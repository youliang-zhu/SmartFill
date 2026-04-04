"""Phase 2B Text 字段检测测试 + 可视化渲染。

用法:
    cd SmartFill
    python TestSpace/preprocess_test_v3/test_text_fields.py --batch
    python TestSpace/preprocess_test_v3/test_text_fields.py --pdf 004
    python TestSpace/preprocess_test_v3/test_text_fields.py --pdf 008 --json
"""
from __future__ import annotations

import sys
sys.path.insert(0, "backend")

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set

import fitz

from app.services.native.preprocess.detector import get_native_detector
from app.services.native.preprocess.collector.collect_checkboxes import collect_checkboxes, _detect_table_zones
from app.services.native.preprocess.collector.collect_text_fields import collect_text_fields
from common import TEST_PDFS, collect_phase1_with_merge, existing_pdf_paths
from viz_utils import COLOR_BLUE, COLOR_GREEN, COLOR_GRAY, COLOR_RED, COLOR_ORANGE, draw_id_badge

COLOR_PURPLE = (0.6, 0.2, 0.8)
COLOR_TEAL = (0.0, 0.6, 0.5)

RESULT_DIR = Path("TestSpace/preprocess_test_v3/results/phase2_text_fields")


def _stem24(pdf_path: str) -> str:
    return Path(pdf_path).stem[:40]


def run_one_pdf(pdf_path: str, save_json: bool = False) -> Dict[str, Any]:
    stem = _stem24(pdf_path)
    detector = get_native_detector()
    doc = fitz.open(pdf_path)

    all_text_fields: Dict[int, List[Dict[str, Any]]] = {}
    all_filtered: Dict[int, List[Dict[str, Any]]] = {}
    all_table_zones: Dict[int, List] = {}
    summary: Dict[str, Any] = {"pdf": stem, "pages": []}

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        page = doc[page_idx]

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

        # Phase 2A: checkbox (get consumed)
        cb_fields, consumed = collect_checkboxes(phase1_data)

        # Phase 2B: text fields（传入 checkbox 输出作为禁区）
        text_fields, consumed_text = collect_text_fields(phase1_data, consumed, checkbox_fields=cb_fields)
        all_text_fields[page_num] = text_fields

        # 记录被过滤掉的行（用于灰色可视化）
        consumed_line_ids: Set[int] = set()
        for c in consumed:
            if c.startswith("line:"):
                consumed_line_ids.add(int(c.split(":")[1]))
        for c in consumed_text:
            if c.startswith("line:"):
                consumed_line_ids.add(int(c.split(":")[1]))

        table_zones = _detect_table_zones(
            phase1.get("tables", []),
            phase1.get("drawing_data", {}).get("vertical_lines", []),
        )
        if table_zones:
            all_table_zones[page_num] = table_zones

        # 被过滤掉的行: 总行 - consumed_by_cb - consumed_by_text
        filtered = []
        for idx, line in enumerate(phase1["merged_lines"]):
            text = line.get("text", "").strip()
            if not text:
                continue
            if idx not in consumed_line_ids:
                filtered.append({"text": text, "bbox": line["bbox"]})
        all_filtered[page_num] = filtered

        page_stat = {
            "page": page_num,
            "total_lines": len(phase1["merged_lines"]),
            "cb_consumed": len([c for c in consumed if c.startswith("line:")]),
            "text_fields": len(text_fields),
            "filtered_out": len(filtered),
        }
        summary["pages"].append(page_stat)

        if text_fields:
            print(f"  p{page_num}: {page_stat['total_lines']} lines → "
                  f"{len(text_fields)} text fields, "
                  f"{page_stat['cb_consumed']} cb consumed, "
                  f"{len(filtered)} filtered out")

    total = sum(len(f) for f in all_text_fields.values())
    summary["total_text_fields"] = total
    print(f"  合计: {total} text fields")

    # 渲染
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    out_pdf = RESULT_DIR / f"tf_{stem}.pdf"
    render_doc = fitz.open(pdf_path)

    for page_num in range(1, len(render_doc) + 1):
        page = render_doc[page_num - 1]

        # 表格区域（紫色半透明横带）
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

        # 被过滤掉的行（灰色虚线框）
        for item in all_filtered.get(page_num, []):
            r = fitz.Rect(item["bbox"])
            shape = page.new_shape()
            shape.draw_rect(r)
            shape.finish(color=COLOR_GRAY, width=0.3, dashes="[2] 0")
            shape.commit()
            page.insert_text(
                fitz.Point(r.x0, max(6.0, r.y0 - 1.0)),
                f"FILTERED: {item['text'][:40]}",
                fontsize=3.5, color=COLOR_GRAY, fontname="helv",
            )

        # Text fields（label 框 + fill_rect）
        for idx, field in enumerate(all_text_fields.get(page_num, []), start=1):
            lb = field.get("label_bbox")
            if not lb:
                continue
            r = fitz.Rect(lb)
            shape = page.new_shape()
            shape.draw_rect(r)
            shape.finish(color=COLOR_TEAL, fill=COLOR_TEAL, fill_opacity=0.08, width=0.8)
            shape.commit()
            draw_id_badge(page, r, f"T{idx} L", COLOR_TEAL, fontsize=5, y_offset=1.0)

            label = field.get("label", "")[:50]
            page.insert_text(
                fitz.Point(r.x0 + 18, max(6.0, r.y0 - 1.0)),
                label,
                fontsize=4,
                color=COLOR_TEAL,
                fontname="helv",
            )

            # fill_rect（绿色半透明 + 标注）
            fr = field.get("fill_rect")
            if fr:
                fr_rect = fitz.Rect(fr)
                shape2 = page.new_shape()
                shape2.draw_rect(fr_rect)
                shape2.finish(color=COLOR_GREEN, fill=COLOR_GREEN, fill_opacity=0.12, width=0.6)
                shape2.commit()
                draw_id_badge(page, fr_rect, f"T{idx}", COLOR_GREEN, fontsize=5, y_offset=0.5)

    render_doc.save(str(out_pdf))
    render_doc.close()
    print(f"  → {out_pdf}")

    if save_json:
        out_json = RESULT_DIR / f"tf_{stem}.json"
        json_data = {}
        for page_num, fields in all_text_fields.items():
            json_data[str(page_num)] = fields
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "fields_by_page": json_data}, f,
                       indent=2, ensure_ascii=False)
        print(f"  → {out_json}")

    doc.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Text field detection test")
    parser.add_argument("--batch", action="store_true", help="Run all test PDFs")
    parser.add_argument("--pdf", type=str, help="Filter PDFs by keyword")
    parser.add_argument("--json", action="store_true", help="Also output JSON")
    args = parser.parse_args()

    pdfs = existing_pdf_paths()
    if args.pdf:
        pdfs = [p for p in pdfs if args.pdf in p]
    elif not args.batch:
        pdfs = existing_pdf_paths()

    if not pdfs:
        print("No matching PDFs found")
        return

    print(f"=== Text Field Detection Test ({len(pdfs)} PDFs) ===\n")
    all_summaries = []
    for pdf_path in pdfs:
        print(f"[{_stem24(pdf_path)}]")
        s = run_one_pdf(pdf_path, save_json=args.json)
        all_summaries.append(s)
        print()

    grand_total = sum(s["total_text_fields"] for s in all_summaries)
    print(f"=== 总计: {grand_total} text fields across {len(pdfs)} PDFs ===")


if __name__ == "__main__":
    main()
