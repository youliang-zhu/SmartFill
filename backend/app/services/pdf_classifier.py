"""
PDF 类型分类器
"""
from pathlib import Path
from typing import Literal

from pypdf import PdfReader

PDFType = Literal["fillable", "native", "scanned"]


class PDFClassifier:
    """
    基于 AcroForm + 页面内容特征做 PDF 类型分类。
    """

    # 仅用于快速区分 scanned/native 的轻量阈值
    MIN_TEXT_CHARS: int = 20

    @staticmethod
    def classify(pdf_path: Path) -> PDFType:
        """
        分类 PDF 类型。

        Returns:
            "fillable" | "native" | "scanned"

        Raises:
            ValueError: PDF 文件损坏或无法解析
            PermissionError: PDF 被密码保护
        """
        try:
            reader = PdfReader(str(pdf_path))
        except Exception as e:
            raise ValueError(f"无法解析 PDF 文件: {e}")

        if reader.is_encrypted:
            raise PermissionError("PDF 文件被密码保护，无法读取")

        fields = reader.get_fields()
        if fields:
            return "fillable"

        # 非 fillable 的场景，再做 native/scanned 区分
        try:
            import fitz
        except ModuleNotFoundError as e:
            raise ValueError(
                "缺少 pymupdf 依赖，无法区分 native/scanned"
            ) from e

        try:
            doc = fitz.open(str(pdf_path))
        except Exception as e:
            raise ValueError(f"无法解析 PDF 文件: {e}")

        total_pages = len(doc)
        text_chars = 0
        image_pages = 0

        try:
            for page in doc:
                page_text = page.get_text("text") or ""
                text_chars += len("".join(page_text.split()))

                # get_image_info 能覆盖常见页面图片资源
                try:
                    image_count = len(page.get_image_info())
                except Exception:
                    image_count = len(page.get_images(full=True))

                if image_count > 0:
                    image_pages += 1
        finally:
            doc.close()

        is_likely_scanned = (
            text_chars <= PDFClassifier.MIN_TEXT_CHARS
            and image_pages >= max(1, total_pages // 2)
        )
        if is_likely_scanned:
            return "scanned"
        return "native"


pdf_classifier = PDFClassifier()


def get_pdf_classifier() -> PDFClassifier:
    """获取 PDF 分类器实例"""
    return pdf_classifier
