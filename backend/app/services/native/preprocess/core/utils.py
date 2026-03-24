from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Sequence, Tuple

import fitz

from app.services.native.preprocess.core.types import RectTuple


class UtilityMixin:
    """通用常量与基础工具方法。"""
    # 线段/几何阈值
    LINE_THICKNESS_MAX = 2.0
    MIN_LINE_LEN = 8.0
    COORD_MERGE_TOL = 2.0
    ROW_GROUP_TOL = 10.0
    MIN_FIELD_WIDTH = 18.0
    MIN_FIELD_HEIGHT = 6.0

    # 规则阈值
    MAX_LABEL_LEN = 250
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
            UtilityMixin._round(rect.x0),
            UtilityMixin._round(rect.y0),
            UtilityMixin._round(rect.x1),
            UtilityMixin._round(rect.y1),
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
        acx, acy = UtilityMixin._bbox_center(a)
        bcx, bcy = UtilityMixin._bbox_center(b)
        return math.hypot(acx - bcx, acy - bcy)

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

