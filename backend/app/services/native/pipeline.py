"""
Native PDF 业务流水线（v2 预留）
"""
import json
from pathlib import Path
from typing import Dict, List, Tuple

from app.models.schemas import FieldInfo, FillResult
from app.services.native.detector import get_native_detector


class NativePipeline:
    """native 类型流水线（Phase 1: 程序化字段检测）。"""

    _FILL_NOT_READY_MESSAGE = "native 填写流程将在后续阶段实现"

    def __init__(self):
        self.detector = get_native_detector()

    @staticmethod
    def _build_field_name(field: Dict[str, object], page_num: int, idx: int) -> str:
        field_type = str(field.get("field_type", "text"))
        label = str(field.get("label", "")).strip().lower()
        slug_chars: List[str] = []
        for ch in label:
            if ch.isalnum():
                slug_chars.append(ch)
            elif slug_chars and slug_chars[-1] != "_":
                slug_chars.append("_")
        slug = "".join(slug_chars).strip("_")[:24] or "field"
        return f"p{page_num}_{field_type}_{idx:03d}_{slug}"

    def extract_fields(self, pdf_path: Path) -> Tuple[List[str], List[FieldInfo]]:
        result = self.detector.detect_all(pdf_path)

        field_names: List[str] = []
        field_details: List[FieldInfo] = []

        idx = 1
        for page in result.get("pages", []):
            page_num = int(page.get("page_num", 0))
            for detected in page.get("detected_fields", []):
                field_name = self._build_field_name(detected, page_num, idx)
                field_names.append(field_name)

                # Phase 1 先复用 default_value 字段携带调试元信息，后续可迁移到独立 metadata 字段
                debug_payload = {
                    "label": detected.get("label"),
                    "page_num": detected.get("page_num"),
                    "fill_rect": detected.get("fill_rect"),
                    "confidence": detected.get("confidence"),
                    "options": detected.get("options"),
                }
                field_details.append(
                    FieldInfo(
                        name=field_name,
                        field_type=str(detected.get("field_type", "text")),
                        default_value=json.dumps(debug_payload, ensure_ascii=False),
                    )
                )
                idx += 1

        return field_names, field_details

    async def fill_with_ai(
        self,
        pdf_path: Path,
        user_info: str,
        output_path: Path,
    ) -> FillResult:
        raise NotImplementedError(self._FILL_NOT_READY_MESSAGE)

    def fill_by_fields(
        self,
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path,
    ) -> FillResult:
        raise NotImplementedError(self._FILL_NOT_READY_MESSAGE)


_native_pipeline = NativePipeline()


def get_native_pipeline() -> NativePipeline:
    """获取 native 流水线单例。"""
    return _native_pipeline
