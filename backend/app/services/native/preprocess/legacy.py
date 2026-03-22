from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import fitz

from app.services.native.preprocess.types import RectTuple


class LegacyEnginesMixin:
    """旧版 4 引擎 + 几何修正流水线（兼容保留）。"""
    def _is_decorative_rect(self, rect_bbox: RectTuple, draw: Dict[str, Any], page: fitz.Page) -> bool:
        fill = draw.get("fill")
        if self._color_is_black_or_white(fill):
            return False
        area = self._bbox_width(rect_bbox) * self._bbox_height(rect_bbox)
        page_area = max(1.0, float(page.rect.width * page.rect.height))
        return area >= page_area * self.DECORATIVE_AREA_RATIO

    def _dedup_rect_candidates(self, rects: List[RectTuple]) -> List[RectTuple]:
        out: List[RectTuple] = []
        for r in sorted(rects, key=lambda x: (x[1], x[0], x[2], x[3])):
            if any(self._overlap_ratio(r, e) > 0.9 for e in out):
                continue
            out.append(r)
        return out

    def _find_label_for_rect(
        self,
        rect: RectTuple,
        text_lines: List[Dict[str, Any]],
        all_rects: List[RectTuple],
    ) -> tuple[str | None, RectTuple | None, str]:
        rx0, ry0, rx1, ry1 = rect
        ry_mid = (ry0 + ry1) / 2.0
        candidates: List[Tuple[float, Dict[str, Any], str]] = []

        for ln in text_lines:
            text = self._normalize_text(ln.get("text", ""))
            if not text or self._is_checkbox_glyph(text):
                continue
            if self._is_instructional_text(text):
                continue
            if len(text) > 200:
                continue

            lb = ln["bbox"]
            lx0, ly0, lx1, ly1 = lb
            ly_mid = (ly0 + ly1) / 2.0

            # 如果这个 label 明显更靠近另一个矩形，则跳过（避免一对多误配）
            my_dist = self._rect_distance(lb, rect)
            other_best = min((self._rect_distance(lb, r) for r in all_rects if r != rect), default=my_dist)
            if my_dist > other_best + 6.0:
                continue

            # 策略 1：矩形内部左上角文字
            if lx0 >= rx0 - 2 and lx1 <= rx1 + 2 and ly0 >= ry0 - 2 and ly1 <= ry0 + (ry1 - ry0) * 0.5:
                candidates.append((0.0, ln, "inside_top"))
                continue

            # 策略 2：左侧文字
            if lx1 <= rx0 + 5 and abs(ly_mid - ry_mid) <= (ry1 - ry0) / 2 + 5:
                dist = rx0 - lx1
                if 0 <= dist <= 200:
                    candidates.append((10.0 + dist, ln, "left"))

            # 策略 3：上方文字
            if ly1 <= ry0 + 2:
                overlap_x = max(0.0, min(lx1, rx1) - max(lx0, rx0))
                vdist = ry0 - ly1
                if overlap_x > 10 and 0 <= vdist <= 30:
                    score = 50.0 + vdist * 2.0 - overlap_x * 0.1
                    candidates.append((score, ln, "above"))

        if not candidates:
            return None, None, "none"
        best = sorted(candidates, key=lambda x: x[0])[0]
        return best[1]["text"], best[1]["bbox"], best[2]

    def _estimate_line_height(self, label_bbox: RectTuple | None, text_spans: List[Dict[str, Any]], y_hint: float) -> float:
        candidates = []
        for sp in text_spans:
            sb = sp["bbox"]
            fs = self._safe_float(sp.get("font_size"), 0.0)
            if fs <= 0:
                continue
            if label_bbox is not None and self._overlap_ratio(sb, label_bbox) > 0.2:
                candidates.append(fs * 1.3)
                continue
            cy = self._bbox_center(sb)[1]
            if abs(cy - y_hint) <= 18:
                candidates.append(fs * 1.3)
        if not candidates:
            return self.LINE_HEIGHT_DEFAULT
        return max(8.0, min(22.0, sum(candidates) / len(candidates)))

    def _find_label_for_underline(
        self,
        underline: Dict[str, float],
        text_lines: List[Dict[str, Any]],
    ) -> tuple[str | None, RectTuple | None, str]:
        ux0, ux1, uy = underline["x0"], underline["x1"], underline["y"]
        candidates: List[Tuple[float, Dict[str, Any], str]] = []

        for ln in text_lines:
            text = self._normalize_text(ln.get("text", ""))
            if not text or self._is_checkbox_glyph(text):
                continue
            if self._is_instructional_text(text):
                continue
            if len(text) > 200:
                continue

            lb = ln["bbox"]
            ly_mid = (lb[1] + lb[3]) / 2.0

            # 左侧同行
            if lb[2] <= ux0 + 5 and abs(ly_mid - uy) <= 10:
                dist = max(0.0, ux0 - lb[2])
                if dist <= 200:
                    if re.match(r"^(YES|NO|Yes|No)$", text.strip()):
                        dist += self.YES_NO_LABEL_PENALTY
                    candidates.append((dist, ln, "left_inline"))

            # 上方
            if lb[3] <= uy + 2:
                overlap_x = max(0.0, min(lb[2], ux1) - max(lb[0], ux0))
                vdist = uy - lb[3]
                if overlap_x > 10 and 0 <= vdist <= 20:
                    candidates.append((100.0 + vdist, ln, "above"))

        if not candidates:
            return None, None, "none"
        best = sorted(candidates, key=lambda x: x[0])[0]
        return best[1]["text"], best[1]["bbox"], best[2]

    def _infer_field_type(self, label_text: str | None) -> str:
        if not label_text:
            return "text"
        lower = self._normalize_text(label_text).lower()
        if any(w in lower for w in ["date", "dob", "birth"]):
            return "date"
        if any(w in lower for w in ["signature", "sign here"]):
            return "signature"
        if any(w in lower for w in ["phone", "telephone", "fax", "tel"]):
            return "phone"
        if any(w in lower for w in ["email", "e-mail"]):
            return "email"
        if any(w in lower for w in ["zip", "postal"]):
            return "zip"
        return "text"

    def _line_is_table_border(self, ln: Dict[str, float], tables: List[Dict[str, Any]]) -> bool:
        y = ln["y"]
        x0, x1 = ln["x0"], ln["x1"]
        for table in tables:
            tb = table["bbox"]
            if tb[1] - 2 <= y <= tb[3] + 2 and x0 >= tb[0] - 2 and x1 <= tb[2] + 2:
                for gy in table.get("grid_y", []):
                    if abs(y - gy) <= 1.5:
                        return True
        return False

    def engine1_detect_boxes(
        self,
        page: fitz.Page,
        page_num: int,
        text_spans: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = []

        rects: List[RectTuple] = []
        for d in drawing_data.get("drawings", []):
            for item in d.get("items", []):
                if item.get("op") != "re":
                    continue
                bbox = item.get("rect")
                if not bbox:
                    continue
                w = self._bbox_width(bbox)
                h = self._bbox_height(bbox)
                if w < self.ENGINE1_RECT_MIN_W or h < self.ENGINE1_RECT_MIN_H:
                    continue
                if w <= h * 1.5:
                    continue
                if 6 <= w <= 20 and 6 <= h <= 20 and abs(w - h) <= 2:
                    continue
                if self._is_decorative_rect(bbox, d, page):
                    continue
                rects.append(bbox)

        rects = self._dedup_rect_candidates(rects)
        for rect in rects:
            label_text, label_bbox, _ = self._find_label_for_rect(rect, text_lines, rects)
            if label_text is None and not self._has_text_above_rect(rect, text_spans, max_gap=20.0):
                continue
            fill_rect = (
                self._round(rect[0] + 1.0),
                self._round(rect[1] + 1.0),
                self._round(rect[2] - 1.0),
                self._round(rect[3] - 1.0),
            )
            if self._bbox_width(fill_rect) < self.MIN_FIELD_WIDTH or self._bbox_height(fill_rect) < self.MIN_FIELD_HEIGHT:
                continue
            fields.append(
                {
                    "label": label_text or "text_box",
                    "label_bbox": label_bbox or fill_rect,
                    "fill_rect": fill_rect,
                    "field_type": self._infer_field_type(label_text),
                    "page_num": page_num,
                    "confidence": self._round(0.84 if label_text else 0.62, 3),
                    "options": None,
                    "source": "engine1_box",
                }
            )

        tables = self._build_table_grids(drawing_data, page_num)
        page_height = float(page.rect.height)
        for ln in drawing_data.get("horizontal_lines", []):
            length = ln["x1"] - ln["x0"]
            if length < self.ENGINE1_UNDERLINE_MIN_W:
                continue
            if not (50.0 < ln["y"] < page_height - 40.0):
                continue
            if self._line_is_table_border(ln, tables):
                continue

            label_text, label_bbox, label_source = self._find_label_for_underline(ln, text_lines)
            line_height = self._estimate_line_height(label_bbox, text_spans, ln["y"])
            fill_x0 = ln["x0"]
            if label_source == "left_inline" and label_bbox is not None:
                fill_x0 = max(label_bbox[2] + 2.0, ln["x0"])
            fill_rect = (
                self._round(fill_x0),
                self._round(ln["y"] - line_height),
                self._round(ln["x1"]),
                self._round(ln["y"] + 1.0),
            )
            if self._bbox_width(fill_rect) < self.MIN_FIELD_WIDTH or self._bbox_height(fill_rect) < self.MIN_FIELD_HEIGHT:
                continue

            fields.append(
                {
                    "label": label_text or "underline_field",
                    "label_bbox": label_bbox or fill_rect,
                    "fill_rect": fill_rect,
                    "field_type": self._infer_field_type(label_text),
                    "page_num": page_num,
                    "confidence": self._round(0.74 if label_text else 0.50, 3),
                    "options": None,
                    "source": "engine1_underline",
                }
            )

        return fields

    # -------------------- 引擎 2 --------------------

    def _engine2_has_overlap(
        self,
        rect: RectTuple,
        existing_fields: List[Dict[str, Any]],
        generated_fields: List[Dict[str, Any]],
        ignore_engine1_box: bool = False,
    ) -> bool:
        for f in existing_fields:
            if ignore_engine1_box and f.get("source") == "engine1_box":
                continue
            if self._overlap_ratio(rect, f["fill_rect"]) > 0.5:
                return True
        for f in generated_fields:
            if self._overlap_ratio(rect, f["fill_rect"]) > 0.5:
                return True
        return False

    def _engine2_detect_dot_leaders(
        self,
        sorted_line: List[Dict[str, Any]],
        line_top: float,
        line_bottom: float,
        page_num: int,
        existing_fields: List[Dict[str, Any]],
        generated_fields: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = []
        i = 0
        n = len(sorted_line)
        while i < n:
            if self._char_text(sorted_line[i]) != ".":
                i += 1
                continue

            run_start = i
            prev_x1 = self._safe_float(sorted_line[i].get("x1"))
            i += 1
            while i < n:
                ch = sorted_line[i]
                if self._char_text(ch) != ".":
                    break
                curr_x0 = self._safe_float(ch.get("x0"))
                if curr_x0 - prev_x1 > 2.0:
                    break
                prev_x1 = self._safe_float(ch.get("x1"))
                i += 1
            run_end = i

            dot_count = run_end - run_start
            if dot_count < self.DOT_LEADER_MIN_COUNT:
                continue

            label_chars = sorted_line[:run_start]
            label_chars = [c for c in label_chars if self._char_text(c).strip()]
            if not label_chars:
                continue

            label_text = self._normalize_text("".join(self._char_text(c) for c in label_chars)).rstrip(":")
            if not label_text:
                continue
            if self._is_instructional_text(label_text):
                continue

            label_end_x = self._safe_float(label_chars[-1].get("x1"))
            dot_start_x = self._safe_float(sorted_line[run_start].get("x0"))
            dot_end_x = self._safe_float(sorted_line[run_end - 1].get("x1"))
            fill_rect = (
                self._round(max(label_end_x + 2.0, dot_start_x)),
                self._round(line_top),
                self._round(dot_end_x),
                self._round(line_bottom),
            )
            if self._bbox_width(fill_rect) < self.MIN_FIELD_WIDTH:
                continue
            if self._engine2_has_overlap(
                fill_rect,
                existing_fields,
                generated_fields + fields,
                ignore_engine1_box=True,
            ):
                continue

            label_bbox = (
                self._round(self._safe_float(label_chars[0].get("x0"))),
                self._round(line_top),
                self._round(label_end_x),
                self._round(line_bottom),
            )
            fields.append(
                {
                    "label": label_text,
                    "label_bbox": label_bbox,
                    "fill_rect": fill_rect,
                    "field_type": self._infer_field_type(label_text),
                    "page_num": page_num,
                    "confidence": 0.90,
                    "options": None,
                    "source": "engine2_blank",
                }
            )

        return fields

    def engine2_detect_blanks(
        self,
        pdf_path: str,
        page_num: int,
        page_rect: RectTuple,
        existing_fields: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = []
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            return fields

        with pdfplumber.open(pdf_path) as pdf:
            if page_num < 1 or page_num > len(pdf.pages):
                return fields
            plumber_page = pdf.pages[page_num - 1]
            chars = plumber_page.chars
            if not chars:
                return fields

        sorted_chars = sorted(
            chars,
            key=lambda c: (
                round(self._safe_float(c.get("top")) / 3.0) * 3.0,
                self._safe_float(c.get("x0")),
            ),
        )
        if not sorted_chars:
            return fields

        lines: List[List[Dict[str, Any]]] = []
        current_line = [sorted_chars[0]]
        for ch in sorted_chars[1:]:
            if abs(self._safe_float(ch.get("top")) - self._safe_float(current_line[0].get("top"))) <= 3.0:
                current_line.append(ch)
            else:
                lines.append(current_line)
                current_line = [ch]
        lines.append(current_line)

        min_blank_width = 40.0
        page_width = page_rect[2]

        for line_chars in lines:
            if len(line_chars) < 2:
                continue
            sorted_line = sorted(line_chars, key=lambda c: self._safe_float(c.get("x0")))
            line_top = min(self._safe_float(c.get("top")) for c in sorted_line)
            line_bottom = max(self._safe_float(c.get("bottom")) for c in sorted_line)

            dot_leader_fields = self._engine2_detect_dot_leaders(
                sorted_line=sorted_line,
                line_top=line_top,
                line_bottom=line_bottom,
                page_num=page_num,
                existing_fields=existing_fields,
                generated_fields=fields,
            )
            if dot_leader_fields:
                fields.extend(dot_leader_fields)

            for i in range(len(sorted_line) - 1):
                curr_x1 = self._safe_float(sorted_line[i].get("x1"))
                next_x0 = self._safe_float(sorted_line[i + 1].get("x0"))
                gap = next_x0 - curr_x1
                if gap < min_blank_width:
                    continue

                blank_rect = (
                    self._round(curr_x1 + 1.0),
                    self._round(line_top),
                    self._round(next_x0 - 1.0),
                    self._round(line_bottom),
                )
                if self._bbox_width(blank_rect) < self.MIN_FIELD_WIDTH:
                    continue

                if self._engine2_has_overlap(blank_rect, existing_fields, fields):
                    continue

                left_chars = [c for c in sorted_line if self._safe_float(c.get("x1")) <= curr_x1 + 1.0]
                left_text = self._normalize_text("".join(self._char_text(c) for c in left_chars))
                if not left_text:
                    continue
                if self._is_instructional_text(left_text):
                    continue

                label_bbox = (
                    self._round(self._safe_float(sorted_line[0].get("x0"))),
                    self._round(line_top),
                    self._round(curr_x1),
                    self._round(line_bottom),
                )
                fields.append(
                    {
                        "label": left_text,
                        "label_bbox": label_bbox,
                        "fill_rect": blank_rect,
                        "field_type": self._infer_field_type(left_text),
                        "page_num": page_num,
                        "confidence": 0.55,
                        "options": None,
                        "source": "engine2_blank",
                    }
                )

            last_x1 = self._safe_float(sorted_line[-1].get("x1"))
            right_margin = page_width - 36.0
            trailing_gap = right_margin - last_x1
            if trailing_gap < min_blank_width:
                continue

            line_text = self._normalize_text("".join(self._char_text(c) for c in sorted_line))
            if not (line_text.endswith(":") or line_text.endswith("_")):
                continue
            if self._is_instructional_text(line_text):
                continue

            blank_rect = (
                self._round(last_x1 + 1.0),
                self._round(line_top),
                self._round(right_margin),
                self._round(line_bottom),
            )
            if self._engine2_has_overlap(blank_rect, existing_fields, fields):
                continue

            label_bbox = (
                self._round(self._safe_float(sorted_line[0].get("x0"))),
                self._round(line_top),
                self._round(last_x1),
                self._round(line_bottom),
            )
            fields.append(
                {
                    "label": line_text,
                    "label_bbox": label_bbox,
                    "fill_rect": blank_rect,
                    "field_type": self._infer_field_type(line_text),
                    "page_num": page_num,
                    "confidence": 0.50,
                    "options": None,
                    "source": "engine2_blank",
                }
            )

        return fields

    # -------------------- 引擎 3 --------------------

    def _find_checkbox_group_label(
        self,
        union_bbox: RectTuple,
        text_lines: List[Dict[str, Any]],
    ) -> tuple[str, RectTuple, str]:
        x0, y0, x1, y1 = union_bbox
        y_mid = (y0 + y1) / 2.0
        candidates: List[Tuple[float, Dict[str, Any], str]] = []

        for ln in text_lines:
            text = self._normalize_text(ln.get("text", ""))
            if not text or self._is_checkbox_glyph(text):
                continue
            if self._is_instructional_text(text):
                continue

            lb = ln["bbox"]
            ly = (lb[1] + lb[3]) / 2.0

            if lb[2] <= x0 + 8 and abs(ly - y_mid) <= 14:
                dist_x = max(0.0, x0 - lb[2])
                score = dist_x + abs(ly - y_mid) * 3.0
                if self._is_section_header(text):
                    score += self.SECTION_HEADER_PENALTY
                candidates.append((score, ln, "left_inline"))

            overlap_x = max(0.0, min(lb[2], x1) - max(lb[0], x0))
            if lb[3] <= y0 + 2 and overlap_x >= 18:
                vdist = y0 - lb[3]
                if 0 <= vdist <= 80:
                    score = 100.0 + vdist * 2.0 - overlap_x * 0.05
                    if self._is_section_header(text):
                        score += self.SECTION_HEADER_PENALTY
                    candidates.append((score, ln, "above"))

        if not candidates:
            return "checkbox_group", union_bbox, "fallback"
        best = sorted(candidates, key=lambda x: x[0])[0]
        return best[1]["text"], best[1]["bbox"], best[2]

    def engine3_detect_checkboxes(
        self,
        page: fitz.Page,
        page_num: int,
        text_spans: List[Dict[str, Any]],
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        del page  # 预留

        boxes: List[RectTuple] = list(drawing_data.get("square_boxes", []))
        for span in text_spans:
            if self._is_checkbox_glyph(span.get("text", "")):
                boxes.append(span["bbox"])
        boxes = self._dedup_boxes(boxes)
        if not boxes:
            return []

        groups: List[List[RectTuple]] = []
        for box in sorted(boxes, key=lambda b: self._bbox_center(b)[1]):
            cy = self._bbox_center(box)[1]
            if not groups:
                groups.append([box])
                continue
            last_cy = self._bbox_center(groups[-1][0])[1]
            if abs(cy - last_cy) <= self.ROW_GROUP_TOL:
                groups[-1].append(box)
            else:
                groups.append([box])

        fields: List[Dict[str, Any]] = []
        for grp in groups:
            grp_sorted = sorted(grp, key=lambda b: b[0])
            union = grp_sorted[0]
            for b in grp_sorted[1:]:
                union = self._bbox_union(union, b)

            label, label_bbox, _ = self._find_checkbox_group_label(union, text_lines)

            options: List[str] = []
            checkbox_positions: List[Dict[str, Any]] = []
            for box in grp_sorted:
                bx1 = box[2]
                by_mid = self._bbox_center(box)[1]

                best_option = None
                best_dist = 1e9
                for ln in text_lines:
                    text = self._normalize_text(ln.get("text", ""))
                    if not text or self._is_checkbox_glyph(text):
                        continue
                    lb = ln["bbox"]
                    ly_mid = (lb[1] + lb[3]) / 2.0
                    if lb[0] < bx1 - 2:
                        continue
                    if abs(ly_mid - by_mid) > 10:
                        continue
                    dist = lb[0] - bx1
                    if 0 <= dist <= 100 and dist < best_dist:
                        best_option = text
                        best_dist = dist

                option_text = best_option or ""
                if option_text:
                    options.append(option_text)
                checkbox_positions.append(
                    {
                        "bbox": (
                            self._round(box[0]),
                            self._round(box[1]),
                            self._round(box[2]),
                            self._round(box[3]),
                        ),
                        "option": option_text,
                    }
                )

            options = list(dict.fromkeys(options))
            fields.append(
                {
                    "label": label,
                    "label_bbox": label_bbox,
                    "fill_rect": (
                        self._round(union[0]),
                        self._round(union[1]),
                        self._round(union[2]),
                        self._round(union[3]),
                    ),
                    "field_type": "checkbox",
                    "page_num": page_num,
                    "confidence": self._round(0.78 if options else 0.62, 3),
                    "options": options,
                    "checkbox_positions": checkbox_positions,
                    "source": "engine3_checkbox",
                }
            )

        return fields

    # -------------------- 引擎 4 --------------------

    def _classify_cell(self, cell_bbox: RectTuple, text_lines: List[Dict[str, Any]]) -> tuple[str, str]:
        inside_lines = self._get_cell_text_lines(cell_bbox, text_lines)
        if not inside_lines:
            return ("empty", "")

        combined_text = self._normalize_text(" ".join(ln["text"] for ln in inside_lines))
        if len(combined_text) <= 2:
            return ("empty", combined_text)

        if combined_text.endswith(":") or combined_text.endswith("*"):
            return ("label", combined_text)
        if "§" in combined_text:
            return ("label", combined_text)

        text_bbox = inside_lines[0]["bbox"]
        for ln in inside_lines[1:]:
            text_bbox = self._bbox_union(text_bbox, ln["bbox"])

        text_area = self._bbox_width(text_bbox) * self._bbox_height(text_bbox)
        cell_area = max(1e-6, self._bbox_width(cell_bbox) * self._bbox_height(cell_bbox))
        text_ratio = text_area / cell_area
        blank_ratio = max(0.0, 1.0 - text_ratio)
        if blank_ratio > self.CELL_FILLABLE_BLANK_RATIO:
            return ("fillable", combined_text)
        if text_ratio > self.LABEL_AREA_RATIO:
            text_bottom = text_bbox[3]
            cell_bottom = cell_bbox[3]
            remaining_height = cell_bottom - text_bottom
            cell_height = self._bbox_height(cell_bbox)
            numbered_prompt_count = len(re.findall(r"\b\d+\.", combined_text))
            if (
                numbered_prompt_count >= 2
                and remaining_height > max(self.MIN_FIELD_HEIGHT, cell_height * 0.18)
            ):
                return ("fillable", combined_text)
            if remaining_height > cell_height * 0.4 and remaining_height > self.MIN_FIELD_HEIGHT:
                return ("fillable", combined_text)
            return ("label", combined_text)

        return ("fillable", combined_text)

    def _find_neighbor_cell(self, table: Dict[str, Any], row: int, col: int) -> Dict[str, Any] | None:
        for c in table["cells"]:
            if c["row"] == row and c["col"] == col:
                return c
        return None

    def _find_label_for_cell(
        self,
        cell: Dict[str, Any],
        table: Dict[str, Any],
        text_lines: List[Dict[str, Any]],
    ) -> tuple[str | None, RectTuple | None, str]:
        row, col = cell["row"], cell["col"]
        cell_bbox = cell["bbox"]

        inside_lines = self._get_cell_text_lines(cell_bbox, text_lines)
        if inside_lines:
            combined = self._normalize_text(" ".join(ln["text"] for ln in inside_lines))
            if combined and len(combined) > 2:
                text_bottom = max(ln["bbox"][3] for ln in inside_lines)
                cell_mid_y = (cell_bbox[1] + cell_bbox[3]) / 2.0
                if text_bottom < cell_mid_y:
                    union_bbox = inside_lines[0]["bbox"]
                    for ln in inside_lines[1:]:
                        union_bbox = self._bbox_union(union_bbox, ln["bbox"])
                    return combined, union_bbox, "inside_cell_top"

        left_cell = self._find_neighbor_cell(table, row, col - 1)
        if left_cell:
            cell_type, text = self._classify_cell(left_cell["bbox"], text_lines)
            if cell_type == "label":
                left_lines = self._get_cell_text_lines(left_cell["bbox"], text_lines)
                if left_lines:
                    lb = left_lines[0]["bbox"]
                    for ln in left_lines[1:]:
                        lb = self._bbox_union(lb, ln["bbox"])
                else:
                    lb = left_cell["bbox"]
                return text, lb, "left_cell"

        above_cell = self._find_neighbor_cell(table, row - 1, col)
        if above_cell:
            cell_type, text = self._classify_cell(above_cell["bbox"], text_lines)
            if cell_type == "label":
                above_lines = self._get_cell_text_lines(above_cell["bbox"], text_lines)
                if above_lines:
                    lb = above_lines[0]["bbox"]
                    for ln in above_lines[1:]:
                        lb = self._bbox_union(lb, ln["bbox"])
                else:
                    lb = above_cell["bbox"]
                return text, lb, "above_cell"

        for c in table["cells"]:
            if c["row"] == row and c["col"] < col:
                cell_type, text = self._classify_cell(c["bbox"], text_lines)
                if cell_type == "label":
                    return text, c["bbox"], "row_fallback"

        return None, None, "none"

    def _find_right_underline_for_line(
        self,
        cell_bbox: RectTuple,
        line_bbox: RectTuple,
        drawing_data: Dict[str, Any],
    ) -> Dict[str, float] | None:
        line_mid_y = (line_bbox[1] + line_bbox[3]) / 2.0
        candidates: List[Dict[str, float]] = []
        for ln in drawing_data.get("horizontal_lines", []):
            if ln["y"] < line_bbox[1] - 4.0 or ln["y"] > line_bbox[3] + 8.0:
                continue
            if ln["x1"] <= line_bbox[2] + 2.0:
                continue
            if ln["x0"] >= cell_bbox[2] - 2.0:
                continue
            if ln["x0"] < cell_bbox[0] - 2.0 or ln["x1"] > cell_bbox[2] + 2.0:
                continue
            candidates.append(ln)
        if not candidates:
            return None
        candidates.sort(key=lambda ln: abs(float(ln["y"]) - line_mid_y))
        return candidates[0]

    def _is_prompt_like_label(self, text: str) -> bool:
        t = self._normalize_text(text)
        if not t:
            return False
        if self._is_instructional_text(t):
            return False
        return bool(
            self.ENUM_PREFIX_RE.match(t)
            or re.match(r"^\s*\d{1,3}\s*[\)\.]\s+", t)
            or (":" in t)
        )

    def _find_prompt_horizontal_bounds(
        self,
        label_bbox: RectTuple,
        drawing_data: Dict[str, Any],
        page_rect: RectTuple,
    ) -> tuple[float, float]:
        y_probe = (label_bbox[1] + label_bbox[3]) / 2.0
        v_lines = drawing_data.get("vertical_lines", [])
        left_candidates: List[float] = []
        right_candidates: List[float] = []
        for ln in v_lines:
            y0 = float(ln.get("y0", 0.0))
            y1 = float(ln.get("y1", 0.0))
            if y0 - 2.0 <= y_probe <= y1 + 2.0:
                x = float(ln.get("x", 0.0))
                if x <= label_bbox[0] + 6.0:
                    left_candidates.append(x)
                if x >= label_bbox[2] - 6.0:
                    right_candidates.append(x)

        left = max(left_candidates) if left_candidates else page_rect[0] + 16.0
        right = min(right_candidates) if right_candidates else page_rect[2] - 16.0
        if right <= left + self.MIN_FIELD_WIDTH:
            left = page_rect[0] + 16.0
            right = page_rect[2] - 16.0
        return self._round(left), self._round(right)

    def _extract_prompt_below_blank_fields(
        self,
        page_num: int,
        page_rect: RectTuple,
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any],
        occupied_fields: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not text_lines:
            return []

        lines = sorted(text_lines, key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
        generated: List[Dict[str, Any]] = []

        i = 0
        while i < len(lines):
            ln = lines[i]
            txt = self._normalize_text(ln.get("text", ""))
            if not self._is_prompt_like_label(txt):
                i += 1
                continue

            label_bbox = ln["bbox"]
            label_parts = [txt]
            start_x = label_bbox[0]

            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                gap_y = nxt["bbox"][1] - label_bbox[3]
                if gap_y > 14.0:
                    break
                nxt_txt = self._normalize_text(nxt.get("text", ""))
                if not nxt_txt:
                    j += 1
                    continue
                if self._is_prompt_like_label(nxt_txt):
                    break
                if abs(nxt["bbox"][0] - start_x) > 40.0:
                    break
                label_parts.append(nxt_txt)
                label_bbox = self._bbox_union(label_bbox, nxt["bbox"])
                j += 1

            label_text = self._normalize_text(" ".join(label_parts))
            left_bound, right_bound = self._find_prompt_horizontal_bounds(label_bbox, drawing_data, page_rect)
            fill_x0 = max(page_rect[0] + 2.0, left_bound + 2.0)
            fill_x1 = min(page_rect[2] - 2.0, right_bound - 2.0)
            if fill_x1 - fill_x0 < max(self.MIN_FIELD_WIDTH, self.PROMPT_FALLBACK_MIN_WIDTH):
                i = j
                continue
            chosen_rect: RectTuple | None = None
            is_colon_label = ":" in label_text

            if is_colon_label:
                same_row_next_prompt_x0: float | None = None
                for k in range(i + 1, len(lines)):
                    nxt = lines[k]
                    if abs(nxt["bbox"][1] - label_bbox[1]) > 3.0:
                        if nxt["bbox"][1] > label_bbox[3] + 2.0:
                            break
                        continue
                    if nxt["bbox"][0] <= label_bbox[0] + 2.0:
                        continue
                    nxt_txt = self._normalize_text(nxt.get("text", ""))
                    if self._is_prompt_like_label(nxt_txt):
                        same_row_next_prompt_x0 = float(nxt["bbox"][0])
                        break

                right_cap = fill_x1
                if same_row_next_prompt_x0 is not None:
                    right_cap = min(right_cap, same_row_next_prompt_x0 - 2.0)
                right_rect = (
                    self._round(max(fill_x0, label_bbox[2] + 2.0)),
                    self._round(max(page_rect[1] + 1.0, label_bbox[1])),
                    self._round(right_cap),
                    self._round(min(page_rect[3] - 2.0, label_bbox[3] + 2.0)),
                )
                if (
                    self._bbox_width(right_rect) >= self.MIN_FIELD_WIDTH
                    and self._bbox_height(right_rect) >= self.MIN_FIELD_HEIGHT
                ):
                    chosen_rect = right_rect

            if chosen_rect is None:
                next_text_y = page_rect[3] - 6.0
                for k in range(j, len(lines)):
                    nxt = lines[k]
                    if nxt["bbox"][1] <= label_bbox[3] + 2.0:
                        continue
                    if self._line_overlap_ratio(fill_x0, fill_x1, nxt["bbox"][0], nxt["bbox"][2]) < 0.12:
                        continue
                    next_text_y = nxt["bbox"][1]
                    break

                fill_y0 = label_bbox[3] + 2.0
                fill_y1 = min(next_text_y - 2.0, fill_y0 + self.PROMPT_FALLBACK_MAX_HEIGHT, page_rect[3] - 6.0)
                if fill_y1 - fill_y0 >= max(self.MIN_FIELD_HEIGHT, self.LINE_HEIGHT_DEFAULT * 1.3):
                    below_rect = (
                        self._round(fill_x0),
                        self._round(fill_y0),
                        self._round(fill_x1),
                        self._round(fill_y1),
                    )
                    fill_area = max(1e-6, self._bbox_width(below_rect) * self._bbox_height(below_rect))
                    text_cover_area = 0.0
                    for tl in lines:
                        tb = tl["bbox"]
                        if tb[3] <= below_rect[1] or tb[1] >= below_rect[3]:
                            continue
                        if self._line_overlap_ratio(below_rect[0], below_rect[2], tb[0], tb[2]) < 0.12:
                            continue
                        ix0 = max(below_rect[0], tb[0])
                        iy0 = max(below_rect[1], tb[1])
                        ix1 = min(below_rect[2], tb[2])
                        iy1 = min(below_rect[3], tb[3])
                        if ix1 > ix0 and iy1 > iy0:
                            text_cover_area += (ix1 - ix0) * (iy1 - iy0)
                    if (text_cover_area / fill_area) <= 0.08:
                        chosen_rect = below_rect

            if chosen_rect is None:
                i = j
                continue

            overlaps_existing = any(
                self._overlap_ratio(chosen_rect, f["fill_rect"]) > 0.5
                for f in occupied_fields + generated
            )
            if overlaps_existing:
                i = j
                continue

            generated.append(
                {
                    "label": label_text,
                    "label_bbox": label_bbox,
                    "fill_rect": chosen_rect,
                    "field_type": self._infer_field_type(label_text),
                    "page_num": page_num,
                    "confidence": 0.56,
                    "options": None,
                    "source": "engine4_table_cell",
                }
            )

            i = j

        return generated

    def _extract_subfields_from_enumerated_label_cell(
        self,
        cell: Dict[str, Any],
        cell_bbox: RectTuple,
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any],
        page_num: int,
        occupied_fields: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        inside_lines = self._get_cell_text_lines(cell_bbox, text_lines)
        if not inside_lines:
            return []

        enum_marks: List[Dict[str, Any]] = []
        for idx, ln in enumerate(inside_lines):
            txt = self._normalize_text(ln.get("text", ""))
            m = self.ENUM_PREFIX_RE.match(txt)
            line_label_text = txt
            if not m:
                m2 = self.ENUM_PREFIX_EMBEDDED_RE.search(txt)
                if not m2 or m2.start(1) > 6:
                    continue
                m = m2
                line_label_text = txt[m.start(1):].strip()
            enum_marks.append(
                {
                    "idx": idx,
                    "token": str(m.group(1)).lower(),
                    "line": ln,
                    "line_label_text": line_label_text,
                }
            )
        if not enum_marks:
            return []

        cell_w = max(1.0, self._bbox_width(cell_bbox))
        sub_fields: List[Dict[str, Any]] = []

        for i, mark in enumerate(enum_marks):
            start_idx = int(mark["idx"])
            end_idx = len(inside_lines) - 1
            next_mark: Dict[str, Any] | None = None
            if i + 1 < len(enum_marks):
                next_mark = enum_marks[i + 1]
                end_idx = int(enum_marks[i + 1]["idx"]) - 1

            label_parts = [str(mark["line_label_text"])]
            label_bbox = mark["line"]["bbox"]
            for j in range(start_idx + 1, end_idx + 1):
                seg = self._normalize_text(inside_lines[j].get("text", ""))
                if seg:
                    label_parts.append(seg)
                label_bbox = self._bbox_union(label_bbox, inside_lines[j]["bbox"])

            txt = self._normalize_text(" ".join(label_parts))
            if not txt:
                continue

            right_blank = cell_bbox[2] - label_bbox[2]
            has_colon = ":" in txt
            has_blank = right_blank >= max(self.MIN_FIELD_WIDTH, cell_w * 0.12)
            underline = self._find_right_underline_for_line(cell_bbox, mark["line"]["bbox"], drawing_data)
            pre_below_bottom = cell_bbox[3] - 2.0
            if next_mark is not None:
                pre_below_bottom = min(pre_below_bottom, float(next_mark["line"]["bbox"][1]) - 1.0)
            pre_remaining_h = pre_below_bottom - (label_bbox[3] + 1.0)
            has_below_blank = pre_remaining_h >= max(self.MIN_FIELD_HEIGHT, self.LINE_HEIGHT_DEFAULT * 0.7)
            if not (has_colon or has_blank or underline is not None or has_below_blank):
                continue

            candidate_rects: List[RectTuple] = []
            if underline is not None:
                fill_x0 = max(label_bbox[2] + 2.0, float(underline["x0"]))
                fill_x1 = min(cell_bbox[2] - 2.0, float(underline["x1"]))
                target_h = max(self.MIN_FIELD_HEIGHT, self.LINE_HEIGHT_DEFAULT * 0.75)
                fill_y1 = min(cell_bbox[3] - 1.0, float(underline["y"]) + max(1.0, self.LINE_HEIGHT_DEFAULT * 0.15))
                fill_y0 = max(cell_bbox[1] + 1.0, fill_y1 - target_h)
                if fill_y1 - fill_y0 < self.MIN_FIELD_HEIGHT:
                    fill_y0 = cell_bbox[1] + 1.0
                    fill_y1 = min(cell_bbox[3] - 1.0, fill_y0 + target_h)
                underline_rect = (
                    self._round(fill_x0),
                    self._round(fill_y0),
                    self._round(fill_x1),
                    self._round(fill_y1),
                )
                if (
                    self._bbox_width(underline_rect) >= self.MIN_FIELD_WIDTH
                    and self._bbox_height(underline_rect) >= self.MIN_FIELD_HEIGHT
                ):
                    candidate_rects.append(underline_rect)

            if has_blank:
                fill_x0 = max(label_bbox[2] + 2.0, cell_bbox[0] + 4.0)
                fill_x1 = cell_bbox[2] - 2.0
                fill_y0 = max(cell_bbox[1] + 1.0, label_bbox[1])
                fill_y1 = min(cell_bbox[3] - 1.0, label_bbox[3] + 2.0)
                blank_rect = (
                    self._round(fill_x0),
                    self._round(fill_y0),
                    self._round(fill_x1),
                    self._round(fill_y1),
                )
                if (
                    self._bbox_width(blank_rect) >= self.MIN_FIELD_WIDTH
                    and self._bbox_height(blank_rect) >= self.MIN_FIELD_HEIGHT
                ):
                    candidate_rects.append(blank_rect)

            below_bottom = cell_bbox[3] - 2.0
            if next_mark is not None:
                below_bottom = min(below_bottom, float(next_mark["line"]["bbox"][1]) - 1.0)
            remaining_h = below_bottom - (label_bbox[3] + 1.0)
            has_below_blank = remaining_h >= max(self.MIN_FIELD_HEIGHT, self.LINE_HEIGHT_DEFAULT * 0.7)
            should_add_below = (
                has_below_blank
                and (next_mark is None or (not has_blank and underline is None))
            )
            if should_add_below:
                fill_x0 = cell_bbox[0] + 2.0
                fill_x1 = cell_bbox[2] - 2.0
                fill_y0 = max(cell_bbox[1] + 1.0, label_bbox[3] + 1.0)
                fill_y1 = below_bottom
                below_rect = (
                    self._round(fill_x0),
                    self._round(fill_y0),
                    self._round(fill_x1),
                    self._round(fill_y1),
                )
                if (
                    self._bbox_width(below_rect) >= self.MIN_FIELD_WIDTH
                    and self._bbox_height(below_rect) >= self.MIN_FIELD_HEIGHT
                ):
                    candidate_rects.append(below_rect)

            if not candidate_rects:
                continue
            fill_rect = max(
                candidate_rects,
                key=lambda r: self._bbox_width(r) * self._bbox_height(r),
            )
            overlaps_existing = any(
                self._overlap_ratio(fill_rect, f["fill_rect"]) > 0.5
                for f in occupied_fields + sub_fields
            )
            if overlaps_existing:
                continue

            sub_fields.append(
                {
                    "label": txt,
                    "label_bbox": label_bbox,
                    "fill_rect": fill_rect,
                    "field_type": self._infer_field_type(txt),
                    "page_num": page_num,
                    "confidence": 0.66,
                    "options": None,
                    "source": "engine4_table_cell",
                    "_engine4_row": cell["row"],
                    "_engine4_col_start": cell["col"],
                    "_engine4_col_end": cell["col"],
                    "_engine4_has_label": True,
                }
            )

        return sub_fields

    def _merge_engine4_same_label_cells(
        self,
        table_fields: List[Dict[str, Any]],
        table: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if len(table_fields) < 2:
            for f in table_fields:
                f.pop("_engine4_row", None)
                f.pop("_engine4_col_start", None)
                f.pop("_engine4_col_end", None)
                f.pop("_engine4_has_label", None)
            return table_fields

        grid_x = table.get("grid_x", [])
        hard_v_boundaries = table.get("hard_v_boundaries", [])
        if len(grid_x) >= 2:
            row_width = max(1.0, float(grid_x[-1]) - float(grid_x[0]))
        else:
            row_width = max(self._bbox_width(f["fill_rect"]) for f in table_fields)

        def has_hard_boundary_between(col_end: int, col_start: int) -> bool:
            if not isinstance(hard_v_boundaries, list) or not hard_v_boundaries:
                return True
            left = int(col_end)
            right = int(col_start)
            if right <= left:
                return False
            start_idx = max(0, left + 1)
            end_idx = min(len(hard_v_boundaries) - 1, right)
            if end_idx < start_idx:
                return True
            return any(bool(hard_v_boundaries[idx]) for idx in range(start_idx, end_idx + 1))

        def merge_into(dst: Dict[str, Any], src: Dict[str, Any], allow_label_adopt: bool) -> None:
            dr = dst["fill_rect"]
            sr = src["fill_rect"]
            dst["fill_rect"] = (
                self._round(min(dr[0], sr[0])),
                self._round(min(dr[1], sr[1])),
                self._round(max(dr[2], sr[2])),
                self._round(max(dr[3], sr[3])),
            )
            dst["label_bbox"] = self._bbox_union(
                tuple(dst.get("label_bbox", dr)), tuple(src.get("label_bbox", sr))
            )
            dst["confidence"] = self._round(
                max(float(dst.get("confidence", 0.0)), float(src.get("confidence", 0.0))), 3
            )
            dst["_engine4_col_start"] = min(
                int(dst.get("_engine4_col_start", 10**9)),
                int(src.get("_engine4_col_start", 10**9)),
            )
            dst["_engine4_col_end"] = max(
                int(dst.get("_engine4_col_end", -1)),
                int(src.get("_engine4_col_end", -1)),
            )
            dst_has = bool(dst.get("_engine4_has_label"))
            src_has = bool(src.get("_engine4_has_label"))
            if allow_label_adopt and (not dst_has) and src_has:
                dst["label"] = src.get("label", dst.get("label", ""))
                dst["field_type"] = src.get("field_type", dst.get("field_type", "text"))
            dst["_engine4_has_label"] = dst_has or src_has

        fields_sorted = sorted(
            [
                {
                    **f,
                    "_engine4_col_start": int(f.get("_engine4_col_start", -1)),
                    "_engine4_col_end": int(f.get("_engine4_col_end", -1)),
                }
                for f in table_fields
            ],
            key=lambda f: (int(f.get("_engine4_row", -1)), f["fill_rect"][1], f["fill_rect"][0]),
        )
        merged: List[Dict[str, Any]] = [fields_sorted[0]]
        for f in fields_sorted[1:]:
            last = merged[-1]
            lr = last["fill_rect"]
            fr = f["fill_rect"]
            same_row = int(last.get("_engine4_row", -1)) == int(f.get("_engine4_row", -2))
            same_label = last.get("label") == f.get("label")
            same_label_state = bool(last.get("_engine4_has_label")) == bool(f.get("_engine4_has_label"))
            adjacent = -2.0 <= (fr[0] - lr[2]) < 10.0
            sub_cell_small_enough = (
                self._bbox_width(lr) < row_width * 0.3 and self._bbox_width(fr) < row_width * 0.3
            )
            if (
                same_row
                and same_label
                and same_label_state
                and abs(fr[1] - lr[1]) < 3.0
                and adjacent
                and sub_cell_small_enough
            ):
                merge_into(last, f, allow_label_adopt=False)
                continue

            y_overlap = self._line_overlap_ratio(lr[1], lr[3], fr[1], fr[3])
            left_col_end = int(last.get("_engine4_col_end", -1))
            right_col_start = int(f.get("_engine4_col_start", -1))
            has_semantic_label_conflict = (
                bool(last.get("_engine4_has_label"))
                and bool(f.get("_engine4_has_label"))
                and last.get("label") != f.get("label")
            )
            soft_boundary_regroup = (
                same_row
                and y_overlap > 0.75
                and -2.0 <= (fr[0] - lr[2]) < 12.0
                and left_col_end >= 0
                and right_col_start >= 0
                and right_col_start > left_col_end
                and (not has_hard_boundary_between(left_col_end, right_col_start))
                and (not has_semantic_label_conflict)
            )
            if soft_boundary_regroup:
                merge_into(last, f, allow_label_adopt=True)
                continue
            merged.append(f)

        for f in merged:
            f.pop("_engine4_row", None)
            f.pop("_engine4_col_start", None)
            f.pop("_engine4_col_end", None)
            f.pop("_engine4_has_label", None)
        return merged

    def engine4_synthesize_table_fields(
        self,
        page: fitz.Page,
        page_num: int,
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any],
        existing_fields: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        page_rect = self._rect_tuple(page.rect)
        tables = self._build_table_grids(drawing_data, page_num)
        fields: List[Dict[str, Any]] = []

        for table in tables:
            table_fields: List[Dict[str, Any]] = []
            for cell in table["cells"]:
                cell_bbox = cell["bbox"]
                cell_type, _ = self._classify_cell(cell_bbox, text_lines)
                should_try_subfields = cell_type == "label"
                if not should_try_subfields and cell_type == "fillable":
                    inside_lines = self._get_cell_text_lines(cell_bbox, text_lines)
                    enum_line_hits = 0
                    for ln in inside_lines:
                        txt = self._normalize_text(ln.get("text", ""))
                        if self.ENUM_PREFIX_RE.match(txt):
                            enum_line_hits += 1
                            if enum_line_hits >= 2:
                                break
                    should_try_subfields = enum_line_hits >= 2

                if should_try_subfields:
                    sub_fields = self._extract_subfields_from_enumerated_label_cell(
                        cell=cell,
                        cell_bbox=cell_bbox,
                        text_lines=text_lines,
                        drawing_data=drawing_data,
                        page_num=page_num,
                        occupied_fields=existing_fields + table_fields,
                    )
                    if sub_fields:
                        table_fields.extend(sub_fields)
                        continue

                if cell_type == "label":
                    continue

                base_rect = (
                    self._round(cell_bbox[0] + 2.0),
                    self._round(cell_bbox[1] + 2.0),
                    self._round(cell_bbox[2] - 2.0),
                    self._round(cell_bbox[3] - 2.0),
                )
                if self._bbox_width(base_rect) < self.MIN_FIELD_WIDTH:
                    continue

                overlaps_existing = any(
                    self._overlap_ratio(base_rect, f["fill_rect"]) > 0.5
                    for f in existing_fields
                )
                if overlaps_existing:
                    continue

                label_text, label_bbox, label_kind = self._find_label_for_cell(cell, table, text_lines)
                has_semantic_label = bool(label_text)

                fill_rect = base_rect
                confidence = 0.58
                if label_kind == "inside_cell_top" and label_bbox is not None:
                    label_bottom = label_bbox[3]
                    inside_rect = (
                        self._round(cell_bbox[0] + 2.0),
                        self._round(label_bottom + 2.0),
                        self._round(cell_bbox[2] - 2.0),
                        self._round(cell_bbox[3] - 2.0),
                    )
                    if self._bbox_width(inside_rect) >= self.MIN_FIELD_WIDTH and self._bbox_height(inside_rect) >= self.MIN_FIELD_HEIGHT:
                        fill_rect = inside_rect
                        confidence = 0.84
                elif label_kind in {"left_cell", "above_cell", "row_fallback"}:
                    confidence = 0.72

                if self._bbox_width(fill_rect) < self.MIN_FIELD_WIDTH or self._bbox_height(fill_rect) < self.MIN_FIELD_HEIGHT:
                    continue

                if not label_text:
                    table_id = table.get("table_id", 0)
                    label_text = f"p{page_num}_t{table_id}_r{cell['row']}_c{cell['col']}"
                    label_bbox = cell_bbox
                    confidence = 0.45

                table_fields.append(
                    {
                        "label": label_text,
                        "label_bbox": label_bbox or cell_bbox,
                        "fill_rect": fill_rect,
                        "field_type": self._infer_field_type(label_text),
                        "page_num": page_num,
                        "confidence": self._round(confidence, 3),
                        "options": None,
                        "source": "engine4_table_cell",
                        "_engine4_row": cell["row"],
                        "_engine4_col_start": cell["col"],
                        "_engine4_col_end": cell["col"],
                        "_engine4_has_label": has_semantic_label,
                    }
                )

            fields.extend(self._merge_engine4_same_label_cells(table_fields, table))

        prompt_fallback_fields = self._extract_prompt_below_blank_fields(
            page_num=page_num,
            page_rect=page_rect,
            text_lines=text_lines,
            drawing_data=drawing_data,
            occupied_fields=existing_fields + fields,
        )
        if prompt_fallback_fields:
            fields.extend(prompt_fallback_fields)

        return fields

    # -------------------- 8 步几何修正 --------------------

    def _step1_synthesize(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(fields) < 2:
            return fields
        fields = sorted(fields, key=lambda f: (f["fill_rect"][1], f["fill_rect"][0]))
        merged = [fields[0]]
        for f in fields[1:]:
            last = merged[-1]
            curr_source = str(f.get("source", ""))
            last_source = str(last.get("source", ""))
            if curr_source.startswith("engine4") or last_source.startswith("engine4"):
                merged.append(f)
                continue
            lr = last["fill_rect"]
            fr = f["fill_rect"]
            y_overlap = self._line_overlap_ratio(lr[1], lr[3], fr[1], fr[3])
            x_gap = fr[0] - lr[2]
            if y_overlap > 0.8 and 0 <= x_gap <= 5:
                last["fill_rect"] = self._bbox_union(lr, fr)
                last["confidence"] = max(last.get("confidence", 0.0), f.get("confidence", 0.0))
            else:
                merged.append(f)
        return merged

    def _step2_carve(self, fields: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for f in fields:
            if str(f.get("source", "")) != "engine1_box":
                result.append(f)
                continue
            rect = f["fill_rect"]
            carved = False
            for table in tables:
                tb = table["bbox"]
                if not self._intersects(rect, tb, gap=0.0):
                    continue
                grid_x = table.get("grid_x", [])
                splits = [x for x in grid_x if rect[0] + 5 < x < rect[2] - 5]
                if not splits:
                    continue
                boundaries = [rect[0]] + sorted(splits) + [rect[2]]
                for i in range(len(boundaries) - 1):
                    sub_rect = (boundaries[i], rect[1], boundaries[i + 1], rect[3])
                    if self._bbox_width(sub_rect) < 15:
                        continue
                    sub_field = dict(f)
                    sub_field["fill_rect"] = (
                        self._round(sub_rect[0]),
                        self._round(sub_rect[1]),
                        self._round(sub_rect[2]),
                        self._round(sub_rect[3]),
                    )
                    if i > 0:
                        sub_field["label"] = f"(continued) {f.get('label', '')}".strip()
                        sub_field["confidence"] = self._round(f.get("confidence", 0.0) * 0.9, 3)
                    result.append(sub_field)
                carved = True
                break
            if not carved:
                result.append(f)
        return result

    def _step3_adjust(self, fields: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        all_grid_x: set[float] = set()
        all_grid_y: set[float] = set()
        for table in tables:
            all_grid_x.update(table.get("grid_x", []))
            all_grid_y.update(table.get("grid_y", []))

        if not all_grid_x and not all_grid_y:
            return fields

        def snap(val: float, grid_values: set[float]) -> float:
            best = val
            best_dist = self.SNAP_TOL + 1.0
            for gv in grid_values:
                d = abs(val - gv)
                if d <= self.SNAP_TOL and d < best_dist:
                    best_dist = d
                    best = gv
            return best

        for f in fields:
            if f.get("source") == "engine2_blank":
                continue
            x0, y0, x1, y1 = f["fill_rect"]
            f["fill_rect"] = (
                self._round(snap(x0, all_grid_x)),
                self._round(snap(y0, all_grid_y)),
                self._round(snap(x1, all_grid_x)),
                self._round(snap(y1, all_grid_y)),
            )
        return fields

    def _step4_nudge(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        padding = 2.0
        for f in fields:
            if f.get("source") == "engine2_blank":
                continue
            x0, y0, x1, y1 = f["fill_rect"]
            x0_new = x0 + padding
            y0_new = y0 + padding
            x1_new = x1 - padding
            y1_new = y1 - padding
            if x1_new > x0_new and y1_new > y0_new:
                f["fill_rect"] = (
                    self._round(x0_new),
                    self._round(y0_new),
                    self._round(x1_new),
                    self._round(y1_new),
                )
        return fields

    def _step5_truncate(self, fields: List[Dict[str, Any]], page_rect: RectTuple) -> List[Dict[str, Any]]:
        px0, py0, px1, py1 = page_rect
        result = []
        for f in fields:
            x0, y0, x1, y1 = f["fill_rect"]
            x0 = max(x0, px0)
            y0 = max(y0, py0)
            x1 = min(x1, px1)
            y1 = min(y1, py1)
            if x1 - x0 >= 10 and y1 - y0 >= 6:
                f["fill_rect"] = (
                    self._round(x0),
                    self._round(y0),
                    self._round(x1),
                    self._round(y1),
                )
                result.append(f)
        return result

    def _step6_offset(self, fields: List[Dict[str, Any]], page: fitz.Page) -> List[Dict[str, Any]]:
        ox, oy = float(page.rect.x0), float(page.rect.y0)
        if abs(ox) < 0.01 and abs(oy) < 0.01:
            return fields
        for f in fields:
            x0, y0, x1, y1 = f["fill_rect"]
            f["fill_rect"] = (
                self._round(x0 - ox),
                self._round(y0 - oy),
                self._round(x1 - ox),
                self._round(y1 - oy),
            )
            if f.get("label_bbox"):
                lx0, ly0, lx1, ly1 = f["label_bbox"]
                f["label_bbox"] = (
                    self._round(lx0 - ox),
                    self._round(ly0 - oy),
                    self._round(lx1 - ox),
                    self._round(ly1 - oy),
                )
        return fields

    def _step7_dedup(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sorted_fields = sorted(
            fields,
            key=lambda f: (
                -float(f.get("confidence", 0.0)),
                self.SOURCE_PRIORITY.get(str(f.get("source", "")), 99),
            ),
        )

        result: List[Dict[str, Any]] = []
        for f in sorted_fields:
            if any(self._overlap_ratio(f["fill_rect"], e["fill_rect"]) > 0.7 for e in result):
                continue
            result.append(f)
        return result

    def _step8_block_table_overlap(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        table_fields = [f for f in fields if str(f.get("source", "")) == "engine4_table_cell"]
        if not table_fields:
            return fields

        result: List[Dict[str, Any]] = []
        for f in fields:
            if str(f.get("source", "")) == "engine4_table_cell":
                result.append(f)
                continue
            if str(f.get("field_type", "")) == "checkbox":
                result.append(f)
                continue
            overlaps_table = any(
                self._overlap_ratio(f["fill_rect"], tf["fill_rect"]) > 0.35
                for tf in table_fields
            )
            if overlaps_table:
                continue
            result.append(f)
        return result

    def _step9_sort(self, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(fields, key=lambda f: (f["fill_rect"][1], f["fill_rect"][0]))

    def correct_fields(
        self,
        fields: List[Dict[str, Any]],
        page: fitz.Page,
        page_rect: RectTuple,
        text_lines: List[Dict[str, Any]],
        tables: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        del text_lines  # 当前几何修正未使用文本特征

        checkbox_fields = [dict(f) for f in fields if f.get("field_type") == "checkbox"]
        non_checkbox_fields = [dict(f) for f in fields if f.get("field_type") != "checkbox"]

        # checkbox 跳过 synthesize / carve / adjust / nudge / offset
        non_checkbox_fields = self._step1_synthesize(non_checkbox_fields)
        non_checkbox_fields = self._step2_carve(non_checkbox_fields, tables)
        non_checkbox_fields = self._step3_adjust(non_checkbox_fields, tables)
        non_checkbox_fields = self._step4_nudge(non_checkbox_fields)

        non_checkbox_fields = self._step5_truncate(non_checkbox_fields, page_rect)
        checkbox_fields = self._step5_truncate(checkbox_fields, page_rect)

        non_checkbox_fields = self._step6_offset(non_checkbox_fields, page)

        merged = non_checkbox_fields + checkbox_fields
        merged = self._step7_dedup(merged)
        merged = self._step8_block_table_overlap(merged)
        merged = self._step9_sort(merged)
        return merged

    # -------------------- v2: Phase 2 标签收集 --------------------
