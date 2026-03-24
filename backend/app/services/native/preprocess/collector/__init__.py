"""Phase 2 字段收集器。"""

from app.services.native.preprocess.collector.collect_checkboxes import collect_checkboxes
from app.services.native.preprocess.collector.collect_text_fields import collect_text_fields

__all__ = ["collect_checkboxes", "collect_text_fields"]
