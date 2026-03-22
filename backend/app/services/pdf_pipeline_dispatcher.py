"""
PDF 类型分发器（通用层）
"""
from pathlib import Path
from typing import Dict, Literal, Protocol, Tuple

from app.models.schemas import FieldInfo, FillResult
from app.services.fillable.pipeline import get_fillable_pipeline
from app.services.native.pipeline import get_native_pipeline
from app.services.pdf_classifier import get_pdf_classifier

PDFType = Literal["fillable", "native", "scanned"]


class PipelineProtocol(Protocol):
    """统一流水线接口。"""

    def extract_fields(self, pdf_path: Path) -> Tuple[list[str], list[FieldInfo]]: ...

    async def fill_with_ai(
        self,
        pdf_path: Path,
        user_info: str,
        output_path: Path,
    ) -> FillResult: ...

    def fill_by_fields(
        self,
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path,
    ) -> FillResult: ...


class PDFPipelineDispatcher:
    """
    统一 PDF 分发器。

    规则：
    - fillable -> fillable pipeline
    - native/scanned -> native pipeline（当前未实现，返回 NotImplementedError）
    """

    def __init__(self):
        self.classifier = get_pdf_classifier()
        self.fillable_pipeline = get_fillable_pipeline()
        self.native_pipeline = get_native_pipeline()

    def _select_pipeline(self, pdf_path: Path) -> tuple[PDFType, PipelineProtocol]:
        pdf_type = self.classifier.classify(pdf_path)
        if pdf_type == "fillable":
            return pdf_type, self.fillable_pipeline
        if pdf_type == "native":
            return pdf_type, self.native_pipeline
        raise NotImplementedError("pdf分类有问题：当前暂不支持 scanned 类型 PDF")

    def extract_fields(self, pdf_path: Path) -> Tuple[list[str], list[FieldInfo]]:
        _, pipeline = self._select_pipeline(pdf_path)
        return pipeline.extract_fields(pdf_path)

    async def fill_with_ai(
        self,
        pdf_path: Path,
        user_info: str,
        output_path: Path,
    ) -> FillResult:
        _, pipeline = self._select_pipeline(pdf_path)
        return await pipeline.fill_with_ai(pdf_path, user_info, output_path)

    def fill_by_fields(
        self,
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path,
    ) -> FillResult:
        _, pipeline = self._select_pipeline(pdf_path)
        return pipeline.fill_by_fields(pdf_path, field_values, output_path)


_dispatcher = PDFPipelineDispatcher()


def get_pdf_pipeline_dispatcher() -> PDFPipelineDispatcher:
    """获取 PDF 分发器单例。"""
    return _dispatcher
