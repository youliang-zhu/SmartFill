"""Preprocess 核心模块 — 类型定义、工具方法、提取逻辑、ODL fallback、入口编排。"""

from app.services.native.preprocess.core.types import LabelCandidate, RectTuple
from app.services.native.preprocess.core.utils import UtilityMixin
from app.services.native.preprocess.core.extraction import ExtractionMixin
from app.services.native.preprocess.core.label_first import LabelFirstMixin
from app.services.native.preprocess.core.odl_fallback import _load_odl_fallback_lines

__all__ = [
    "LabelCandidate",
    "RectTuple",
    "UtilityMixin",
    "ExtractionMixin",
    "LabelFirstMixin",
    "_load_odl_fallback_lines",
]
