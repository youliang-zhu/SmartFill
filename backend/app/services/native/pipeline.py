"""
Native PDF 业务流水线

完整流程: Preprocess → Recognize (VLM) → Fill (LLM) → Write
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from app.config import get_settings
from app.models.schemas import FieldInfo, FillResult
from app.services.native.preprocess.detector import get_native_detector
from app.services.native.recognize import recognize_page
from app.services.native.fill import fill_page, read_user_memory, PageFillResult
from app.services.native.writer import write_filled_pdf

logger = logging.getLogger(__name__)


class NativePipeline:
    """native 类型流水线: preprocess → recognize → fill → write。"""

    def __init__(self):
        self.detector = get_native_detector()
        self.settings = get_settings()

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
        memory_path: str | None = None,
    ) -> FillResult:
        """
        完整 AI 填写流程: preprocess → recognize → fill → write

        Args:
            pdf_path: 输入 PDF 路径
            user_info: 用户信息文本（暂未使用，用 memory 文件代替）
            output_path: 输出 PDF 路径
            memory_path: user memory 文件路径，默认读取 TestSpace 下的文件
        """
        # 1. Preprocess
        logger.info("Pipeline: preprocess %s", pdf_path)
        preprocess_result = self.detector.detect_all(pdf_path)

        # 2. 读取 user memory
        user_memory = read_user_memory(memory_path)
        if not user_memory:
            logger.warning("No user memory loaded, LLM may not fill fields correctly")

        all_page_fills: List[PageFillResult] = []
        total_vlm_fields = 0
        total_matched = 0

        for page_data in preprocess_result["pages"]:
            page_num = page_data["page_num"]
            preprocess_fields = page_data.get("detected_fields", [])
            text_spans = page_data.get("text_spans", [])

            if not preprocess_fields:
                logger.info("Pipeline: page %d has no fields, skipping", page_num)
                continue

            # 3. Recognize (VLM)
            logger.info("Pipeline: recognize page %d (%d preprocess fields)",
                        page_num, len(preprocess_fields))
            recognize_result = recognize_page(
                pdf_path=str(pdf_path),
                page_num=page_num,
                preprocess_fields=preprocess_fields,
                text_spans=text_spans,
                settings=self.settings,
            )

            total_vlm_fields += sum(
                len(g["fields"]) for g in recognize_result.matched_groups
            )
            total_matched += sum(
                len(g["fields"]) for g in recognize_result.matched_groups
            )

            if not recognize_result.matched_groups:
                logger.info("Pipeline: page %d no matched fields, skipping fill", page_num)
                continue

            # 4. Fill (LLM)
            logger.info("Pipeline: fill page %d (%d matched groups)",
                        page_num, len(recognize_result.matched_groups))
            fill_result = fill_page(
                page_num=page_num,
                matched_groups=recognize_result.matched_groups,
                user_memory=user_memory,
                settings=self.settings,
            )
            all_page_fills.append(fill_result)

        # 5. Write
        if all_page_fills:
            logger.info("Pipeline: writing PDF to %s", output_path)
            write_stats = write_filled_pdf(
                pdf_path=str(pdf_path),
                output_path=str(output_path),
                all_page_fills=all_page_fills,
            )
            filled_list = []
            skipped_list = []
            for pf in all_page_fills:
                for ff in pf.filled_fields:
                    if ff.value:
                        filled_list.append(ff.field_id)
                    else:
                        skipped_list.append(ff.field_id)
        else:
            logger.warning("Pipeline: no fields to write")
            filled_list = []
            skipped_list = []

        return FillResult(
            filled_fields=filled_list,
            skipped_fields=skipped_list,
            total_filled=len(filled_list),
            total_skipped=len(skipped_list),
        )

    def fill_by_fields(
        self,
        pdf_path: Path,
        field_values: Dict[str, str],
        output_path: Path,
    ) -> FillResult:
        raise NotImplementedError("fill_by_fields 暂不支持 native PDF")


_native_pipeline = NativePipeline()


def get_native_pipeline() -> NativePipeline:
    """获取 native 流水线单例。"""
    return _native_pipeline
