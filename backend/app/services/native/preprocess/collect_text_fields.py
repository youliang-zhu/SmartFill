"""Phase 2B — Text 字段收集器。

从 Phase 1 数据中收集所有"可能是 label"的文本行：
1. 去掉被 checkbox（Phase 2A）消耗的行
2. 去掉表格 zone 内的行
3. 去掉字数超过阈值的纯说明性文字（单语 >30 词，双语 >60 词）
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from app.services.native.preprocess.collect_checkboxes import (
    _detect_table_zones,
    _in_table_zone,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_MAX_WORDS_SINGLE = 30   # 单语行最大词数
_MAX_WORDS_BILINGUAL = 60  # 双语行最大词数（双语行词数翻倍）


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _is_bilingual(text: str) -> bool:
    """检测是否为双语文本（同时含 ASCII 拉丁字母和扩展拉丁字母/西班牙语特征）。

    简单判断：文本中同时出现 '/' 分隔的两段，
    或包含常见西班牙语字符（á, é, í, ó, ú, ñ, ¿, ¡）。
    """
    spanish_chars = set("áéíóúñ¿¡ÁÉÍÓÚÑ")
    return bool(spanish_chars & set(text)) or " / " in text


def _word_count(text: str) -> int:
    """统计文本词数。"""
    return len(text.split())


def _bbox_center_y(bbox: Tuple[float, ...]) -> float:
    return (bbox[1] + bbox[3]) / 2.0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def collect_text_fields(
    phase1_data: Dict[str, Any],
    consumed: Set[str],
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """从 Phase 1 数据中收集 text 字段。

    Returns:
        - text 字段列表，每个含 field_type, label, label_bbox
        - 新增的 consumed 集合
    """
    merged_lines: List[Dict[str, Any]] = phase1_data.get("text_lines", [])
    drawing_data: Dict[str, Any] = phase1_data.get("drawing_data", {})
    tables: List[Dict[str, Any]] = phase1_data.get("table_structures", [])
    v_lines = drawing_data.get("vertical_lines", [])

    # 已被 checkbox 消耗的行 index
    consumed_line_ids: Set[int] = set()
    for c in consumed:
        if c.startswith("line:"):
            consumed_line_ids.add(int(c.split(":")[1]))

    # 表格区域
    table_zones = _detect_table_zones(tables, v_lines)

    fields: List[Dict[str, Any]] = []
    new_consumed: Set[str] = set()

    for idx, line in enumerate(merged_lines):
        # 1. 跳过被 checkbox 消耗的行
        if idx in consumed_line_ids:
            continue

        text = line.get("text", "").strip()
        if not text:
            continue

        bbox = line.get("bbox", (0, 0, 0, 0))

        # 2. 跳过表格 zone 内的行
        if _in_table_zone(_bbox_center_y(bbox), table_zones):
            continue

        # 3. 跳过字数过多的说明性文字
        wc = _word_count(text)
        threshold = _MAX_WORDS_BILINGUAL if _is_bilingual(text) else _MAX_WORDS_SINGLE
        if wc > threshold:
            continue

        fields.append({
            "field_type": "text",
            "label": text,
            "label_bbox": list(bbox),
        })
        new_consumed.add(f"line:{idx}")

    return fields, new_consumed
