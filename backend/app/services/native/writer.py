"""
Writer 模块 — PDF 写入

职责:
1. 接收所有页的 filled_fields（含 fill_rect + value）
2. 使用 pymupdf 将文本写入 PDF 对应位置
3. 处理字体大小、文字溢出、checkbox 勾选
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import fitz

from app.services.native.fill import FilledField, PageFillResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FONT_NAME = "helv"
DEFAULT_FONT_SIZE = 10.0
MIN_FONT_SIZE = 6.0
FONT_STEP = 0.5
CHECKBOX_MARK = "\u2713"  # ✓
TEXT_COLOR = (0, 0, 0)
LINE_HEIGHT_FACTOR = 1.2
BOLD_OVERDRAW_X = 0.18


# ---------------------------------------------------------------------------
# Text fitting
# ---------------------------------------------------------------------------


def _fit_text(
    text: str,
    rect_width: float,
    font_size: float,
    font_name: str = DEFAULT_FONT_NAME,
) -> tuple[str, float]:
    """
    调整文本和字号使其适合 fill_rect 宽度。
    返回 (adjusted_text, adjusted_font_size)。
    """
    # 缩小字号
    fs = font_size
    while fs >= MIN_FONT_SIZE:
        tw = fitz.get_text_length(text, fontname=font_name, fontsize=fs)
        if tw <= rect_width:
            return text, fs
        fs -= FONT_STEP

    # 字号已最小，截断文本
    fs = MIN_FONT_SIZE
    t = text
    while len(t) > 1:
        t = t[:-1]
        tw = fitz.get_text_length(t + "...", fontname=font_name, fontsize=fs)
        if tw <= rect_width:
            return t + "...", fs

    return text[:1], fs


# ---------------------------------------------------------------------------
# Field writing
# ---------------------------------------------------------------------------


def _write_text_field(
    page: fitz.Page,
    rect: tuple,
    text: str,
    font_size: float,
) -> bool:
    """写入文本字段。返回是否成功写入。"""
    if not text:
        return False

    fitz_rect = fitz.Rect(rect)
    rect_width = fitz_rect.width
    if rect_width <= 0:
        return False

    # 轻微放大目标字号，并在后续做宽度适配，增强与原表单标签的区分度
    target_size = max(font_size * 1.12, font_size + 0.8)
    fitted_text, fitted_size = _fit_text(text, rect_width, target_size)

    try:
        # 使用 baseline 写入，避免 textbox 在矮框中返回负值导致“看似写入成功但页面无字”。
        # baseline 取 rect 垂直中心附近，保证视觉上居中。
        baseline_y = fitz_rect.y0 + (fitz_rect.height + fitted_size) / 2.0
        p1 = (fitz_rect.x0, baseline_y)
        p2 = (fitz_rect.x0 + BOLD_OVERDRAW_X, baseline_y)

        # 双次绘制模拟更深更黑字重
        page.insert_text(
            p1,
            fitted_text,
            fontsize=fitted_size,
            fontname=DEFAULT_FONT_NAME,
            color=TEXT_COLOR,
        )
        page.insert_text(
            p2,
            fitted_text,
            fontsize=fitted_size,
            fontname=DEFAULT_FONT_NAME,
            color=TEXT_COLOR,
        )
        return True
    except Exception as e:
        logger.warning("Failed to write text at %s: %s", rect, e)
        return False


def _write_checkbox(page: fitz.Page, rect: tuple) -> bool:
    """在 checkbox 方框内写入勾选标记。返回是否成功。"""
    try:
        fitz_rect = fitz.Rect(rect)
        cx = (rect[0] + rect[2]) / 2
        cy = (rect[1] + rect[3]) / 2
        size = min(fitz_rect.width, fitz_rect.height)
        if size <= 0:
            return False
        fs = size * 0.7

        page.insert_text(
            (cx - fs * 0.3, cy + fs * 0.3),
            CHECKBOX_MARK,
            fontsize=fs,
            color=TEXT_COLOR,
        )
        return True
    except Exception as e:
        logger.warning("Failed to write checkbox at %s: %s", rect, e)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class WriteStats:
    total_written: int = 0
    total_skipped: int = 0
    text_written: int = 0
    checkbox_written: int = 0


def write_filled_pdf(
    pdf_path: str,
    output_path: str,
    all_page_fills: List[PageFillResult],
) -> WriteStats:
    """
    将所有页的填写结果写入 PDF。

    Args:
        pdf_path: 原始 PDF 路径
        output_path: 输出 PDF 路径
        all_page_fills: 每页的填写结果

    Returns:
        WriteStats 写入统计
    """
    doc = fitz.open(pdf_path)
    stats = WriteStats()

    for page_fill in all_page_fills:
        if page_fill.page_num < 1 or page_fill.page_num > len(doc):
            logger.warning("Invalid page_num %d, skipping", page_fill.page_num)
            continue

        page = doc[page_fill.page_num - 1]

        for ff in page_fill.filled_fields:
            if not ff.value:
                stats.total_skipped += 1
                continue

            if ff.field_type == "checkbox":
                if ff.value.lower() == "checked":
                    ok = _write_checkbox(page, ff.fill_rect)
                    if ok:
                        stats.checkbox_written += 1
                        stats.total_written += 1
                    else:
                        stats.total_skipped += 1
                else:
                    stats.total_skipped += 1
            else:
                ok = _write_text_field(page, ff.fill_rect, ff.value, ff.font_size)
                if ok:
                    stats.text_written += 1
                    stats.total_written += 1
                else:
                    stats.total_skipped += 1

    # 确保输出目录存在
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    doc.close()

    logger.info(
        "Written PDF: %s (text=%d, checkbox=%d, skipped=%d)",
        output_path, stats.text_written, stats.checkbox_written, stats.total_skipped,
    )
    return stats
