"""
PDF 处理服务 - 表单字段读写
"""
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject, TextStringObject

from app.models.schemas import FieldInfo, FillResult

logger = logging.getLogger("app.services.ai_service")  # 复用 AI 日志文件


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
        
        writer = PdfWriter(clone_from=str(pdf_path))
        
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
        
        logger.info(f"[PDF 填写] 准备写入 {len(values_to_fill)} 个字段: {values_to_fill}")
        logger.info(f"[PDF 填写] 总页数: {len(writer.pages)}")
        
        actually_filled: List[str] = []
        
        if values_to_fill:
            # 手动遍历所有页面的 annotations，直接写入字段值
            for page_num in range(len(writer.pages)):
                page = writer.pages[page_num]
                annots = page.get("/Annots")
                if not annots:
                    logger.info(f"[PDF 填写] 第 {page_num + 1} 页: 无 annotations，跳过")
                    continue
                
                logger.info(f"[PDF 填写] 第 {page_num + 1} 页: {len(annots)} 个 annotations")
                
                for annot in annots:
                    # 兼容 IndirectObject 和 dict
                    annot_obj = annot.get_object() if hasattr(annot, 'get_object') else annot
                    
                    field_name = annot_obj.get("/T")
                    if field_name is None:
                        continue
                    
                    field_name_str = str(field_name)
                    
                    if field_name_str in values_to_fill:
                        value = values_to_fill[field_name_str]
                        # 直接设置 /V（字段值）
                        annot_obj[NameObject("/V")] = TextStringObject(value)
                        # 同时设置 /AP 为空，强制 PDF 阅读器重新渲染显示
                        if NameObject("/AP") in annot_obj:
                            del annot_obj[NameObject("/AP")]
                        actually_filled.append(field_name_str)
                        logger.info(f"  ✅ {field_name_str} = {value}")
                    else:
                        logger.info(f"  ⏭️ {field_name_str}: 无匹配值，跳过")
        
        # 设置 NeedAppearances 标志，确保 PDF 阅读器重新生成字段外观
        try:
            root = writer._root_object if hasattr(writer, '_root_object') else None
            if root is None and hasattr(writer, '_root'):
                root = writer._root
            if root:
                acroform = root.get("/AcroForm")
                if acroform:
                    acro_obj = acroform.get_object() if hasattr(acroform, 'get_object') else acroform
                    acro_obj[NameObject("/NeedAppearances")] = BooleanObject(True)
                    logger.info("[PDF 填写] 已设置 /NeedAppearances = true")
                else:
                    logger.warning("[PDF 填写] 未找到 /AcroForm，跳过 NeedAppearances 设置")
            else:
                logger.warning("[PDF 填写] 无法访问 root object，跳过 NeedAppearances 设置")
        except Exception as e:
            logger.warning(f"[PDF 填写] 设置 NeedAppearances 失败（不影响填写）: {e}")
        
        logger.info(f"[PDF 填写] 实际写入成功: {len(actually_filled)} 个字段: {actually_filled}")
        
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
