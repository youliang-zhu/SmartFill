"""
PDF 处理服务 - 表单字段读写
"""
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from pypdf import PdfReader, PdfWriter

from app.models.schemas import FieldInfo, FillResult


# pypdf 字段类型常量映射
# /FT 字段类型: Btn=按钮/复选框, Tx=文本, Ch=下拉/列表, Sig=签名
_FIELD_TYPE_MAP = {
    "/Tx": "text",
    "/Btn": "checkbox",
    "/Ch": "dropdown",
    "/Sig": "signature",
}


class PDFService:
    """PDF 处理服务"""
    
    @staticmethod
    def has_form_fields(pdf_path: Path) -> bool:
        """
        快速判断 PDF 是否包含可编辑表单字段
        
        Args:
            pdf_path: PDF 文件路径
        
        Returns:
            True 表示是可编辑表单
        
        Raises:
            ValueError: PDF 文件损坏或无法解析
            PermissionError: PDF 被密码保护
        """
        try:
            reader = PdfReader(str(pdf_path))
        except Exception as e:
            raise ValueError(f"无法解析 PDF 文件: {e}")
        
        # 检查是否加密
        if reader.is_encrypted:
            raise PermissionError("PDF 文件被密码保护，无法读取")
        
        # 检查 AcroForm 是否存在
        if reader.get_fields() is None:
            return False
        
        return len(reader.get_fields()) > 0
    
    @staticmethod
    def extract_form_fields(pdf_path: Path) -> List[str]:
        """
        提取 PDF 表单字段名称列表
        
        Args:
            pdf_path: PDF 文件路径
        
        Returns:
            表单字段名称列表
        
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
        if fields is None:
            return []
        
        return list(fields.keys())
    
    @staticmethod
    def get_field_details(pdf_path: Path) -> List[FieldInfo]:
        """
        获取 PDF 表单字段的详细信息（名称、类型、默认值）
        
        遍历所有字段，提取字段类型和已有值，用于调试和 AI 匹配。
        
        Args:
            pdf_path: PDF 文件路径
        
        Returns:
            字段详细信息列表
        
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
        if fields is None:
            return []
        
        field_details: List[FieldInfo] = []
        
        for field_name, field_obj in fields.items():
            # 提取字段类型
            field_type = "text"  # 默认文本类型
            if hasattr(field_obj, "get"):
                ft = field_obj.get("/FT", "")
                field_type = _FIELD_TYPE_MAP.get(str(ft), "text")
            
            # 提取字段已有值
            default_value = None
            if hasattr(field_obj, "get"):
                val = field_obj.get("/V")
                if val is not None:
                    default_value = str(val)
            
            field_details.append(FieldInfo(
                name=field_name,
                field_type=field_type,
                default_value=default_value,
            ))
        
        return field_details
    
    @staticmethod
    def fill_form(
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path
    ) -> FillResult:
        """
        填写 PDF 表单（支持多页）
        
        遍历所有页面查找并填写表单字段，返回详细的填写结果。
        
        Args:
            pdf_path: 原始 PDF 路径
            field_values: 字段名称到值的映射
            output_path: 输出 PDF 路径
        
        Returns:
            FillResult 填写结果详情
        
        Raises:
            ValueError: PDF 文件损坏或无法解析
            PermissionError: PDF 被密码保护
            IOError: 输出文件写入失败
        """
        try:
            reader = PdfReader(str(pdf_path))
        except Exception as e:
            raise ValueError(f"无法解析 PDF 文件: {e}")
        
        if reader.is_encrypted:
            raise PermissionError("PDF 文件被密码保护，无法读取")
        
        writer = PdfWriter()
        writer.append_pages_from_reader(reader)
        
        # 获取 PDF 中实际存在的字段名
        existing_fields = set()
        pdf_fields = reader.get_fields()
        if pdf_fields:
            existing_fields = set(pdf_fields.keys())
        
        # 分类：哪些字段能填写，哪些不存在需要跳过
        filled_fields: List[str] = []
        skipped_fields: List[str] = []
        
        for field_name, value in field_values.items():
            if field_name in existing_fields:
                filled_fields.append(field_name)
            else:
                skipped_fields.append(field_name)
        
        # 只填写 PDF 中实际存在的字段
        values_to_fill = {k: v for k, v in field_values.items() if k in existing_fields}
        
        if values_to_fill:
            # 遍历所有页面，填写表单字段
            for page_num in range(len(writer.pages)):
                try:
                    writer.update_page_form_field_values(
                        writer.pages[page_num],
                        values_to_fill
                    )
                except Exception:
                    # 某些页面可能没有表单字段，跳过
                    continue
        
        # 保存输出文件
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                writer.write(f)
        except Exception as e:
            raise IOError(f"输出文件写入失败: {e}")
        
        return FillResult(
            filled_fields=filled_fields,
            skipped_fields=skipped_fields,
            total_filled=len(filled_fields),
            total_skipped=len(skipped_fields),
        )


# 创建全局服务实例
pdf_service = PDFService()


def get_pdf_service() -> PDFService:
    """获取 PDF 服务实例"""
    return pdf_service
