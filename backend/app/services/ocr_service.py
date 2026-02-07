"""
OCR 服务抽象接口（预留）
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class OCRService(ABC):
    """OCR 服务抽象基类"""
    
    @abstractmethod
    async def extract_text(self, image_path: Path) -> Optional[str]:
        """
        从图片中提取文本
        
        Args:
            image_path: 图片路径
        
        Returns:
            提取的文本，如果失败返回 None
        """
        pass
    
    @abstractmethod
    async def extract_from_pdf(self, pdf_path: Path) -> Optional[str]:
        """
        从扫描版 PDF 中提取文本
        
        Args:
            pdf_path: PDF 路径
        
        Returns:
            提取的文本，如果失败返回 None
        """
        pass


class PlaceholderOCRService(OCRService):
    """OCR 服务占位实现"""
    
    async def extract_text(self, image_path: Path) -> Optional[str]:
        """预留实现"""
        raise NotImplementedError("OCR 服务将在后续版本实现")
    
    async def extract_from_pdf(self, pdf_path: Path) -> Optional[str]:
        """预留实现"""
        raise NotImplementedError("OCR 服务将在后续版本实现")


def get_ocr_service() -> OCRService:
    """获取 OCR 服务实例"""
    return PlaceholderOCRService()
