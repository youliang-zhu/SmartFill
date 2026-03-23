from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

import fitz

from app.services.native.preprocess.types import LabelCandidate, RectTuple


class LabelFirstMixin:
    """Preprocess v2 Label-first 流程实现。"""
    @staticmethod
    def _is_url_like_text(text: str) -> bool:
        t = text.strip().lower()
        return t.startswith("http://") or t.startswith("https://") or t.startswith("www.")

    @staticmethod
    def _is_yes_no_text(text: str) -> bool:
        return bool(re.fullmatch(r"(?i)(yes|no)", text.strip()))

    @staticmethod
    def _is_emphasis_underline(
        label_bbox: RectTuple,
        line_x0: float,
        line_x1: float,
    ) -> bool:
        label_x0 = float(label_bbox[0])
        label_x1 = float(label_bbox[2])
        label_w = max(1.0, label_x1 - label_x0)
        overlap = max(0.0, min(line_x1, label_x1) - max(line_x0, label_x0))
        coverage = overlap / label_w
        # 强调线特征：与文字高度对齐，覆盖率高，且不会明显延伸到文字右侧空白区。
        return (
            coverage >= 0.85
            and abs(line_x0 - label_x0) <= 5.0
            and (line_x1 - label_x1) <= 6.0
        )

    def _should_skip_enum_candidate(
        self,
        full_text: str,
        prefix_token: str,
        content_after_prefix: str,
    ) -> bool:
        if re.match(r"^[A-Z]\.[A-Z]\.", full_text):
            return True
        if self._is_section_header(content_after_prefix):
            return True
        if len(prefix_token) == 1 and prefix_token.isalpha() and prefix_token.isupper():
            lower = content_after_prefix.lower()
            if self._word_count(content_after_prefix) >= 3 and (
                lower.endswith("information")
                or "section" in lower
                or "department" in lower
                or "instructions" in lower
            ):
                return True
        return False

    def _find_table_cell_for_line(
        self,
        line_bbox: RectTuple,
        tables: List[Dict[str, Any]],
    ) -> RectTuple | None:
        cx = (line_bbox[0] + line_bbox[2]) / 2.0
        cy = (line_bbox[1] + line_bbox[3]) / 2.0
        for table in tables:
            grid_x = table.get("grid_x", [])
            grid_y = table.get("grid_y", [])
            if len(grid_x) < 2 or len(grid_y) < 2:
                continue
            for r in range(len(grid_y) - 1):
                for c in range(len(grid_x) - 1):
                    cell = (
                        float(grid_x[c]),
                        float(grid_y[r]),
                        float(grid_x[c + 1]),
                        float(grid_y[r + 1]),
                    )
                    if cell[0] - 1.0 <= cx <= cell[2] + 1.0 and cell[1] - 1.0 <= cy <= cell[3] + 1.0:
                        return cell
        return None

    @staticmethod
    def _same_table_cell(a: RectTuple, b: RectTuple, tol: float = 3.0) -> bool:
        return (
            abs(a[0] - b[0]) <= tol
            and abs(a[1] - b[1]) <= tol
            and abs(a[2] - b[2]) <= tol
            and abs(a[3] - b[3]) <= tol
        )

    def _is_short_colon_label_line(self, text: str) -> bool:
        t = self._normalize_text(text)
        if not t:
            return False
        if not re.search(r":\s*$", t):
            return False
        return len(t) <= 80 and self._word_count(t) <= 12

    def _contains_checkbox_glyph(self, text: str) -> bool:
        if self._is_checkbox_glyph(text):
            return True
        glyph_tokens = {"☐", "☑", "☒", "□", "■", "✓", "✔", "", ""}
        if any(ch in glyph_tokens for ch in text):
            return True
        return any(0xF000 <= ord(ch) <= 0xF0FF for ch in text)

    def _find_text_left_of(
        self,
        text_spans: List[Dict[str, Any]],
        target_x0: float,
        target_y: float,
        max_gap: float = 80.0,
        y_tolerance: float = 8.0,
    ) -> Dict[str, Any] | None:
        candidates: List[Tuple[float, Dict[str, Any]]] = []
        for sp in text_spans:
            sp_bbox = sp.get("bbox")
            if not sp_bbox:
                continue
            sp_x1 = float(sp_bbox[2])
            sp_cy = (float(sp_bbox[1]) + float(sp_bbox[3])) / 2.0
            if sp_x1 > target_x0 + 2.0:
                continue
            if target_x0 - sp_x1 > max_gap:
                continue
            if abs(sp_cy - target_y) > y_tolerance:
                continue
            candidates.append((target_x0 - sp_x1, sp))
        if not candidates:
            return None
        candidates.sort(key=lambda t: t[0])
        return candidates[0][1]

    def _find_text_above(
        self,
        text_lines: List[Dict[str, Any]],
        x0: float,
        x1: float,
        y: float,
        max_gap: float = 20.0,
    ) -> Dict[str, Any] | None:
        candidates: List[Tuple[float, Dict[str, Any]]] = []
        for tl in text_lines:
            tl_bbox = tl.get("bbox")
            if not tl_bbox:
                continue
            tl_y1 = float(tl_bbox[3])
            if tl_y1 > y + 2.0:
                continue
            if y - tl_y1 > max_gap:
                continue
            overlap = self._line_overlap_ratio(x0, x1, float(tl_bbox[0]), float(tl_bbox[2]))
            if overlap < 0.1:
                continue
            candidates.append((y - tl_y1, tl))
        if not candidates:
            return None
        candidates.sort(key=lambda t: t[0])
        return candidates[0][1]

    def _is_table_border_line(
        self,
        ln: Dict[str, float],
        tables: List[Dict[str, Any]],
    ) -> bool:
        return self._line_is_table_border(ln, tables)

    def _collect_underline_labels(
        self,
        text_lines: List[Dict[str, Any]],
        text_spans: List[Dict[str, Any]],
        drawing_data: Dict[str, Any],
        tables: List[Dict[str, Any]],
        page_num: int,
    ) -> List[LabelCandidate]:
        labels: List[LabelCandidate] = []
        h_lines = drawing_data.get("horizontal_lines", [])
        for idx, ln in enumerate(h_lines, start=1):
            x0 = float(ln.get("x0", 0.0))
            x1 = float(ln.get("x1", 0.0))
            y = float(ln.get("y", 0.0))
            line_len = x1 - x0

            if line_len < self.ENGINE1_UNDERLINE_MIN_W:
                continue
            if self._is_table_border_line(ln, tables):
                continue

            best_label = self._find_text_left_of(text_spans, x0, y, max_gap=80.0, y_tolerance=8.0)
            if best_label:
                text = self._normalize_text(str(best_label.get("text", "")))
                label_bbox = tuple(best_label["bbox"])
                if not text:
                    continue
                if self._is_instructional_text(text):
                    continue
                if self._is_likely_running_text(text):
                    continue
                if self._is_checkbox_glyph(text):
                    continue
                if self._is_yes_no_text(text):
                    continue
                if self._is_url_like_text(text):
                    continue
                if self._is_emphasis_underline(label_bbox, x0, x1):
                    continue
                labels.append(
                    LabelCandidate(
                        text=text,
                        bbox=label_bbox,
                        source="underline",
                        confidence=0.74,
                        page_num=page_num,
                        underline_bbox=(x0, y - 1.0, x1, y + 1.0),
                    )
                )
                continue

            above_label = self._find_text_above(text_lines, x0, x1, y, max_gap=20.0)
            if above_label:
                label_text = self._normalize_text(str(above_label.get("text", "")))
                label_bbox = tuple(above_label["bbox"])
                if not label_text:
                    label_text = f"field_line_{page_num}_{idx:03d}_{int(round(y))}"
                elif (
                    self._is_instructional_text(label_text)
                    or self._is_likely_running_text(label_text)
                    or self._is_checkbox_glyph(label_text)
                    or self._is_yes_no_text(label_text)
                    or self._is_url_like_text(label_text)
                ):
                    continue
                if self._is_emphasis_underline(label_bbox, x0, x1):
                    continue
            else:
                label_text = f"field_line_{page_num}_{idx:03d}_{int(round(y))}"
                label_bbox = (x0, y - 12.0, x0 + 40.0, y)
            labels.append(
                LabelCandidate(
                    text=label_text,
                    bbox=label_bbox,
                    source="underline",
                    confidence=0.50,
                    page_num=page_num,
                    underline_bbox=(x0, y - 1.0, x1, y + 1.0),
                )
            )
        return labels

    def _collect_colon_labels(
        self,
        text_spans: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
        page_num: int,
    ) -> List[LabelCandidate]:
        del text_lines
        labels: List[LabelCandidate] = []
        for sp in text_spans:
            text = self._normalize_text(str(sp.get("text", "")))
            if not text:
                continue
            if not re.search(r":\s*$", text):
                continue
            if self._is_instructional_text(text):
                continue
            if self._is_likely_running_text(text):
                continue
            if len(text) > self.MAX_LABEL_LEN:
                continue
            labels.append(
                LabelCandidate(
                    text=text,
                    bbox=tuple(sp["bbox"]),
                    source="colon",
                    confidence=0.70,
                    page_num=page_num,
                )
            )
        return labels

    def _extract_embedded_enum_labels_from_text(
        self,
        text: str,
        line_bbox: RectTuple,
        page_num: int,
        source: str,
        table_cell_bbox: RectTuple | None,
    ) -> List[LabelCandidate]:
        matches = list(self.ENUM_PREFIX_EMBEDDED_RE.finditer(text))
        if len(matches) < 2:
            return []

        out: List[LabelCandidate] = []
        line_x0, line_y0, line_x1, line_y1 = line_bbox
        width = max(1.0, line_x1 - line_x0)
        text_len = max(1, len(text))
        for idx, m in enumerate(matches):
            seg_start = m.start()
            seg_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            seg_text = self._normalize_text(text[seg_start:seg_end])
            if len(seg_text) < 2:
                continue
            if self._is_instructional_text(seg_text):
                continue
            rel0 = seg_start / text_len
            rel1 = seg_end / text_len
            sub_bbox = (
                self._round(line_x0 + width * rel0),
                self._round(line_y0),
                self._round(line_x0 + width * rel1),
                self._round(line_y1),
            )
            out.append(
                LabelCandidate(
                    text=seg_text,
                    bbox=sub_bbox,
                    source=source,
                    confidence=0.64,
                    page_num=page_num,
                    table_cell_bbox=table_cell_bbox,
                )
            )
        return out

    def _collect_enum_labels(
        self,
        text_lines: List[Dict[str, Any]],
        tables: List[Dict[str, Any]],
        page_num: int,
    ) -> List[LabelCandidate]:
        labels: List[LabelCandidate] = []

        # 第一轮：全局行首枚举（不再做续行合并，续行由 Phase 1 _merge_continuation_lines 统一处理）
        for tl in text_lines:
            if not tl.get("bbox"):
                continue
            text = self._normalize_text(str(tl.get("text", "")))
            if not text:
                continue
            enum_match = self.ENUM_PREFIX_RE.match(text)
            if not enum_match:
                continue
            if self._is_instructional_text(text):
                continue
            prefix_token = str(enum_match.group(1) or "")
            content_after_prefix = self._normalize_text(text[enum_match.end():])
            if len(content_after_prefix) < 2:
                continue
            if self._should_skip_enum_candidate(
                full_text=text,
                prefix_token=prefix_token,
                content_after_prefix=content_after_prefix,
            ):
                continue

            labels.append(
                LabelCandidate(
                    text=text,
                    bbox=tuple(tl["bbox"]),
                    source="enum",
                    confidence=0.65,
                    page_num=page_num,
                )
            )

        # 第二轮：仅表格单元格内部的行内嵌枚举
        for table in tables:
            grid_x = table.get("grid_x", [])
            grid_y = table.get("grid_y", [])
            if len(grid_x) < 2 or len(grid_y) < 2:
                continue
            for r in range(len(grid_y) - 1):
                for c in range(len(grid_x) - 1):
                    cell_bbox = (
                        float(grid_x[c]),
                        float(grid_y[r]),
                        float(grid_x[c + 1]),
                        float(grid_y[r + 1]),
                    )
                    cell_lines = self._get_cell_text_lines(cell_bbox, text_lines)
                    if not cell_lines:
                        continue
                    for ln in cell_lines:
                        line_text = self._normalize_text(str(ln.get("text", "")))
                        if not line_text:
                            continue
                        embedded = self._extract_embedded_enum_labels_from_text(
                            text=line_text,
                            line_bbox=tuple(ln["bbox"]),
                            page_num=page_num,
                            source="enum",
                            table_cell_bbox=cell_bbox,
                        )
                        if embedded:
                            labels.extend(embedded)
        return labels

    def _collect_table_labels(
        self,
        text_lines: List[Dict[str, Any]],
        tables: List[Dict[str, Any]],
        page_num: int,
    ) -> List[LabelCandidate]:
        labels: List[LabelCandidate] = []
        for table in tables:
            grid_x = table.get("grid_x", [])
            grid_y = table.get("grid_y", [])
            if len(grid_x) < 2 or len(grid_y) < 2:
                continue

            for r in range(len(grid_y) - 1):
                for c in range(len(grid_x) - 1):
                    cell_bbox = (
                        float(grid_x[c]),
                        float(grid_y[r]),
                        float(grid_x[c + 1]),
                        float(grid_y[r + 1]),
                    )
                    cell_w = cell_bbox[2] - cell_bbox[0]
                    cell_h = cell_bbox[3] - cell_bbox[1]
                    if cell_w < self.MIN_FIELD_WIDTH or cell_h < self.MIN_FIELD_HEIGHT:
                        continue

                    cell_texts = self._get_cell_text_lines(cell_bbox, text_lines)
                    if not cell_texts:
                        continue
                    combined_text = self._normalize_text(" ".join(str(t.get("text", "")) for t in cell_texts))
                    if not combined_text:
                        continue
                    if self._is_instructional_text(combined_text):
                        continue
                    if self._is_checkbox_glyph(combined_text):
                        continue
                    if len(combined_text) > self.MAX_LABEL_LEN:
                        continue
                    alpha_count = sum(1 for ch in combined_text if ch.isalpha())
                    if alpha_count < 2:
                        continue

                    text_area = sum(
                        self._bbox_width(tuple(t["bbox"])) * self._bbox_height(tuple(t["bbox"]))
                        for t in cell_texts
                    )
                    cell_area = max(1e-6, cell_w * cell_h)
                    text_ratio = text_area / cell_area
                    is_header_only = text_ratio > self.CELL_FILLABLE_BLANK_RATIO

                    labels.append(
                        LabelCandidate(
                            text=combined_text,
                            bbox=tuple(cell_texts[0]["bbox"]),
                            source="table",
                            confidence=0.66 if not is_header_only else 0.45,
                            page_num=page_num,
                            table_cell_bbox=cell_bbox,
                        )
                    )
        return labels

    def _find_dot_runs(self, line_chars: List[Dict[str, Any]]) -> List[Dict[str, float]]:
        runs: List[Dict[str, float]] = []
        i = 0
        n = len(line_chars)
        while i < n:
            if self._char_text(line_chars[i]) != ".":
                i += 1
                continue
            start = i
            prev_x1 = self._safe_float(line_chars[i].get("x1"))
            i += 1
            while i < n:
                ch = line_chars[i]
                if self._char_text(ch) != ".":
                    break
                curr_x0 = self._safe_float(ch.get("x0"))
                if curr_x0 - prev_x1 > 2.0:
                    break
                prev_x1 = self._safe_float(ch.get("x1"))
                i += 1
            end = i
            if end - start < self.DOT_LEADER_MIN_COUNT:
                continue
            runs.append(
                {
                    "x0": self._safe_float(line_chars[start].get("x0")),
                    "x1": self._safe_float(line_chars[end - 1].get("x1")),
                }
            )
        return runs

    def _collect_dotleader_labels(
        self,
        pdf_path: str,
        page_num: int,
        page_rect: RectTuple,
        existing_labels: List[LabelCandidate],
        text_lines: List[Dict[str, Any]],
    ) -> List[LabelCandidate]:
        del page_rect, existing_labels, text_lines
        labels: List[LabelCandidate] = []
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            return labels

        with pdfplumber.open(pdf_path) as pdf:
            if page_num < 1 or page_num > len(pdf.pages):
                return labels
            plumber_page = pdf.pages[page_num - 1]
            chars = plumber_page.chars
            if not chars:
                return labels

        sorted_chars = sorted(
            chars,
            key=lambda c: (
                round(self._safe_float(c.get("top")) / 3.0) * 3.0,
                self._safe_float(c.get("x0")),
            ),
        )
        if not sorted_chars:
            return labels

        char_lines: List[List[Dict[str, Any]]] = []
        current_line = [sorted_chars[0]]
        for ch in sorted_chars[1:]:
            if abs(self._safe_float(ch.get("top")) - self._safe_float(current_line[0].get("top"))) <= 3.0:
                current_line.append(ch)
            else:
                char_lines.append(current_line)
                current_line = [ch]
        char_lines.append(current_line)

        for line_chars in char_lines:
            sorted_line = sorted(line_chars, key=lambda c: self._safe_float(c.get("x0")))
            dot_runs = self._find_dot_runs(sorted_line)
            if not dot_runs:
                continue

            for dot_run in dot_runs:
                left_chars = [c for c in sorted_line if self._safe_float(c.get("x1")) <= dot_run["x0"] + 2.0]
                left_chars = [c for c in left_chars if self._char_text(c).strip()]
                if not left_chars:
                    continue

                label_text = self._normalize_text("".join(self._char_text(c) for c in left_chars)).rstrip(":")
                if not label_text or len(label_text) < 2:
                    continue
                if self._is_instructional_text(label_text):
                    continue
                if self._is_likely_running_text(label_text):
                    continue

                label_x0 = min(self._safe_float(c.get("x0")) for c in left_chars)
                label_y0 = min(self._safe_float(c.get("top")) for c in left_chars)
                label_x1 = max(self._safe_float(c.get("x1")) for c in left_chars)
                label_y1 = max(self._safe_float(c.get("bottom")) for c in left_chars)
                labels.append(
                    LabelCandidate(
                        text=label_text,
                        bbox=(label_x0, label_y0, label_x1, label_y1),
                        source="dotleader",
                        confidence=0.90,
                        page_num=page_num,
                        dotleader_end_x=float(dot_run["x1"]),
                    )
                )

        return labels

    # -------------------- v2: Phase 3 标签去重 --------------------

    def _dedup_labels(self, labels: List[LabelCandidate]) -> List[LabelCandidate]:
        if not labels:
            return []

        sorted_labels = sorted(labels, key=lambda lb: -lb.confidence)
        kept: List[LabelCandidate] = []
        for lb in sorted_labels:
            is_dup = False
            for existing in kept:
                cx1 = (lb.bbox[0] + lb.bbox[2]) / 2.0
                cy1 = (lb.bbox[1] + lb.bbox[3]) / 2.0
                cx2 = (existing.bbox[0] + existing.bbox[2]) / 2.0
                cy2 = (existing.bbox[1] + existing.bbox[3]) / 2.0
                dist = math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)
                if dist > 15.0:
                    continue

                t1 = lb.text.strip().lower()
                t2 = existing.text.strip().lower()
                if t1 == t2 or t1 in t2 or t2 in t1:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(lb)
        return kept

    # -------------------- v2: Phase 4 Rect 分配 --------------------

    def _find_right_empty_cell(
        self,
        cell_bbox: RectTuple,
        tables: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
    ) -> RectTuple | None:
        cx1 = cell_bbox[2]
        cy0 = cell_bbox[1]
        for table in tables:
            grid_x = table.get("grid_x", [])
            grid_y = table.get("grid_y", [])
            for r in range(len(grid_y) - 1):
                for c in range(len(grid_x) - 1):
                    rc = (
                        float(grid_x[c]),
                        float(grid_y[r]),
                        float(grid_x[c + 1]),
                        float(grid_y[r + 1]),
                    )
                    if abs(rc[0] - cx1) < 3.0 and abs(rc[1] - cy0) < 3.0:
                        cell_texts = self._get_cell_text_lines(rc, text_lines)
                        if not cell_texts:
                            return rc
        return None

    def _find_below_empty_in_table(
        self,
        cell_bbox: RectTuple,
        tables: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
    ) -> RectTuple | None:
        cx0, cy1, cx1 = cell_bbox[0], cell_bbox[3], cell_bbox[2]
        padding = 2.0
        for table in tables:
            grid_x = table.get("grid_x", [])
            grid_y = table.get("grid_y", [])
            for r in range(len(grid_y) - 1):
                for c in range(len(grid_x) - 1):
                    rc = (
                        float(grid_x[c]),
                        float(grid_y[r]),
                        float(grid_x[c + 1]),
                        float(grid_y[r + 1]),
                    )
                    if abs(rc[0] - cx0) < 3.0 and abs(rc[2] - cx1) < 3.0 and abs(rc[1] - cy1) < 3.0:
                        cell_texts = self._get_cell_text_lines(rc, text_lines)
                        if not cell_texts:
                            return (
                                self._round(rc[0] + padding),
                                self._round(rc[1] + padding),
                                self._round(rc[2] - padding),
                                self._round(rc[3] - padding),
                            )
        return None

    def _calc_table_cell_rect(
        self,
        lb: LabelCandidate,
        tables: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
    ) -> RectTuple | None:
        cell = lb.table_cell_bbox
        if cell is None:
            return None

        cell_x0, cell_y0, cell_x1, cell_y1 = cell
        label_y1 = lb.bbox[3]
        label_x1 = lb.bbox[2]
        padding = 2.0
        right_candidate: RectTuple | None = None
        below_candidate: RectTuple | None = None

        # 候选 A：label 右侧（同单元格）
        right_rect = (
            self._round(label_x1 + padding),
            self._round(cell_y0 + padding),
            self._round(cell_x1 - padding),
            self._round(cell_y1 - padding),
        )
        if self._bbox_width(right_rect) >= self.MIN_FIELD_WIDTH and self._bbox_height(right_rect) >= self.MIN_FIELD_HEIGHT:
            right_candidate = right_rect

        # 候选 B：label 下方（同单元格）
        below_rect = (
            self._round(cell_x0 + padding),
            self._round(label_y1 + padding),
            self._round(cell_x1 - padding),
            self._round(cell_y1 - padding),
        )
        if self._bbox_width(below_rect) >= self.MIN_FIELD_WIDTH and self._bbox_height(below_rect) >= self.MIN_FIELD_HEIGHT:
            below_candidate = below_rect

        # 同单元格候选优先：右侧/下方都可用时，直接按横向宽度选择更宽者。
        if right_candidate and below_candidate:
            same_cell_candidates = [r for r in (right_candidate, below_candidate) if r[2] >= lb.bbox[0]]
            if same_cell_candidates:
                return max(same_cell_candidates, key=lambda r: self._bbox_width(r))
        elif right_candidate and right_candidate[2] >= lb.bbox[0]:
            return right_candidate
        elif below_candidate and below_candidate[2] >= lb.bbox[0]:
            return below_candidate

        # 同单元格不可用时，再尝试邻接空单元格
        external_candidates: List[RectTuple] = []
        right_cell = self._find_right_empty_cell(cell, tables, text_lines)
        if right_cell is not None:
            external_candidates.append(
                (
                    self._round(right_cell[0] + padding),
                    self._round(right_cell[1] + padding),
                    self._round(right_cell[2] - padding),
                    self._round(right_cell[3] - padding),
                )
            )

        below_space = self._find_below_empty_in_table(cell, tables, text_lines)
        if below_space is not None:
            external_candidates.append(below_space)

        valid_external = [
            r for r in external_candidates
            if self._bbox_width(r) >= self.MIN_FIELD_WIDTH and self._bbox_height(r) >= self.MIN_FIELD_HEIGHT
            and r[2] >= lb.bbox[0]
        ]
        if valid_external:
            return max(valid_external, key=lambda r: self._bbox_width(r))

        return None

    def _find_right_blank(
        self,
        lb: LabelCandidate,
        text_spans: List[Dict[str, Any]],
        v_lines: List[Dict[str, Any]],
        page_rect: RectTuple,
        next_label_x0: float | None,
    ) -> RectTuple | None:
        label_x1 = lb.bbox[2]
        label_y0, label_y1 = lb.bbox[1], lb.bbox[3]
        label_cy = (label_y0 + label_y1) / 2.0

        right_cap = page_rect[2] - 20.0
        if next_label_x0 is not None:
            right_cap = min(right_cap, next_label_x0 - 2.0)

        next_text_x0: float | None = None
        for sp in text_spans:
            sp_bbox = sp.get("bbox")
            if not sp_bbox:
                continue
            sp_cy = (float(sp_bbox[1]) + float(sp_bbox[3])) / 2.0
            if abs(sp_cy - label_cy) >= 8.0:
                continue
            if float(sp_bbox[0]) <= label_x1 + 5.0:
                continue
            if next_text_x0 is None or float(sp_bbox[0]) < next_text_x0:
                next_text_x0 = float(sp_bbox[0])
        if next_text_x0 is not None:
            right_cap = min(right_cap, next_text_x0 - 2.0)

        for vl in v_lines:
            vx = float(vl.get("x", 0.0))
            vy0 = float(vl.get("y0", 0.0))
            vy1 = float(vl.get("y1", 0.0))
            if vx <= label_x1 + 5.0:
                continue
            if vy0 > label_y1 or vy1 < label_y0:
                continue
            if vx < right_cap:
                right_cap = vx - 2.0

        blank_width = right_cap - label_x1 - 2.0
        if blank_width < self.MIN_FIELD_WIDTH:
            return None

        rect = (
            self._round(label_x1 + 2.0),
            self._round(label_y0),
            self._round(right_cap),
            self._round(label_y1),
        )
        if self._bbox_width(rect) < self.MIN_FIELD_WIDTH:
            return None
        return rect

    def _find_below_blank(
        self,
        lb: LabelCandidate,
        text_lines: List[Dict[str, Any]],
        h_lines: List[Dict[str, Any]],
        page_rect: RectTuple,
    ) -> RectTuple | None:
        label_x0 = lb.bbox[0]
        label_y1 = lb.bbox[3]
        label_x1 = lb.bbox[2]

        bottom_cap = label_y1 + 40.0

        for hl in h_lines:
            hy = float(hl.get("y", 0.0))
            if not (label_y1 + 3.0 < hy < bottom_cap):
                continue
            if float(hl.get("x0", 0.0)) <= label_x1 and float(hl.get("x1", 0.0)) >= label_x0:
                bottom_cap = hy - 2.0

        for tl in text_lines:
            tl_bbox = tl.get("bbox")
            if not tl_bbox:
                continue
            tl_y0 = float(tl_bbox[1])
            if not (label_y1 + 3.0 < tl_y0 < bottom_cap):
                continue
            overlap = self._line_overlap_ratio(label_x0, label_x1, float(tl_bbox[0]), float(tl_bbox[2]))
            if overlap > 0.1:
                bottom_cap = tl_y0 - 2.0

        if bottom_cap - label_y1 > self.PROMPT_FALLBACK_MAX_HEIGHT:
            bottom_cap = label_y1 + self.PROMPT_FALLBACK_MAX_HEIGHT

        right_cap = page_rect[2] - 20.0
        width = right_cap - label_x0
        if width < self.PROMPT_FALLBACK_MIN_WIDTH:
            return None

        height = bottom_cap - label_y1
        if height < self.MIN_FIELD_HEIGHT:
            return None

        return (
            self._round(label_x0),
            self._round(label_y1 + 2.0),
            self._round(right_cap),
            self._round(bottom_cap),
        )

    def _assign_fill_rects(
        self,
        labels: List[LabelCandidate],
        drawing_data: Dict[str, Any],
        tables: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
        text_spans: List[Dict[str, Any]],
        page_rect: RectTuple,
    ) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = []
        v_lines = drawing_data.get("vertical_lines", [])
        h_lines = drawing_data.get("horizontal_lines", [])
        sorted_labels = sorted(labels, key=lambda lb: (lb.bbox[1], lb.bbox[0]))

        for i, lb in enumerate(sorted_labels):
            rect: RectTuple | None = None

            next_label_x0: float | None = None
            for j in range(i + 1, len(sorted_labels)):
                nb = sorted_labels[j]
                if abs(((nb.bbox[1] + nb.bbox[3]) / 2.0) - ((lb.bbox[1] + lb.bbox[3]) / 2.0)) < 8.0:
                    next_label_x0 = nb.bbox[0]
                    break

            if lb.underline_bbox is not None:
                ul = lb.underline_bbox
                line_height = self._estimate_line_height(lb.bbox, text_spans, ul[1])
                rect = (
                    self._round(max(lb.bbox[2] + 2.0, ul[0])),
                    self._round(ul[1] - line_height),
                    self._round(ul[2]),
                    self._round(ul[3]),
                )
            elif lb.table_cell_bbox is not None:
                rect = self._calc_table_cell_rect(lb, tables, text_lines)
            elif lb.dotleader_end_x is not None:
                rect = (
                    self._round(lb.bbox[2] + 2.0),
                    self._round(lb.bbox[1]),
                    self._round(lb.dotleader_end_x),
                    self._round(lb.bbox[3]),
                )
            else:
                rect = self._find_right_blank(lb, text_spans, v_lines, page_rect, next_label_x0)

            if rect is None:
                rect = self._find_below_blank(lb, text_lines, h_lines, page_rect)
            if rect is None:
                continue

            rect_w = rect[2] - rect[0]
            rect_h = rect[3] - rect[1]
            if rect_w < self.MIN_FIELD_WIDTH or rect_h < self.MIN_FIELD_HEIGHT:
                continue
            if lb.table_cell_bbox is not None and rect[2] < lb.bbox[0]:
                continue

            fields.append(
                {
                    "label": lb.text,
                    "label_bbox": lb.bbox,
                    "fill_rect": rect,
                    "field_type": self._infer_field_type(lb.text),
                    "source": lb.source,
                    "confidence": self._round(lb.confidence, 3),
                    "page_num": lb.page_num,
                    "options": None,
                }
            )

        fields = self._resolve_rect_conflicts(fields)
        return fields

    def _resolve_rect_conflicts(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(fields) <= 1:
            return fields

        rows: List[List[int]] = []
        used = [False] * len(fields)
        for i in range(len(fields)):
            if used[i]:
                continue
            row = [i]
            used[i] = True
            iy = (fields[i]["fill_rect"][1] + fields[i]["fill_rect"][3]) / 2.0
            for j in range(i + 1, len(fields)):
                if used[j]:
                    continue
                jy = (fields[j]["fill_rect"][1] + fields[j]["fill_rect"][3]) / 2.0
                if abs(iy - jy) < 8.0:
                    row.append(j)
                    used[j] = True
            rows.append(row)

        for row in rows:
            row.sort(key=lambda idx: fields[idx]["label_bbox"][0])
            for k in range(len(row) - 1):
                curr_idx = row[k]
                next_idx = row[k + 1]
                curr_rect = list(fields[curr_idx]["fill_rect"])
                next_label_x0 = float(fields[next_idx]["label_bbox"][0])

                own_label_x0 = float(fields[curr_idx]["label_bbox"][0])
                if next_label_x0 > own_label_x0 + 1.0 and curr_rect[2] > next_label_x0 - 2.0:
                    curr_rect[2] = next_label_x0 - 2.0
                if curr_rect[2] - curr_rect[0] < self.MIN_FIELD_WIDTH:
                    fields[curr_idx]["_discard"] = True
                else:
                    fields[curr_idx]["fill_rect"] = tuple(self._round(v) for v in curr_rect)

        for i in range(len(fields)):
            if fields[i].get("_discard"):
                continue
            for j in range(i + 1, len(fields)):
                if fields[j].get("_discard"):
                    continue
                overlap = self._overlap_ratio(fields[i]["fill_rect"], fields[j]["fill_rect"])
                if overlap <= 0.05:
                    continue
                if float(fields[i].get("confidence", 0.0)) >= float(fields[j].get("confidence", 0.0)):
                    fields[j]["_discard"] = True
                else:
                    fields[i]["_discard"] = True
                    break

        return [f for f in fields if not f.get("_discard")]

    # -------------------- v2: Phase 5 checkbox 独立通道 --------------------

    def _detect_checkboxes(
        self,
        page: fitz.Page,
        page_num: int,
        text_spans: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        fields = self.engine3_detect_checkboxes(page, page_num, text_spans, text_lines, drawing_data)
        normalized: List[Dict[str, Any]] = []
        for f in fields:
            item = dict(f)
            item["source"] = "checkbox"
            normalized.append(item)
        return normalized

    # -------------------- v2: Phase 6 后处理 --------------------

    def _truncate_to_page(self, fields: List[Dict[str, Any]], page_rect: RectTuple) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for f in fields:
            r = list(f["fill_rect"])
            r[0] = max(r[0], page_rect[0] + 1.0)
            r[1] = max(r[1], page_rect[1] + 1.0)
            r[2] = min(r[2], page_rect[2] - 1.0)
            r[3] = min(r[3], page_rect[3] - 1.0)
            if r[2] - r[0] >= self.MIN_FIELD_WIDTH and r[3] - r[1] >= self.MIN_FIELD_HEIGHT:
                item = dict(f)
                item["fill_rect"] = tuple(self._round(v) for v in r)
                result.append(item)
        return result

    def _final_dedup(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        for f in fields:
            is_dup = False
            for existing in list(kept):
                overlap = self._overlap_ratio(f["fill_rect"], existing["fill_rect"])
                if overlap <= 0.05:
                    continue
                if existing.get("field_type") == "checkbox":
                    is_dup = True
                    break
                if f.get("field_type") == "checkbox":
                    kept.remove(existing)
                    continue
                if float(existing.get("confidence", 0.0)) >= float(f.get("confidence", 0.0)):
                    is_dup = True
                    break
                kept.remove(existing)
            if not is_dup:
                kept.append(f)
        return kept

    def _final_sort(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(fields, key=lambda f: (f["fill_rect"][1], f["fill_rect"][0]))

    def _postprocess(
        self,
        text_fields: List[Dict[str, Any]],
        checkbox_fields: List[Dict[str, Any]],
        page_rect: RectTuple,
    ) -> List[Dict[str, Any]]:
        all_fields = text_fields + checkbox_fields
        all_fields = self._truncate_to_page(all_fields, page_rect)
        all_fields = self._final_dedup(all_fields)
        all_fields = self._final_sort(all_fields)
        for idx, field in enumerate(all_fields, start=1):
            field["field_id"] = f"p{field['page_num']}_f{idx:03d}"
        return all_fields

    # -------------------- v2: 整合入口 --------------------

    def detect_page_v2(self, page: fitz.Page, page_num: int, pdf_path: str) -> Dict[str, Any]:
        text_spans = self.extract_text_spans(page, page_num)
        text_lines = self._extract_text_lines(page, page_num)
        drawing_data = self.extract_drawings(page, page_num)
        tables = self._build_table_grids(drawing_data, page_num)
        page_rect = self._rect_tuple(page.rect)

        # Phase 1.5：续行合并（Union-Find pairwise，含矢量边界检查）
        merged_lines, _ = self._merge_continuation_lines(text_lines, drawing_data=drawing_data)

        all_labels: List[LabelCandidate] = []
        all_labels.extend(
            self._collect_underline_labels(
                text_lines=merged_lines,
                text_spans=text_spans,
                drawing_data=drawing_data,
                tables=tables,
                page_num=page_num,
            )
        )
        all_labels.extend(self._collect_colon_labels(text_spans=text_spans, text_lines=merged_lines, page_num=page_num))
        all_labels.extend(self._collect_enum_labels(text_lines=merged_lines, tables=tables, page_num=page_num))
        all_labels.extend(self._collect_table_labels(text_lines=merged_lines, tables=tables, page_num=page_num))

        underline_count = sum(1 for lb in all_labels if lb.source == "underline")
        is_toc = self._is_toc_page(merged_lines, page_width=self._bbox_width(page_rect))
        if underline_count <= 2 and not is_toc:
            all_labels.extend(
                self._collect_dotleader_labels(
                    pdf_path=pdf_path,
                    page_num=page_num,
                    page_rect=page_rect,
                    existing_labels=all_labels,
                    text_lines=merged_lines,
                )
            )

        unique_labels = self._dedup_labels(all_labels)
        text_fields = self._assign_fill_rects(
            labels=unique_labels,
            drawing_data=drawing_data,
            tables=tables,
            text_lines=merged_lines,
            text_spans=text_spans,
            page_rect=page_rect,
        )
        checkbox_fields = self._detect_checkboxes(
            page=page,
            page_num=page_num,
            text_spans=text_spans,
            text_lines=merged_lines,
            drawing_data=drawing_data,
        )
        all_fields = self._postprocess(text_fields, checkbox_fields, page_rect)
        return {
            "page_num": page_num,
            "page_size": page_rect,
            "text_spans": text_spans,
            "text_lines": merged_lines,
            "table_structures": tables,
            "detected_fields": all_fields,
        }

    # -------------------- 整合入口 --------------------

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
