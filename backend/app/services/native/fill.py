"""
Fill 模块 — LLM 基于分组的自动填写

职责:
1. 接收 matched_groups（来自 Recognize）+ user memory
2. 每页一次 LLM call，输出所有字段的填写值
3. 输出结构化 JSON：每个 field_id 对应填写值
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------

FILL_PROMPT_TEMPLATE = """\
You are a form filling assistant. You are given a list of form field groups and user information. Your task is to fill in each field with the appropriate value from the user's information.

## User Information
{user_memory_content}

## Form Fields
{fields_json}

## Instructions
1. For each "text" field, provide the appropriate value based on the user's information and the field label.
2. For each "checkbox" field, set the correct option to "checked" and leave others as "" (empty string).
3. If the user's information does not contain a value for a field, set value to "" (empty string) — do NOT guess or make up information.
4. Use the exact format requested by the field label:
   - Dates: use MM/DD/YYYY unless the form specifies otherwise
   - Phone: use the format shown on the form, or default to (XXX) XXX-XXXX
   - Names: follow the order specified by the label (e.g., "Last, First, Middle")
5. For checkbox fields, each option has a field_id. Set value to "checked" for the correct option(s), "" for the rest.

Output ONLY valid JSON:
{{
  "filled_fields": [
    {{"field_id": "string", "value": "string"}},
    ...
  ]
}}
"""

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FilledField:
    field_id: str
    value: str
    fill_rect: tuple
    field_type: str = "text"
    font_size: float = 10.0


@dataclass
class PageFillResult:
    page_num: int
    filled_fields: List[FilledField] = field(default_factory=list)
    unfilled_count: int = 0


# ---------------------------------------------------------------------------
# matched_groups → LLM input conversion
# ---------------------------------------------------------------------------


def build_llm_input(matched_groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    将 matched_groups 转换为 LLM 输入格式。
    - text 字段直接保留
    - checkbox 字段展开每个 option 为独立 field
    """
    llm_groups: List[Dict[str, Any]] = []
    for group in matched_groups:
        llm_fields: List[Dict[str, Any]] = []
        for f in group["fields"]:
            if f["type"] == "text":
                llm_fields.append({
                    "field_id": f["field_id"],
                    "label": f["vlm_label"],
                    "type": "text",
                })
            elif f["type"] == "checkbox":
                for opt in f.get("options", []):
                    # 每个 option 展开为独立的 field
                    # field_id 用 "原field_id::option_text" 格式，方便回查
                    opt_id = f"{f['field_id']}::{opt['option_text']}"
                    llm_fields.append({
                        "field_id": opt_id,
                        "label": f"{f['vlm_label']} \u2014 {opt['option_text']}",
                        "type": "checkbox",
                    })
        if llm_fields:
            llm_groups.append({
                "group_name": group["group_name"],
                "group_description": group.get("group_description", ""),
                "fields": llm_fields,
            })
    return {"groups": llm_groups}


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def call_llm(
    fields_json: Dict[str, Any],
    user_memory: str,
    settings: Settings | None = None,
) -> Dict[str, Any]:
    """调用 LLM API 填写字段值。"""
    settings = settings or get_settings()
    client = OpenAI(
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
    )
    prompt = FILL_PROMPT_TEMPLATE.format(
        user_memory_content=user_memory,
        fields_json=json.dumps(fields_json, ensure_ascii=False, indent=2),
    )
    response = client.chat.completions.create(
        model=settings.QWEN_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw_text = response.choices[0].message.content
    return json.loads(raw_text)


# ---------------------------------------------------------------------------
# LLM output → FilledField mapping
# ---------------------------------------------------------------------------


def _build_rect_lookup(
    matched_groups: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    构建 field_id → {fill_rect, font_size, type} 的查找表。
    checkbox option 的 key 为 "field_id::option_text"。
    """
    lookup: Dict[str, Dict[str, Any]] = {}
    for group in matched_groups:
        for f in group["fields"]:
            if f["type"] == "text":
                lookup[f["field_id"]] = {
                    "fill_rect": f["fill_rect"],
                    "font_size": f.get("font_size", 10.0),
                    "field_type": "text",
                }
            elif f["type"] == "checkbox":
                for opt in f.get("options", []):
                    opt_id = f"{f['field_id']}::{opt['option_text']}"
                    lookup[opt_id] = {
                        "fill_rect": opt["fill_rect"],
                        "font_size": 10.0,
                        "field_type": "checkbox",
                    }
    return lookup


def _map_llm_output(
    llm_result: Dict[str, Any],
    rect_lookup: Dict[str, Dict[str, Any]],
) -> tuple[List[FilledField], int]:
    """将 LLM 输出映射为 FilledField 列表。"""
    filled: List[FilledField] = []
    unfilled = 0

    for item in llm_result.get("filled_fields", []):
        fid = item.get("field_id", "")
        value = item.get("value", "")
        info = rect_lookup.get(fid)
        if info is None:
            logger.warning("LLM returned unknown field_id: %s", fid)
            unfilled += 1
            continue
        filled.append(FilledField(
            field_id=fid,
            value=value,
            fill_rect=info["fill_rect"],
            field_type=info["field_type"],
            font_size=info.get("font_size", 10.0),
        ))

    return filled, unfilled


# ---------------------------------------------------------------------------
# User memory
# ---------------------------------------------------------------------------

_DEFAULT_MEMORY_PATH = Path("TestSpace/recognize_fill_test/user_memory.md")


def read_user_memory(memory_path: Path | str | None = None) -> str:
    """读取 user memory 文件内容。"""
    path = Path(memory_path) if memory_path else _DEFAULT_MEMORY_PATH
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("User memory file not found: %s", path)
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fill_page(
    page_num: int,
    matched_groups: List[Dict[str, Any]],
    user_memory: str,
    settings: Settings | None = None,
) -> PageFillResult:
    """
    对单页执行 LLM 填写。

    1. 将 matched_groups 转换为 LLM 输入格式
    2. 调用 LLM 获取填写值
    3. 将填写值与 fill_rect 关联
    4. 返回 PageFillResult
    """
    settings = settings or get_settings()

    # 1. 构建 LLM 输入
    llm_input = build_llm_input(matched_groups)
    total_fields = sum(len(g["fields"]) for g in llm_input.get("groups", []))
    if total_fields == 0:
        return PageFillResult(page_num=page_num)

    logger.info("Fill page %d: %d fields in %d groups",
                page_num, total_fields, len(llm_input["groups"]))

    # 2. 调用 LLM
    llm_result = call_llm(llm_input, user_memory, settings)

    # 3. 映射回 fill_rect
    rect_lookup = _build_rect_lookup(matched_groups)
    filled, unfilled = _map_llm_output(llm_result, rect_lookup)

    logger.info("Fill page %d: %d filled, %d unfilled", page_num, len(filled), unfilled)

    return PageFillResult(
        page_num=page_num,
        filled_fields=filled,
        unfilled_count=unfilled,
    )
