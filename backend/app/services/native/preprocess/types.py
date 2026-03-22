from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


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
