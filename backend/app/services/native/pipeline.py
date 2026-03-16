"""
Native PDF 业务流水线（v2 预留）
"""
from pathlib import Path
from typing import Dict, List, Tuple

from app.models.schemas import FieldInfo, FillResult


class NativePipeline:
    """native 类型流水线（当前阶段未实现）。"""

    _NOT_READY_MESSAGE = "native pipeline暂未实现"

    def extract_fields(self, pdf_path: Path) -> Tuple[List[str], List[FieldInfo]]:
        raise NotImplementedError(self._NOT_READY_MESSAGE)

    async def fill_with_ai(
        self,
        pdf_path: Path,
        user_info: str,
        output_path: Path,
    ) -> FillResult:
        raise NotImplementedError(self._NOT_READY_MESSAGE)

    def fill_by_fields(
        self,
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path,
    ) -> FillResult:
        raise NotImplementedError(self._NOT_READY_MESSAGE)


_native_pipeline = NativePipeline()


def get_native_pipeline() -> NativePipeline:
    """获取 native 流水线单例。"""
    return _native_pipeline
