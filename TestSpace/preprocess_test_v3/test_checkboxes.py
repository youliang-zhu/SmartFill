"""Phase 2A Checkbox 检测测试 + 可视化渲染。

用法:
    cd SmartFill
    python TestSpace/preprocess_test_v3/test_checkboxes.py --batch        # 全部 6 个 PDF
    python TestSpace/preprocess_test_v3/test_checkboxes.py --pdf 001      # 关键词过滤
    python TestSpace/preprocess_test_v3/test_checkboxes.py --pdf 008 --json  # 输出 JSON
"""
from __future__ import annotations

import sys
sys.path.insert(0, "backend")

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import fitz

from app.services.native.preprocess.detector import get_native_detector
from app.services.native.preprocess.collector.collect_checkboxes import collect_checkboxes, _detect_table_zones
from common import TEST_PDFS, collect_phase1_with_merge, existing_pdf_paths
from viz_utils import COLOR_RED, COLOR_BLUE, COLOR_ORANGE, COLOR_CYAN, COLOR_GREEN, draw_id_badge

COLOR_PURPLE = (0.6, 0.2, 0.8)

RESULT_DIR = Path("TestSpace/preprocess_test_v3/results/phase2_checkboxes")


def _stem24(pdf_path: str) -> str:
    return Path(pdf_path).stem[:40]


def _draw_checkbox_field(page: fitz.Page, field: Dict[str, Any], idx: int) -> None:
    """在页面上渲染一个 checkbox 字段。

    - 红色粗框：整体 fill_rect（外包围框）
    - 红色细框 + 半透明填充：每个 option 的 bbox
    - 蓝色框：label_bbox
    - 橙色文字：option text 标注
    - 青色框 + 文字：additional_text
    """
    gid = field.get("group_id", idx)

    # 外包围框（红色粗框）
    fill_rect = field.get("fill_rect")
    if fill_rect:
        rect = fitz.Rect(fill_rect)
        shape = page.new_shape()
        shape.draw_rect(rect)
        shape.finish(color=COLOR_RED, width=1.5)
        shape.commit()

        draw_id_badge(page, rect, f"G{gid}", COLOR_RED, fontsize=6, y_offset=2.0)

    # Label bbox（蓝色虚线框 + 文字标注）
    label_bbox = field.get("label_bbox")
    if label_bbox:
        lb = fitz.Rect(label_bbox)
        shape = page.new_shape()
        shape.draw_rect(lb)
        shape.finish(color=COLOR_BLUE, width=0.6)
        shape.commit()

        label_text = field.get("label", "")[:60]
        if label_text:
            draw_id_badge(page, lb, f"G{gid} L", COLOR_BLUE, fontsize=5, y_offset=1.0)
            page.insert_text(
                fitz.Point(lb.x0 + 18, max(6.0, lb.y0 - 1.0)),
                label_text,
                fontsize=4,
                color=COLOR_BLUE,
                fontname="helv",
            )

    # 每个 option（红色细框 + 半透明填充 + 右侧标注）
    for opt_idx, opt in enumerate(field.get("options", []), start=1):
        bbox = opt.get("bbox")
        if not bbox:
            continue
        r = fitz.Rect(bbox)
        shape = page.new_shape()
        shape.draw_rect(r)
        shape.finish(color=COLOR_RED, fill=COLOR_RED, fill_opacity=0.15, width=0.8)
        shape.commit()
        draw_id_badge(page, r, f"G{gid}-O{opt_idx}", COLOR_ORANGE, fontsize=4.5, y_offset=0.5)

        opt_text = opt.get("text", "")
        if opt_text:
            page.insert_text(
                fitz.Point(r.x1 + 2, r.y1),
                opt_text[:20],
                fontsize=5,
                color=COLOR_ORANGE,
                fontname="helv",
            )

    # Additional text（绿色框 + 文字标注）
    for add_idx, at in enumerate(field.get("additional_text", []), start=1):
        add_id = f"G{gid}-A{add_idx}"
        # 用 label_bbox 画文字包围框
        at_lb = at.get("label_bbox") or at.get("fill_rect")
        if not at_lb:
            continue
        r = fitz.Rect(at_lb)
        shape = page.new_shape()
        shape.draw_rect(r)
        shape.finish(color=COLOR_GREEN, width=0.6)
        shape.commit()
        draw_id_badge(page, r, f"{add_id} L", COLOR_GREEN, fontsize=5, y_offset=1.0)

        at_label = at.get("label", "")[:40]
        if at_label:
            page.insert_text(
                fitz.Point(r.x0 + 26, max(6.0, r.y0 - 1.0)),
                at_label,
                fontsize=4,
                color=COLOR_GREEN,
                fontname="helv",
            )

        at_fr = at.get("fill_rect")
        if at_fr:
            fr = fitz.Rect(at_fr)
            shape2 = page.new_shape()
            shape2.draw_rect(fr)
            shape2.finish(color=COLOR_GREEN, fill=COLOR_GREEN, fill_opacity=0.10, width=0.7)
            shape2.commit()
            draw_id_badge(page, fr, add_id, COLOR_GREEN, fontsize=5, y_offset=0.5)


def run_one_pdf(pdf_path: str, save_json: bool = False) -> Dict[str, Any]:
    """对单个 PDF 运行 checkbox 检测并渲染。"""
    stem = _stem24(pdf_path)
    detector = get_native_detector()
    doc = fitz.open(pdf_path)

    all_fields: Dict[int, List[Dict[str, Any]]] = {}
    all_table_zones: Dict[int, List] = {}
    summary = {"pdf": stem, "pages": []}

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        page = doc[page_idx]

        # Phase 1 + 1.5
        phase1 = collect_phase1_with_merge(detector, page, page_num)
        phase1_data = {
            "page_num": page_num,
            "pdf_path": pdf_path,
            "page_size": phase1.get("page_rect"),
            "text_spans": phase1["text_spans"],
            "text_lines": phase1["merged_lines"],
            "drawing_data": phase1["drawing_data"],
            "table_structures": phase1["tables"],
        }

        # Phase 2A: checkbox
        fields, consumed = collect_checkboxes(phase1_data)
        all_fields[page_num] = fields

        # 记录表格区域供可视化使用
        table_zones = _detect_table_zones(
            phase1.get("tables", []),
            phase1.get("drawing_data", {}).get("vertical_lines", []),
        )
        if table_zones:
            all_table_zones[page_num] = table_zones

        page_stat = {
            "page": page_num,
            "checkbox_count": len(fields),
            "consumed_count": len(consumed),
            "square_boxes_total": len(phase1["drawing_data"].get("square_boxes", [])),
        }
        summary["pages"].append(page_stat)

        # 打印每页统计
        sb = page_stat["square_boxes_total"]
        fc = page_stat["checkbox_count"]
        if fc > 0 or sb > 0:
            print(f"  p{page_num}: {sb} square_boxes → {fc} checkbox fields")

    total_fields = sum(len(f) for f in all_fields.values())
    summary["total_checkbox_fields"] = total_fields
    print(f"  合计: {total_fields} checkbox fields")

    # 渲染标注 PDF
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    out_pdf = RESULT_DIR / f"cb_{stem}.pdf"
    render_doc = fitz.open(pdf_path)

    for page_num, fields in all_fields.items():
        page = render_doc[page_num - 1]
        # 画表格区域（紫色半透明横带）
        for y_top, y_bot in all_table_zones.get(page_num, []):
            pw = page.rect.width
            shape = page.new_shape()
            shape.draw_rect(fitz.Rect(0, y_top, pw, y_bot))
            shape.finish(color=COLOR_PURPLE, fill=COLOR_PURPLE, fill_opacity=0.10, width=0.8)
            shape.commit()
            page.insert_text(
                fitz.Point(2, y_top + 8),
                f"TABLE ZONE y={y_top:.0f}~{y_bot:.0f}",
                fontsize=5, color=COLOR_PURPLE, fontname="helv",
            )
        for idx, field in enumerate(fields, start=1):
            _draw_checkbox_field(page, field, idx)

    render_doc.save(str(out_pdf))
    render_doc.close()
    print(f"  → {out_pdf}")

    # JSON
    if save_json:
        out_json = RESULT_DIR / f"cb_{stem}.json"
        # 把 fields 整理成可 JSON 序列化的结构
        json_data = {}
        for page_num, fields in all_fields.items():
            json_data[str(page_num)] = fields
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "fields_by_page": json_data}, f,
                       indent=2, ensure_ascii=False)
        print(f"  → {out_json}")

    doc.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Checkbox detection test")
    parser.add_argument("--batch", action="store_true", help="Run all test PDFs")
    parser.add_argument("--pdf", type=str, help="Filter PDFs by keyword")
    parser.add_argument("--json", action="store_true", help="Also output JSON")
    args = parser.parse_args()

    pdfs = existing_pdf_paths()
    if args.pdf:
        pdfs = [p for p in pdfs if args.pdf in p]
    elif not args.batch:
        pdfs = existing_pdf_paths()  # default: all

    if not pdfs:
        print("No matching PDFs found")
        return

    print(f"=== Checkbox Detection Test ({len(pdfs)} PDFs) ===\n")
    all_summaries = []
    for pdf_path in pdfs:
        print(f"[{_stem24(pdf_path)}]")
        s = run_one_pdf(pdf_path, save_json=args.json)
        all_summaries.append(s)
        print()

    # 总结
    total = sum(s["total_checkbox_fields"] for s in all_summaries)
    print(f"=== 总计: {total} checkbox fields across {len(pdfs)} PDFs ===")


if __name__ == "__main__":
    main()
