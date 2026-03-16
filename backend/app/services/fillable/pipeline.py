"""
Fillable PDF 业务流水线（仅 AcroForm）
"""
from pathlib import Path
from typing import Dict, List, Tuple

from app.models.schemas import FieldInfo, FillResult
from app.services.fillable.ai_service import get_ai_service
from app.services.fillable.pdf_service import get_pdf_service


class FillablePipeline:
    """fillable 类型流水线。"""

    def __init__(self):
        self.pdf_service = get_pdf_service()

    def extract_fields(self, pdf_path: Path) -> Tuple[List[str], List[FieldInfo]]:
        """
        提取字段（fillable）。
        """
        field_names = self.pdf_service.extract_form_fields(pdf_path)
        field_details = self.pdf_service.get_field_details(pdf_path)
        return field_names, field_details

    async def fill_with_ai(
        self,
        pdf_path: Path,
        user_info: str,
        output_path: Path,
    ) -> FillResult:
        """
        AI 填写（fillable）。
        """
        field_names = self.pdf_service.extract_form_fields(pdf_path)
        ai_service = get_ai_service()
        field_values = await ai_service.match_fields(field_names, user_info)
        return self.pdf_service.fill_form(pdf_path, field_values, output_path)

    def fill_by_fields(
        self,
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path,
    ) -> FillResult:
        """
        手动字段映射填写（fillable）。
        """
        return self.pdf_service.fill_form(pdf_path, field_values, output_path)


_fillable_pipeline = FillablePipeline()


def get_fillable_pipeline() -> FillablePipeline:
    """获取 fillable 流水线单例。"""
    return _fillable_pipeline
