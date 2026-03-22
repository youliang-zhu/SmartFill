"""
Native PDF 程序化字段检测（Phase 1）

实现架构：
- 引擎 1：engine1_detect_boxes（矢量矩形框 + 下划线）
- 引擎 2：engine2_detect_blanks（pdfplumber 空白区间回退）
- 引擎 3：engine3_detect_checkboxes（checkbox 分组）
- 引擎 4：engine4_synthesize_table_fields（表格单元格合成）
- 8 步几何修正：correct_fields
"""
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import fitz


RectTuple = Tuple[float, float, float, float]


@dataclass
class LabelCandidate:
    text: str
    bbox: RectTuple
    source: str
    confidence: float
    page_num: int
    underline_bbox: RectTuple | None = None
    table_cell_bbox: RectTuple | None = None
    dotleader_end_x: float | None = None


class NativeDetector:
    """Native PDF 结构化检测器。"""

    # 线段/几何阈值
    LINE_THICKNESS_MAX = 2.0
    MIN_LINE_LEN = 8.0
    COORD_MERGE_TOL = 2.0
    ROW_GROUP_TOL = 10.0
    MIN_FIELD_WIDTH = 18.0
    MIN_FIELD_HEIGHT = 6.0

    # 规则阈值
    MAX_LABEL_LEN = 160
    MAX_LABEL_WORDS = 28
    ENGINE2_TRIGGER_THRESHOLD = 3
    LABEL_AREA_RATIO = 0.3
    CELL_FILLABLE_BLANK_RATIO = 0.6
    SECTION_HEADER_PENALTY = 200.0
    YES_NO_LABEL_PENALTY = 150.0

    # 引擎阈值
    ENGINE1_RECT_MIN_W = 30.0
    ENGINE1_RECT_MIN_H = 12.0
    ENGINE1_UNDERLINE_MIN_W = 40.0
    DOT_LEADER_MIN_COUNT = 10

    # 通用参数
    LINE_HEIGHT_DEFAULT = 14.0
    DECORATIVE_AREA_RATIO = 0.02
    SNAP_TOL = 3.0
    PROMPT_FALLBACK_MAX_HEIGHT = 320.0
    PROMPT_FALLBACK_MIN_WIDTH = 80.0

    INSTRUCTION_PREFIXES = (
        "note",
        "instructions",
        "estimated reporting burden",
        "privacy act statement",
        "table of contents",
        "page down to access form",
        "certifies as follows",
        "the undersigned",
        "signature of an agent is not acceptable",
    )
    DECORATIVE_LABEL_PATTERNS = (
        r"^page\s+\d+\s+of\s+\d+$",
        r"^omb\s*#?\s*\d+",
        r"^for\s+.{0,30}\s+use\s+only$",
        r"public\s+reporting\s+burden",
    )

    SOURCE_PRIORITY = {
        "engine1_box": 0,
        "engine1_underline": 1,
        "engine3_checkbox": 2,
        "engine4_table_cell": 3,
        "engine2_blank": 4,
    }
    ENUM_PREFIX_RE = re.compile(r"^\s*(?:\(\s*)?([A-Za-z]|\d{1,3})\s*[\)\.:]\s*")
    ENUM_PREFIX_EMBEDDED_RE = re.compile(
        r"(?:^|[\s,;/\-])(?:\(\s*)?([A-Za-z]|\d{1,3})\s*[\)\.:]\s*"
    )

    @staticmethod
    def _round(v: float, ndigits: int = 2) -> float:
        return round(float(v), ndigits)

    @staticmethod
    def _rect_tuple(rect: fitz.Rect) -> RectTuple:
        return (
            NativeDetector._round(rect.x0),
            NativeDetector._round(rect.y0),
            NativeDetector._round(rect.x1),
            NativeDetector._round(rect.y1),
        )

    @staticmethod
    def _bbox_union(a: RectTuple, b: RectTuple) -> RectTuple:
        return (
            min(a[0], b[0]),
            min(a[1], b[1]),
            max(a[2], b[2]),
            max(a[3], b[3]),
        )

    @staticmethod
    def _bbox_center(bbox: RectTuple) -> Tuple[float, float]:
        return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)

    @staticmethod
    def _bbox_width(bbox: RectTuple) -> float:
        return bbox[2] - bbox[0]

    @staticmethod
    def _bbox_height(bbox: RectTuple) -> float:
        return bbox[3] - bbox[1]

    @staticmethod
    def _is_valid_rect(bbox: RectTuple) -> bool:
        return bbox[2] > bbox[0] and bbox[3] > bbox[1]

    @staticmethod
    def _intersects(a: RectTuple, b: RectTuple, gap: float = 0.0) -> bool:
        return not (
            a[2] < b[0] - gap
            or a[0] > b[2] + gap
            or a[3] < b[1] - gap
            or a[1] > b[3] + gap
        )

    @staticmethod
    def _overlap_ratio(a: RectTuple, b: RectTuple) -> float:
        ix0 = max(a[0], b[0])
        iy0 = max(a[1], b[1])
        ix1 = min(a[2], b[2])
        iy1 = min(a[3], b[3])
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        area_a = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
        area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
        return inter / min(area_a, area_b)

    @staticmethod
    def _cluster_values(values: Sequence[float], tol: float) -> List[float]:
        if not values:
            return []
        sorted_vals = sorted(values)
        clusters: List[List[float]] = [[sorted_vals[0]]]
        for v in sorted_vals[1:]:
            if abs(v - clusters[-1][-1]) <= tol:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [sum(c) / len(c) for c in clusters]

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.replace("\n", " ").split()).strip()

    @staticmethod
    def _word_count(text: str) -> int:
        return len([w for w in text.split() if w])

    @staticmethod
    def _slug(text: str, max_len: int = 24) -> str:
        out = []
        for ch in text.lower():
            if ch.isalnum():
                out.append(ch)
            elif out and out[-1] != "_":
                out.append("_")
        slug = "".join(out).strip("_")
        return slug[:max_len] if slug else "field"

    @staticmethod
    def _is_checkbox_glyph(text: str) -> bool:
        if not text:
            return False
        tokens = {"☐", "☑", "☒", "□", "■", "✓", "✔", "", ""}
        if text.strip() in tokens:
            return True
        return any(0xF000 <= ord(ch) <= 0xF0FF for ch in text)

    @classmethod
    def _is_instructional_text(cls, text: str) -> bool:
        t = cls._normalize_text(text).lower()
        if not t:
            return False
        for pattern in cls.DECORATIVE_LABEL_PATTERNS:
            if re.search(pattern, t):
                return True
        if any(t.startswith(prefix) for prefix in cls.INSTRUCTION_PREFIXES):
            return True
        if t.startswith("note:") or t.startswith("note :") or t.startswith("note -"):
            return True
        return "certifies as follows" in t

    @classmethod
    def _is_likely_running_text(cls, text: str) -> bool:
        t = cls._normalize_text(text)
        if not t:
            return False
        return len(t) > cls.MAX_LABEL_LEN or cls._word_count(t) > cls.MAX_LABEL_WORDS

    @classmethod
    def _is_section_header(cls, text: str) -> bool:
        t = cls._normalize_text(text)
        if not t:
            return False
        if len(t) < 3:
            return False
        if not t.isupper():
            return False
        if re.search(r"\d", t):
            return False
        return cls._word_count(t) <= 4

    @staticmethod
    def _line_overlap_ratio(a0: float, a1: float, b0: float, b1: float) -> float:
        i0 = max(a0, b0)
        i1 = min(a1, b1)
        if i1 <= i0:
            return 0.0
        inter = i1 - i0
        base = max(1e-6, min(a1 - a0, b1 - b0))
        return inter / base

    @staticmethod
    def _char_text(ch: Dict[str, Any]) -> str:
        return str(ch.get("text", ""))

    def _is_toc_page(self, text_lines: List[Dict[str, Any]], page_width: float) -> bool:
        del page_width  # TOC 判定使用文本模式，不依赖几何阈值
        for tl in text_lines:
            t = self._normalize_text(tl.get("text", "")).lower()
            if "table of contents" in t:
                return True
        right_number_count = 0
        for tl in text_lines:
            text = self._normalize_text(tl.get("text", ""))
            if len(text) <= 10:
                continue
            if not re.search(r"\d{1,3}\s*$", text):
                continue
            right_number_count += 1
        return right_number_count >= 5

    def _has_text_above_rect(
        self,
        rect: RectTuple,
        text_spans: List[Dict[str, Any]],
        max_gap: float = 20.0,
    ) -> bool:
        rx0, ry0, rx1, _ = rect
        for span in text_spans:
            sb = span.get("bbox")
            if not sb:
                continue
            sx0, sy0, sx1, sy1 = sb
            if sy1 > ry0:
                continue
            if ry0 - sy1 > max_gap:
                continue
            overlap_x = max(0.0, min(rx1, sx1) - max(rx0, sx0))
            if overlap_x > 0.0:
                return True
        return False

    @staticmethod
    def _color_is_black_or_white(color: Any) -> bool:
        if color is None:
            return True
        if not isinstance(color, (tuple, list)) or len(color) < 3:
            return True
        try:
            r, g, b = float(color[0]), float(color[1]), float(color[2])
        except (TypeError, ValueError):
            return True
        black = max(abs(r), abs(g), abs(b)) <= 0.12
        white = min(abs(1.0 - r), abs(1.0 - g), abs(1.0 - b)) <= 0.12
        return black or white

    @staticmethod
    def _rect_distance(a: RectTuple, b: RectTuple) -> float:
        acx, acy = NativeDetector._bbox_center(a)
        bcx, bcy = NativeDetector._bbox_center(b)
        return math.hypot(acx - bcx, acy - bcy)

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def extract_text_spans(self, page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
        spans: List[Dict[str, Any]] = []
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = self._normalize_text(span.get("text", ""))
                    if not text:
                        continue
                    bbox = self._rect_tuple(fitz.Rect(span.get("bbox")))
                    spans.append(
                        {
                            "text": text,
                            "bbox": bbox,
                            "font_name": span.get("font", ""),
                            "font_size": self._round(span.get("size", 0.0)),
                            "page_num": page_num,
                        }
                    )
        return spans

    def _extract_text_lines(self, page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
        lines_out: List[Dict[str, Any]] = []
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_spans = line.get("spans", [])
                if not line_spans:
                    continue
                texts = []
                bbox: RectTuple | None = None
                for span in line_spans:
                    t = self._normalize_text(span.get("text", ""))
                    if not t:
                        continue
                    texts.append(t)
                    sb = self._rect_tuple(fitz.Rect(span.get("bbox")))
                    bbox = sb if bbox is None else self._bbox_union(bbox, sb)
                if not texts or bbox is None:
                    continue
                lines_out.append(
                    {
                        "text": self._normalize_text(" ".join(texts)),
                        "bbox": bbox,
                        "page_num": page_num,
                    }
                )
        return lines_out

    def extract_drawings(self, page: fitz.Page, page_num: int) -> Dict[str, Any]:
        drawings = page.get_drawings()
        drawing_items: List[Dict[str, Any]] = []
        raw_lines_h: List[Dict[str, float]] = []
        raw_lines_v: List[Dict[str, float]] = []
        square_boxes: List[RectTuple] = []

        for d in drawings:
            d_rect = self._rect_tuple(d.get("rect", fitz.Rect(0, 0, 0, 0)))
            normalized_items = []

            for item in d.get("items", []):
                op = item[0]
                if op == "re":
                    rect: fitz.Rect = item[1]
                    bbox = self._rect_tuple(rect)
                    normalized_items.append({"op": "re", "rect": bbox})

                    w = rect.width
                    h = rect.height
                    if h <= self.LINE_THICKNESS_MAX and w >= self.MIN_LINE_LEN:
                        raw_lines_h.append(
                            {"x0": rect.x0, "x1": rect.x1, "y": (rect.y0 + rect.y1) / 2.0}
                        )
                    elif w <= self.LINE_THICKNESS_MAX and h >= self.MIN_LINE_LEN:
                        raw_lines_v.append(
                            {"x": (rect.x0 + rect.x1) / 2.0, "y0": rect.y0, "y1": rect.y1}
                        )

                    if 6.0 <= w <= 20.0 and 6.0 <= h <= 20.0 and abs(w - h) <= 2.0:
                        square_boxes.append(bbox)

                elif op == "l":
                    p1, p2 = item[1], item[2]
                    bbox = (
                        self._round(min(p1.x, p2.x)),
                        self._round(min(p1.y, p2.y)),
                        self._round(max(p1.x, p2.x)),
                        self._round(max(p1.y, p2.y)),
                    )
                    normalized_items.append({"op": "l", "bbox": bbox})

                    if abs(p1.y - p2.y) <= self.LINE_THICKNESS_MAX and abs(p1.x - p2.x) >= self.MIN_LINE_LEN:
                        raw_lines_h.append(
                            {"x0": min(p1.x, p2.x), "x1": max(p1.x, p2.x), "y": (p1.y + p2.y) / 2.0}
                        )
                    elif abs(p1.x - p2.x) <= self.LINE_THICKNESS_MAX and abs(p1.y - p2.y) >= self.MIN_LINE_LEN:
                        raw_lines_v.append(
                            {"x": (p1.x + p2.x) / 2.0, "y0": min(p1.y, p2.y), "y1": max(p1.y, p2.y)}
                        )

            drawing_items.append(
                {
                    "type": d.get("type", ""),
                    "rect": d_rect,
                    "items": normalized_items,
                    "items_count": len(normalized_items),
                    "fill": d.get("fill"),
                    "color": d.get("color"),
                    "width": self._safe_float(d.get("width"), 0.0),
                    "stroke_opacity": d.get("stroke_opacity"),
                    "fill_opacity": d.get("fill_opacity"),
                    "page_num": page_num,
                }
            )

        merged_h = self._merge_horizontal_lines(raw_lines_h)
        merged_v = self._merge_vertical_lines(raw_lines_v)
        dedup_boxes = self._dedup_boxes(square_boxes)

        return {
            "drawings": drawing_items,
            "horizontal_lines": merged_h,
            "vertical_lines": merged_v,
            "square_boxes": dedup_boxes,
        }

    def _merge_horizontal_lines(self, lines: List[Dict[str, float]]) -> List[Dict[str, float]]:
        if not lines:
            return []
        lines = sorted(lines, key=lambda x: (x["y"], x["x0"]))
        merged: List[Dict[str, float]] = []
        for ln in lines:
            if not merged:
                merged.append(dict(ln))
                continue
            last = merged[-1]
            y_close = abs(last["y"] - ln["y"]) <= self.COORD_MERGE_TOL
            x_overlap = ln["x0"] <= last["x1"] + self.COORD_MERGE_TOL
            if y_close and x_overlap:
                last["x0"] = min(last["x0"], ln["x0"])
                last["x1"] = max(last["x1"], ln["x1"])
                last["y"] = (last["y"] + ln["y"]) / 2.0
            else:
                merged.append(dict(ln))
        return merged

    def _merge_vertical_lines(self, lines: List[Dict[str, float]]) -> List[Dict[str, float]]:
        if not lines:
            return []
        lines = sorted(lines, key=lambda x: (x["x"], x["y0"]))
        merged: List[Dict[str, float]] = []
        for ln in lines:
            if not merged:
                merged.append(dict(ln))
                continue
            last = merged[-1]
            x_close = abs(last["x"] - ln["x"]) <= self.COORD_MERGE_TOL
            y_overlap = ln["y0"] <= last["y1"] + self.COORD_MERGE_TOL
            if x_close and y_overlap:
                last["y0"] = min(last["y0"], ln["y0"])
                last["y1"] = max(last["y1"], ln["y1"])
                last["x"] = (last["x"] + ln["x"]) / 2.0
            else:
                merged.append(dict(ln))
        return merged

    def _dedup_boxes(self, boxes: List[RectTuple]) -> List[RectTuple]:
        dedup: List[RectTuple] = []
        for b in boxes:
            cx, cy = self._bbox_center(b)
            exists = False
            for e in dedup:
                ex, ey = self._bbox_center(e)
                if abs(cx - ex) <= 2.0 and abs(cy - ey) <= 2.0:
                    exists = True
                    break
            if not exists:
                dedup.append(b)
        return dedup

    # -------------------- 引擎 1 --------------------

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

    def _build_table_grids(self, drawing_data: Dict[str, Any], page_num: int) -> List[Dict[str, Any]]:
        h_lines = drawing_data.get("horizontal_lines", [])
        v_lines = drawing_data.get("vertical_lines", [])
        if len(h_lines) < 2 or len(v_lines) < 2:
            return []

        line_nodes: List[Dict[str, Any]] = []
        for h in h_lines:
            bbox = (h["x0"], h["y"] - 0.5, h["x1"], h["y"] + 0.5)
            line_nodes.append({"kind": "h", "bbox": bbox, "line": h})
        for v in v_lines:
            bbox = (v["x"] - 0.5, v["y0"], v["x"] + 0.5, v["y1"])
            line_nodes.append({"kind": "v", "bbox": bbox, "line": v})

        parent = list(range(len(line_nodes)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(line_nodes)):
            for j in range(i + 1, len(line_nodes)):
                if self._intersects(line_nodes[i]["bbox"], line_nodes[j]["bbox"], gap=2.0):
                    union(i, j)

        groups: Dict[int, List[Dict[str, Any]]] = {}
        for i, node in enumerate(line_nodes):
            groups.setdefault(find(i), []).append(node)

        tables: List[Dict[str, Any]] = []
        for group in groups.values():
            gh = [n for n in group if n["kind"] == "h"]
            gv = [n for n in group if n["kind"] == "v"]
            if len(gh) < 2 or len(gv) < 2:
                continue

            # Aggressive mode: only use original vector lines as table boundaries.
            # Do not synthesize extra split lines from segment endpoints.
            xs = [float(v["line"]["x"]) for v in gv]
            ys = [float(h["line"]["y"]) for h in gh]

            x_grid = self._cluster_values(xs, tol=self.COORD_MERGE_TOL)
            y_grid = self._cluster_values(ys, tol=self.COORD_MERGE_TOL)
            if len(x_grid) < 2 or len(y_grid) < 2:
                continue

            bbox = (
                self._round(min(x_grid)),
                self._round(min(y_grid)),
                self._round(max(x_grid)),
                self._round(max(y_grid)),
            )
            if self._bbox_width(bbox) < 40 or self._bbox_height(bbox) < 20:
                continue

            table_h = max(1.0, self._bbox_height(bbox))
            hard_v_boundaries: List[bool] = []
            for x in x_grid:
                segments: List[Tuple[float, float]] = []
                for v in gv:
                    vx = float(v["line"]["x"])
                    if abs(vx - x) > max(1.5, self.COORD_MERGE_TOL):
                        continue
                    y0 = max(float(v["line"]["y0"]), bbox[1])
                    y1 = min(float(v["line"]["y1"]), bbox[3])
                    if y1 > y0:
                        segments.append((y0, y1))
                if not segments:
                    hard_v_boundaries.append(False)
                    continue
                segments.sort(key=lambda s: s[0])
                merged_len = 0.0
                cur0, cur1 = segments[0]
                for s0, s1 in segments[1:]:
                    if s0 <= cur1 + 0.8:
                        cur1 = max(cur1, s1)
                    else:
                        merged_len += cur1 - cur0
                        cur0, cur1 = s0, s1
                merged_len += cur1 - cur0
                coverage = merged_len / table_h
                hard_v_boundaries.append(coverage >= 0.68)
            if hard_v_boundaries:
                hard_v_boundaries[0] = True
                hard_v_boundaries[-1] = True

            cells = []
            for r in range(len(y_grid) - 1):
                for c in range(len(x_grid) - 1):
                    cb = (
                        self._round(x_grid[c]),
                        self._round(y_grid[r]),
                        self._round(x_grid[c + 1]),
                        self._round(y_grid[r + 1]),
                    )
                    if self._bbox_width(cb) < 3 or self._bbox_height(cb) < 3:
                        continue
                    cells.append({"row": r, "col": c, "bbox": cb})

            if len(cells) < 2:
                continue

            tables.append(
                {
                    "page_num": page_num,
                    "bbox": bbox,
                    "row_count": max(0, len(y_grid) - 1),
                    "col_count": max(0, len(x_grid) - 1),
                    "grid_x": [self._round(x) for x in x_grid],
                    "grid_y": [self._round(y) for y in y_grid],
                    "hard_v_boundaries": hard_v_boundaries,
                    "orig_h_lines": [
                        {
                            "x0": self._round(float(h["line"]["x0"])),
                            "x1": self._round(float(h["line"]["x1"])),
                            "y": self._round(float(h["line"]["y"])),
                        }
                        for h in gh
                    ],
                    "orig_v_lines": [
                        {
                            "x": self._round(float(v["line"]["x"])),
                            "y0": self._round(float(v["line"]["y0"])),
                            "y1": self._round(float(v["line"]["y1"])),
                        }
                        for v in gv
                    ],
                    "cells": cells,
                }
            )

        tables.sort(key=lambda t: (t["bbox"][1], t["bbox"][0]))
        for idx, table in enumerate(tables, start=1):
            table["table_id"] = idx
        return tables

    def _get_cell_text_lines(self, cell_bbox: RectTuple, text_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        lines = []
        for ln in text_lines:
            if self._intersects(cell_bbox, ln["bbox"], gap=-1.0):
                lines.append(ln)
        lines.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
        return lines

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
        for ln in h_lines:
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
                if not text:
                    continue
                if self._is_instructional_text(text):
                    continue
                if self._is_likely_running_text(text):
                    continue
                labels.append(
                    LabelCandidate(
                        text=text,
                        bbox=tuple(best_label["bbox"]),
                        source="underline",
                        confidence=0.74,
                        page_num=page_num,
                        underline_bbox=(x0, y - 1.0, x1, y + 1.0),
                    )
                )
                continue

            above_label = self._find_text_above(text_lines, x0, x1, y, max_gap=20.0)
            label_text = self._normalize_text(str(above_label.get("text", ""))) if above_label else "underline_field"
            label_bbox = tuple(above_label["bbox"]) if above_label else (x0, y - 12.0, x0 + 40.0, y)
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

        # 第一轮：全局行首枚举
        for tl in text_lines:
            text = self._normalize_text(str(tl.get("text", "")))
            if not text:
                continue
            if not self.ENUM_PREFIX_RE.match(text):
                continue
            if self._is_instructional_text(text):
                continue
            content_after_prefix = self.ENUM_PREFIX_RE.sub("", text).strip()
            if len(content_after_prefix) < 2:
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
                    if len(combined_text) > self.MAX_LABEL_LEN:
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
        label_x1 = lb.bbox[2]
        padding = 2.0
        right_space = cell_x1 - label_x1

        if right_space > self.MIN_FIELD_WIDTH:
            return (
                self._round(label_x1 + padding),
                self._round(cell_y0 + padding),
                self._round(cell_x1 - padding),
                self._round(cell_y1 - padding),
            )

        right_cell = self._find_right_empty_cell(cell, tables, text_lines)
        if right_cell is not None:
            return (
                self._round(right_cell[0] + padding),
                self._round(right_cell[1] + padding),
                self._round(right_cell[2] - padding),
                self._round(right_cell[3] - padding),
            )

        below_space = self._find_below_empty_in_table(cell, tables, text_lines)
        if below_space is not None:
            return below_space

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

                if curr_rect[2] > next_label_x0 - 2.0:
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

        all_labels: List[LabelCandidate] = []
        all_labels.extend(
            self._collect_underline_labels(
                text_lines=text_lines,
                text_spans=text_spans,
                drawing_data=drawing_data,
                tables=tables,
                page_num=page_num,
            )
        )
        all_labels.extend(self._collect_colon_labels(text_spans=text_spans, text_lines=text_lines, page_num=page_num))
        all_labels.extend(self._collect_enum_labels(text_lines=text_lines, tables=tables, page_num=page_num))
        all_labels.extend(self._collect_table_labels(text_lines=text_lines, tables=tables, page_num=page_num))

        underline_count = sum(1 for lb in all_labels if lb.source == "underline")
        is_toc = self._is_toc_page(text_lines, page_width=self._bbox_width(page_rect))
        if underline_count <= 2 and not is_toc:
            all_labels.extend(
                self._collect_dotleader_labels(
                    pdf_path=pdf_path,
                    page_num=page_num,
                    page_rect=page_rect,
                    existing_labels=all_labels,
                    text_lines=text_lines,
                )
            )

        unique_labels = self._dedup_labels(all_labels)
        text_fields = self._assign_fill_rects(
            labels=unique_labels,
            drawing_data=drawing_data,
            tables=tables,
            text_lines=text_lines,
            text_spans=text_spans,
            page_rect=page_rect,
        )
        checkbox_fields = self._detect_checkboxes(
            page=page,
            page_num=page_num,
            text_spans=text_spans,
            text_lines=text_lines,
            drawing_data=drawing_data,
        )
        all_fields = self._postprocess(text_fields, checkbox_fields, page_rect)
        return {
            "page_num": page_num,
            "page_size": page_rect,
            "text_spans": text_spans,
            "text_lines": text_lines,
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


_native_detector = NativeDetector()


def get_native_detector() -> NativeDetector:
    return _native_detector


def _main() -> None:
    parser = argparse.ArgumentParser(description="Native PDF 字段检测（Phase 1）")
    parser.add_argument("--input", required=True, help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出 JSON 路径（可选）")
    parser.add_argument("--pretty", action="store_true", help="控制台输出缩进 JSON")
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {pdf_path}")

    detector = get_native_detector()
    result = detector.detect_all(pdf_path)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已输出检测结果: {out}")

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = {
            "pdf_path": result["pdf_path"],
            "page_count": result["page_count"],
            "detected_field_count": result["detected_field_count"],
            "fields_per_page": [len(p["detected_fields"]) for p in result["pages"]],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
