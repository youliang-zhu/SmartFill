"""Preprocess 入口 — Phase 1 提取 + Phase 1.5 续行合并 + Phase 2 字段收集。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import fitz

from app.services.native.preprocess.collector.collect_checkboxes import collect_checkboxes
from app.services.native.preprocess.collector.collect_text_fields import collect_text_fields


class LabelFirstMixin:
    """Preprocess 入口方法。"""

    def detect_page_v2(self, page: fitz.Page, page_num: int, pdf_path: str) -> Dict[str, Any]:
        """单页检测入口。Phase 1 → Phase 1.5 → Phase 2（checkbox → text → table）。"""
        text_spans = self.extract_text_spans(page, page_num)
        text_lines = self._extract_text_lines(page, page_num)
        drawing_data = self.extract_drawings(page, page_num)
        tables = self._build_table_grids(drawing_data, page_num)
        page_rect = self._rect_tuple(page.rect)

        # Phase 1.5：续行合并（Union-Find pairwise，含矢量边界检查）
        merged_lines, _ = self._merge_continuation_lines(text_lines, drawing_data=drawing_data)

        # Phase 1.6：左右融合（短文本以字母/数字开头且 ≤ 10 字符 → 与右侧合并）
        merged_lines = self._merge_left_right(merged_lines)

        # Phase 1 输出打包
        phase1_data = {
            "page_num": page_num,
            "pdf_path": pdf_path,
            "page_size": page_rect,
            "text_spans": text_spans,
            "text_lines": merged_lines,
            "drawing_data": drawing_data,
            "table_structures": tables,
        }

        # Phase 2A：Checkbox 收集
        consumed: set[str] = set()
        checkbox_fields, consumed = collect_checkboxes(phase1_data, consumed)

        # Phase 2B：Text 字段收集（传入 checkbox 输出作为禁区）
        text_fields, consumed_text = collect_text_fields(phase1_data, consumed, checkbox_fields=checkbox_fields)
        consumed |= consumed_text

        # Phase 2C：table（待实现）
        detected_fields = checkbox_fields + text_fields

        return {
            "page_num": page_num,
            "page_size": page_rect,
            "text_spans": text_spans,
            "text_lines": merged_lines,
            "table_structures": tables,
            "detected_fields": detected_fields,
        }

    def detect_page(self, page: fitz.Page, page_num: int, pdf_path: str) -> Dict[str, Any]:
        return self.detect_page_v2(page=page, page_num=page_num, pdf_path=pdf_path)

    def detect_all(self, pdf_path: Path) -> Dict[str, Any]:
        doc = fitz.open(str(pdf_path))
        pages = []
        for i, page in enumerate(doc, start=1):
            pages.append(self.detect_page(page, page_num=i, pdf_path=str(pdf_path)))
        doc.close()

        total_fields = sum(len(p["detected_fields"]) for p in pages)
        return {
            "pdf_path": str(pdf_path),
            "page_count": len(pages),
            "detected_field_count": total_fields,
            "pages": pages,
        }
