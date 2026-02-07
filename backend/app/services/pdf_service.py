"""
PDF 处理服务（预留）
"""
from pathlib import Path
from typing import List, Dict, Optional

from pypdf import PdfReader, PdfWriter


class PDFService:
    """PDF 处理服务"""
    
    @staticmethod
    def extract_form_fields(pdf_path: Path) -> List[str]:
        """
        提取 PDF 表单字段
        
        Args:
            pdf_path: PDF 文件路径
        
        Returns:
            表单字段名称列表
        """
        try:
            reader = PdfReader(str(pdf_path))
            fields = reader.get_form_text_fields()
            
            if fields is None:
                return []
            
            return list(fields.keys())
        except Exception as e:
            print(f"Error extracting fields: {e}")
            return []
    
    @staticmethod
    def fill_form(
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path
    ) -> bool:
        """
        填写 PDF 表单
        
        Args:
            pdf_path: 原始 PDF 路径
            field_values: 字段名称到值的映射
            output_path: 输出 PDF 路径
        
        Returns:
            是否成功
        """
        try:
            reader = PdfReader(str(pdf_path))
            writer = PdfWriter()
            
            # 复制所有页面
            for page in reader.pages:
                writer.add_page(page)
            
            # 填写表单字段
            writer.update_page_form_field_values(
                writer.pages[0],
                field_values
            )
            
            # 保存输出文件
            with open(output_path, "wb") as f:
                writer.write(f)
            
            return True
        except Exception as e:
            print(f"Error filling form: {e}")
            return False


# 创建全局服务实例
pdf_service = PDFService()


def get_pdf_service() -> PDFService:
    """获取 PDF 服务实例"""
    return pdf_service
