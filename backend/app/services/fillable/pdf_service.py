"""
PDF 处理服务 - Fillable（仅 AcroForm）字段读写
"""
import logging
from pathlib import Path
from typing import Dict, List

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject, TextStringObject

from app.models.schemas import FieldInfo, FillResult

logger = logging.getLogger("app.services.fillable.ai_service")  # 复用 AI 日志文件


# pypdf 字段类型常量映射
# /FT 字段类型: Btn=按钮/复选框, Tx=文本, Ch=下拉/列表, Sig=签名
_FIELD_TYPE_MAP = {
    "/Tx": "text",
    "/Btn": "checkbox",
    "/Ch": "dropdown",
    "/Sig": "signature",
}


class PDFService:
    """Fillable PDF 处理服务（仅 AcroForm）"""

    @staticmethod
    def _load_reader(pdf_path: Path) -> PdfReader:
        """统一 Reader 加载与基础校验。"""
        try:
            reader = PdfReader(str(pdf_path))
        except Exception as e:
            raise ValueError(f"无法解析 PDF 文件: {e}")

        if reader.is_encrypted:
            raise PermissionError("PDF 文件被密码保护，无法读取")

        return reader

    @staticmethod
    def has_form_fields(pdf_path: Path) -> bool:
        """
        快速判断 PDF 是否包含可编辑 AcroForm 字段。
        """
        reader = PDFService._load_reader(pdf_path)
        fields = reader.get_fields()
        return bool(fields and len(fields) > 0)

    @staticmethod
    def extract_form_fields(pdf_path: Path) -> List[str]:
        """
        提取 AcroForm 字段名称列表。
        """
        reader = PDFService._load_reader(pdf_path)
        fields = reader.get_fields()
        if fields is None:
            return []
        return list(fields.keys())

    @staticmethod
    def get_field_details(pdf_path: Path) -> List[FieldInfo]:
        """
        获取 AcroForm 字段详细信息（名称、类型、默认值）。
        """
        reader = PDFService._load_reader(pdf_path)
        fields = reader.get_fields()
        if fields is None:
            return []

        field_details: List[FieldInfo] = []
        for field_name, field_obj in fields.items():
            field_type = "text"  # 默认文本类型
            if hasattr(field_obj, "get"):
                ft = field_obj.get("/FT", "")
                field_type = _FIELD_TYPE_MAP.get(str(ft), "text")

            default_value = None
            if hasattr(field_obj, "get"):
                val = field_obj.get("/V")
                if val is not None:
                    default_value = str(val)

            field_details.append(
                FieldInfo(
                    name=field_name,
                    field_type=field_type,
                    default_value=default_value,
                )
            )

        return field_details

    @staticmethod
    def fill_form(
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path,
    ) -> FillResult:
        """
        填写 AcroForm PDF（支持多页）。
        """
        reader = PDFService._load_reader(pdf_path)
        writer = PdfWriter(clone_from=str(pdf_path))

        existing_fields = set()
        pdf_fields = reader.get_fields()
        if pdf_fields:
            existing_fields = set(pdf_fields.keys())

        filled_fields: List[str] = []
        skipped_fields: List[str] = []
        for field_name in field_values.keys():
            if field_name in existing_fields:
                filled_fields.append(field_name)
            else:
                skipped_fields.append(field_name)

        values_to_fill = {k: v for k, v in field_values.items() if k in existing_fields}

        logger.info(f"[PDF 填写] 准备写入 {len(values_to_fill)} 个字段: {values_to_fill}")
        logger.info(f"[PDF 填写] 总页数: {len(writer.pages)}")

        actually_filled: List[str] = []

        if values_to_fill:
            for page_num in range(len(writer.pages)):
                page = writer.pages[page_num]
                annots = page.get("/Annots")
                annots = annots.get_object() if hasattr(annots, "get_object") else annots
                if not annots:
                    logger.info(f"[PDF 填写] 第 {page_num + 1} 页: 无 annotations，跳过")
                    continue

                logger.info(f"[PDF 填写] 第 {page_num + 1} 页: {len(annots)} 个 annotations")

                for annot in annots:
                    annot_obj = annot.get_object() if hasattr(annot, "get_object") else annot
                    field_name = annot_obj.get("/T")
                    if field_name is None:
                        continue

                    field_name_str = str(field_name)
                    if field_name_str not in values_to_fill:
                        logger.info(f"  ⏭️ {field_name_str}: 无匹配值，跳过")
                        continue

                    value = values_to_fill[field_name_str]
                    annot_obj[NameObject("/V")] = TextStringObject(value)
                    if NameObject("/AP") in annot_obj:
                        del annot_obj[NameObject("/AP")]
                    actually_filled.append(field_name_str)
                    logger.info(f"  ✅ {field_name_str} = {value}")

        # 设置 NeedAppearances 标志，确保 PDF 阅读器重新生成字段外观
        try:
            root = writer._root_object if hasattr(writer, "_root_object") else None
            if root is None and hasattr(writer, "_root"):
                root = writer._root

            if root:
                acroform = root.get("/AcroForm")
                if acroform:
                    acro_obj = acroform.get_object() if hasattr(acroform, "get_object") else acroform
                    acro_obj[NameObject("/NeedAppearances")] = BooleanObject(True)
                    logger.info("[PDF 填写] 已设置 /NeedAppearances = true")
                else:
                    logger.warning("[PDF 填写] 未找到 /AcroForm，跳过 NeedAppearances 设置")
            else:
                logger.warning("[PDF 填写] 无法访问 root object，跳过 NeedAppearances 设置")
        except Exception as e:
            logger.warning(f"[PDF 填写] 设置 NeedAppearances 失败（不影响填写）: {e}")

        logger.info(f"[PDF 填写] 实际写入成功: {len(actually_filled)} 个字段: {actually_filled}")

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
