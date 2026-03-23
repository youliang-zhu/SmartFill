"""
Recognize 模块 — VLM 识别 + preprocess 匹配

职责:
1. 将 PDF 页面渲染为截图
2. 调用 VLM（每页一次），纯看截图，输出分好组的字段列表
3. 将 VLM 输出与 preprocess 的 detected_fields 做文本匹配（取交集）
4. 输出 matched_fields：VLM 语义信息 + preprocess 精确 fill_rect
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz
from openai import OpenAI

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VLM Prompt
# ---------------------------------------------------------------------------

VLM_PROMPT = """You are a form field analyzer. You will receive a screenshot of one page from a PDF form.

Your tasks:
1. Identify all fields on this page that need to be filled in by a user.
2. Group related fields together. Here, "related" means: if some questions cannot be correctly answered without their surrounding context, then they are related and must be placed in the same group. In other words, if related questions are split into different groups, users may feel confused when filling out the form and may not know which questions are related.
3. For each field, provide:
   - "label": the complete label text shown on the form. Important! This must be exactly the same as the label text on the form. Do not rewrite or simplify it, and do not translate it into another language. Again, do not rewrite or simplify it. It must be exactly identical.
   - "type": use "text" for text input fields, and "checkbox" for checkbox/radio button fields
   - "options": (only for checkbox type) list all available options shown on the form

Rules:
- Include only labels and checkboxes for fields that users need to fill in. Do not include:
- Section headers, titles, or instructions
- Pre-printed text that is not a field label
- Page numbers, form numbers, or reference codes
- For checkbox fields, "label" should be the question or prompt, and "options" should list all options
- Labels and options must use exactly the same text as printed on the form; do not rewrite
- Each field can appear in only one group
- Group names should be short snake_case identifiers

Output only valid JSON in the following format:
{
  "groups": [
    {
      "group_name": "string",
      "group_description": "string",
      "fields": [
        {"label": "string", "type": "text"},
        {"label": "string", "type": "checkbox", "options": ["string"]}
      ]
    }
  ]
}
"""

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PageRecognizeResult:
    page_num: int
    matched_groups: List[Dict[str, Any]] = field(default_factory=list)
    vlm_raw: Optional[Dict[str, Any]] = None
    unmatched_vlm_count: int = 0
    unmatched_pp_count: int = 0


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------


def render_page_image(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """渲染 PDF 页面为 PNG 图片。page_num 从 1 开始。"""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


# ---------------------------------------------------------------------------
# VLM call
# ---------------------------------------------------------------------------


def call_vlm(img_bytes: bytes, settings: Settings | None = None) -> Dict[str, Any]:
    """调用 VLM API，返回解析后的 JSON。"""
    settings = settings or get_settings()
    client = OpenAI(
        api_key=settings.resolved_vlm_api_key,
        base_url=settings.resolved_vlm_base_url,
    )
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model=settings.resolved_vlm_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VLM_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                        },
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )
    raw_text = response.choices[0].message.content
    return json.loads(raw_text)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

_MATCH_THRESHOLD = 0.45
_TOKEN_RE = re.compile(r"[A-Za-z0-9\u00C0-\u024F]+")
_WS_RE = re.compile(r"\s+")
_CHAR_EQUIV = str.maketrans({
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "：": ":",
})


def _normalize(text: str) -> str:
    s = (text or "").strip().lower()
    s = s.translate(_CHAR_EQUIV)
    # 用户要求：比较时移除所有空格
    s = _WS_RE.sub("", s)
    return s


def _similarity(a: str, b: str) -> float:
    """文本相似度：精确 > 包含 > 模糊。"""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower().translate(_CHAR_EQUIV))


def _informative_len(text: str) -> int:
    return sum(len(tok) for tok in _tokenize(text))


def _token_jaccard(a: str, b: str) -> float:
    ta = set(_tokenize(a))
    tb = set(_tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _layered_text_score(vlm_label: str, pp_label: str) -> tuple[int, float, float]:
    """
    分层文本匹配:
    1) exact
    2) exact subset/superset

    Returns:
        (tier, semantic_score, assignment_score)
    """
    na, nb = _normalize(vlm_label), _normalize(pp_label)
    if not na or not nb:
        return 0, 0.0, 0.0

    # Tier 3: 精确匹配（含精确子集/超集）
    if na == nb:
        return 3, 1.0, 31.0

    if na in nb or nb in na:
        short = na if len(na) <= len(nb) else nb
        long_ = nb if len(na) <= len(nb) else na
        short_info = _informative_len(short)
        long_info = _informative_len(long_)
        cover = (short_info / long_info) if long_info > 0 else 0.0
        tok = _token_jaccard(na, nb)
        # 子集也归为“精确层”，但分值由覆盖率控制，避免短碎片拿高分
        sem = min(0.995, 0.65 + 0.35 * (0.85 * cover + 0.15 * tok))
        return 3, sem, 30.0 + sem

    # Tier 2: 轻量增强（仅做字符级清洗后的包含/相等）
    # - 去除所有非字母数字字符
    # - 保留两层方案，不引入模糊编辑距离
    va = "".join(_tokenize(vlm_label))
    pa = "".join(_tokenize(pp_label))
    if not va or not pa:
        return 0, 0.0, 0.0

    if va == pa:
        return 2, 0.94, 20.94

    if va in pa or pa in va:
        short = va if len(va) <= len(pa) else pa
        long_ = pa if len(va) <= len(pa) else va
        cover = (len(short) / len(long_)) if len(long_) > 0 else 0.0
        tok = _token_jaccard(va, pa)
        sem = min(0.93, 0.30 + 0.63 * cover + 0.07 * tok)
        return 2, sem, 20.0 + sem

    # Not matched in the first two tiers
    return 0, 0.0, 0.0


def _find_font_size(
    label_bbox: tuple,
    text_spans: List[Dict[str, Any]],
) -> float:
    """从 preprocess text_spans 中查找与 label_bbox 最近的 font_size。"""
    if not label_bbox or not text_spans:
        return 10.0
    lx0, ly0, lx1, ly1 = label_bbox
    lcy = (ly0 + ly1) / 2.0
    lcx = (lx0 + lx1) / 2.0
    best_dist = 1e9
    best_size = 10.0
    for span in text_spans:
        sb = span.get("bbox")
        if not sb:
            continue
        scx = (sb[0] + sb[2]) / 2.0
        scy = (sb[1] + sb[3]) / 2.0
        dist = abs(scx - lcx) + abs(scy - lcy)
        if dist < best_dist:
            best_dist = dist
            best_size = span.get("font_size", 10.0)
    return best_size


def _hungarian_min_cost(cost: List[List[float]]) -> List[int]:
    """
    Hungarian algorithm (min-cost assignment).
    Returns row->col assignment for square matrix.
    """
    n = len(cost)
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        minv = [float("inf")] * (n + 1)
        used = [False] * (n + 1)
        j0 = 0
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment = [-1] * n
    for j in range(1, n + 1):
        if p[j] != 0:
            assignment[p[j] - 1] = j - 1
    return assignment


def _match_text_fields_global(
    vlm_text_items: List[tuple[int, int, Dict[str, Any]]],
    pp_text: List[Dict[str, Any]],
    text_spans: List[Dict[str, Any]],
) -> tuple[Dict[tuple[int, int], Dict[str, Any]], set]:
    """
    对整页 text 字段做全局一对一匹配（VLM 优先，按分层相似度最大化）。
    Returns:
      - (group_idx, field_idx) -> matched field payload
      - used_pp_ids
    """
    if not vlm_text_items or not pp_text:
        return {}, set()

    m = len(vlm_text_items)
    n = len(pp_text)
    dim = max(m, n)

    semantic: List[List[float]] = [[0.0] * n for _ in range(m)]
    assign_profit: List[List[float]] = [[0.0] * n for _ in range(m)]
    for i, (_, _, vf) in enumerate(vlm_text_items):
        vlabel = vf.get("label", "")
        for j, pp in enumerate(pp_text):
            plabel = pp.get("label", "")
            _, sem, prof = _layered_text_score(vlabel, plabel)
            semantic[i][j] = sem
            assign_profit[i][j] = prof

    # pad to square matrix with zero-profit dummy rows/cols
    profit_square: List[List[float]] = [[0.0] * dim for _ in range(dim)]
    for i in range(m):
        for j in range(n):
            profit_square[i][j] = assign_profit[i][j]

    max_profit = max((profit_square[i][j] for i in range(dim) for j in range(dim)), default=0.0)
    cost_square: List[List[float]] = [[max_profit - profit_square[i][j] for j in range(dim)] for i in range(dim)]
    row_to_col = _hungarian_min_cost(cost_square)

    match_map: Dict[tuple[int, int], Dict[str, Any]] = {}
    used_pp_ids: set = set()
    for i in range(m):
        j = row_to_col[i]
        if j < 0 or j >= n:
            continue  # matched to dummy column
        gi, fi, vf = vlm_text_items[i]
        pp = pp_text[j]
        pp_id = pp["field_id"]
        sem = semantic[i][j]
        prof = assign_profit[i][j]
        # 取消强制绑定：无有效相似度时不分配
        if sem <= 0.0 or prof <= 0.0:
            continue
        if pp_id in used_pp_ids:
            continue
        used_pp_ids.add(pp_id)
        font_size = _find_font_size(pp.get("label_bbox"), text_spans)
        match_map[(gi, fi)] = {
            "vlm_label": vf.get("label", ""),
            "type": "text",
            "field_id": pp_id,
            "fill_rect": pp["fill_rect"],
            "label_bbox": pp.get("label_bbox"),
            "confidence": pp.get("confidence", 0.0),
            "match_score": round(sem, 3),
            "font_size": font_size,
        }
    return match_map, used_pp_ids


def _match_checkbox(
    vlm_field: Dict[str, Any],
    pp_checkboxes: List[Dict[str, Any]],
    used_ids: set,
) -> Optional[Dict[str, Any]]:
    """
    匹配一个 VLM checkbox 字段到 preprocess checkbox 字段。

    preprocess checkbox 字段结构:
      - label: 问题文本
      - options: ["Yes", "No", ...]
      - checkbox_positions: [{"bbox": (...), "option": "Yes"}, ...]
    """
    vlm_label = vlm_field["label"]
    vlm_options = [opt.strip().lower() for opt in vlm_field.get("options", [])]
    if not vlm_options:
        return None

    # 策略: 用 options 文本去匹配 preprocess checkbox 的 options
    best_pp = None
    best_score = 0.0
    for pp in pp_checkboxes:
        pp_id = pp["field_id"]
        if pp_id in used_ids:
            continue
        pp_options = [opt.strip().lower() for opt in pp.get("options", [])]
        if not pp_options:
            continue

        # options 重叠度
        common = set(vlm_options) & set(pp_options)
        if not common:
            continue
        score = len(common) / max(len(vlm_options), len(pp_options))

        # 也考虑 label 相似度
        label_sim = _similarity(vlm_label, pp.get("label", ""))
        combined = score * 0.6 + label_sim * 0.4

        if combined > best_score:
            best_score = combined
            best_pp = pp

    if best_pp is None:
        return None

    used_ids.add(best_pp["field_id"])

    # 从 checkbox_positions 提取每个 option 的精确 rect
    matched_options = []
    for cp in best_pp.get("checkbox_positions", []):
        matched_options.append({
            "option_text": cp.get("option", ""),
            "fill_rect": cp["bbox"],
        })

    # 如果没有 checkbox_positions，回退到整体 fill_rect
    if not matched_options:
        matched_options.append({
            "option_text": "",
            "fill_rect": best_pp["fill_rect"],
        })

    return {
        "vlm_label": vlm_label,
        "type": "checkbox",
        "field_id": best_pp["field_id"],
        "options": matched_options,
        "match_score": round(best_score, 3),
    }


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------


def match_fields(
    vlm_groups: List[Dict[str, Any]],
    preprocess_fields: List[Dict[str, Any]],
    text_spans: List[Dict[str, Any]] | None = None,
) -> tuple[List[Dict[str, Any]], int, int]:
    """
    将 VLM 输出的字段与 preprocess detected_fields 做匹配。

    Returns:
        (matched_groups, unmatched_vlm_count, unmatched_pp_count)
    """
    text_spans = text_spans or []
    pp_text = [f for f in preprocess_fields if f.get("field_type") != "checkbox"]
    pp_checkbox = [f for f in preprocess_fields if f.get("field_type") == "checkbox"]
    # 1) text 字段先做全局一对一分配（避免顺序贪心误绑）
    vlm_text_items: List[tuple[int, int, Dict[str, Any]]] = []
    for gi, group in enumerate(vlm_groups):
        for fi, vf in enumerate(group.get("fields", [])):
            if vf.get("type", "text") != "checkbox":
                vlm_text_items.append((gi, fi, vf))
    text_match_map, used_text_ids = _match_text_fields_global(vlm_text_items, pp_text, text_spans)

    # 2) checkbox 继续按 options + label 匹配
    used_checkbox_ids: set = set()
    total_vlm = 0
    total_matched = 0
    matched_groups: List[Dict[str, Any]] = []
    for gi, group in enumerate(vlm_groups):
        matched_fields: List[Dict[str, Any]] = []
        for fi, vlm_field in enumerate(group.get("fields", [])):
            total_vlm += 1
            field_type = vlm_field.get("type", "text")
            if field_type == "checkbox":
                match = _match_checkbox(vlm_field, pp_checkbox, used_checkbox_ids)
            else:
                match = text_match_map.get((gi, fi))

            if match is not None:
                matched_fields.append(match)
                total_matched += 1

        if matched_fields:
            matched_groups.append({
                "group_name": group.get("group_name", "unknown"),
                "group_description": group.get("group_description", ""),
                "fields": matched_fields,
            })

    unmatched_vlm = total_vlm - total_matched
    unmatched_pp = len(preprocess_fields) - (len(used_text_ids) + len(used_checkbox_ids))

    return matched_groups, unmatched_vlm, unmatched_pp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def recognize_page(
    pdf_path: str,
    page_num: int,
    preprocess_fields: List[Dict[str, Any]],
    text_spans: List[Dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> PageRecognizeResult:
    """
    对单页执行 VLM 识别 + 匹配。

    1. 渲染页面截图
    2. 调用 VLM 获取分组字段
    3. 与 preprocess_fields 做文本匹配
    4. 返回 PageRecognizeResult
    """
    settings = settings or get_settings()

    # 1. 渲染截图
    img_bytes = render_page_image(pdf_path, page_num)

    # 2. 调用 VLM
    vlm_result = call_vlm(img_bytes, settings)
    vlm_groups = vlm_result.get("groups", [])

    logger.info(
        "VLM page %d: %d groups, %d fields",
        page_num,
        len(vlm_groups),
        sum(len(g.get("fields", [])) for g in vlm_groups),
    )

    # 3. 匹配
    matched_groups, unmatched_vlm, unmatched_pp = match_fields(
        vlm_groups, preprocess_fields, text_spans
    )

    logger.info(
        "Match page %d: %d matched groups, unmatched_vlm=%d, unmatched_pp=%d",
        page_num, len(matched_groups), unmatched_vlm, unmatched_pp,
    )

    return PageRecognizeResult(
        page_num=page_num,
        matched_groups=matched_groups,
        vlm_raw=vlm_result,
        unmatched_vlm_count=unmatched_vlm,
        unmatched_pp_count=unmatched_pp,
    )
