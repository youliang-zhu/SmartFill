from __future__ import annotations

from typing import Any, Dict, List

import fitz

from app.services.native.preprocess.types import RectTuple


class ExtractionMixin:
    """PDF 文字/矢量提取与表格网格构建。"""
    def extract_text_spans(self, page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
        spans: List[Dict[str, Any]] = []
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = self._normalize_text(span.get("text", ""))
                    if not text:
                        continue
                    bbox = self._rect_tuple(fitz.Rect(span.get("bbox")))
                    spans.append(
                        {
                            "text": text,
                            "bbox": bbox,
                            "font_name": span.get("font", ""),
                            "font_size": self._round(span.get("size", 0.0)),
                            "page_num": page_num,
                        }
                    )
        return spans

    def _extract_text_lines(self, page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
        lines_out: List[Dict[str, Any]] = []
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_spans = line.get("spans", [])
                if not line_spans:
                    continue
                texts = []
                bbox: RectTuple | None = None
                for span in line_spans:
                    t = self._normalize_text(span.get("text", ""))
                    if not t:
                        continue
                    texts.append(t)
                    sb = self._rect_tuple(fitz.Rect(span.get("bbox")))
                    bbox = sb if bbox is None else self._bbox_union(bbox, sb)
                if not texts or bbox is None:
                    continue
                lines_out.append(
                    {
                        "text": self._normalize_text(" ".join(texts)),
                        "bbox": bbox,
                        "page_num": page_num,
                    }
                )
        return lines_out

    def extract_drawings(self, page: fitz.Page, page_num: int) -> Dict[str, Any]:
        drawings = page.get_drawings()
        drawing_items: List[Dict[str, Any]] = []
        raw_lines_h: List[Dict[str, float]] = []
        raw_lines_v: List[Dict[str, float]] = []
        square_boxes: List[RectTuple] = []

        for d in drawings:
            d_rect = self._rect_tuple(d.get("rect", fitz.Rect(0, 0, 0, 0)))
            normalized_items = []

            for item in d.get("items", []):
                op = item[0]
                if op == "re":
                    rect: fitz.Rect = item[1]
                    bbox = self._rect_tuple(rect)
                    normalized_items.append({"op": "re", "rect": bbox})

                    w = rect.width
                    h = rect.height
                    if h <= self.LINE_THICKNESS_MAX and w >= self.MIN_LINE_LEN:
                        raw_lines_h.append(
                            {"x0": rect.x0, "x1": rect.x1, "y": (rect.y0 + rect.y1) / 2.0}
                        )
                    elif w <= self.LINE_THICKNESS_MAX and h >= self.MIN_LINE_LEN:
                        raw_lines_v.append(
                            {"x": (rect.x0 + rect.x1) / 2.0, "y0": rect.y0, "y1": rect.y1}
                        )

                    if 6.0 <= w <= 20.0 and 6.0 <= h <= 20.0 and abs(w - h) <= 2.0:
                        square_boxes.append(bbox)

                elif op == "l":
                    p1, p2 = item[1], item[2]
                    bbox = (
                        self._round(min(p1.x, p2.x)),
                        self._round(min(p1.y, p2.y)),
                        self._round(max(p1.x, p2.x)),
                        self._round(max(p1.y, p2.y)),
                    )
                    normalized_items.append({"op": "l", "bbox": bbox})

                    if abs(p1.y - p2.y) <= self.LINE_THICKNESS_MAX and abs(p1.x - p2.x) >= self.MIN_LINE_LEN:
                        raw_lines_h.append(
                            {"x0": min(p1.x, p2.x), "x1": max(p1.x, p2.x), "y": (p1.y + p2.y) / 2.0}
                        )
                    elif abs(p1.x - p2.x) <= self.LINE_THICKNESS_MAX and abs(p1.y - p2.y) >= self.MIN_LINE_LEN:
                        raw_lines_v.append(
                            {"x": (p1.x + p2.x) / 2.0, "y0": min(p1.y, p2.y), "y1": max(p1.y, p2.y)}
                        )

            drawing_items.append(
                {
                    "type": d.get("type", ""),
                    "rect": d_rect,
                    "items": normalized_items,
                    "items_count": len(normalized_items),
                    "fill": d.get("fill"),
                    "color": d.get("color"),
                    "width": self._safe_float(d.get("width"), 0.0),
                    "stroke_opacity": d.get("stroke_opacity"),
                    "fill_opacity": d.get("fill_opacity"),
                    "page_num": page_num,
                }
            )

        merged_h = self._merge_horizontal_lines(raw_lines_h)
        merged_v = self._merge_vertical_lines(raw_lines_v)
        dedup_boxes = self._dedup_boxes(square_boxes)

        return {
            "drawings": drawing_items,
            "horizontal_lines": merged_h,
            "vertical_lines": merged_v,
            "square_boxes": dedup_boxes,
        }

    def _merge_horizontal_lines(self, lines: List[Dict[str, float]]) -> List[Dict[str, float]]:
        if not lines:
            return []
        lines = sorted(lines, key=lambda x: (x["y"], x["x0"]))
        merged: List[Dict[str, float]] = []
        for ln in lines:
            if not merged:
                merged.append(dict(ln))
                continue
            last = merged[-1]
            y_close = abs(last["y"] - ln["y"]) <= self.COORD_MERGE_TOL
            x_overlap = ln["x0"] <= last["x1"] + self.COORD_MERGE_TOL
            if y_close and x_overlap:
                last["x0"] = min(last["x0"], ln["x0"])
                last["x1"] = max(last["x1"], ln["x1"])
                last["y"] = (last["y"] + ln["y"]) / 2.0
            else:
                merged.append(dict(ln))
        return merged

    def _merge_vertical_lines(self, lines: List[Dict[str, float]]) -> List[Dict[str, float]]:
        if not lines:
            return []
        lines = sorted(lines, key=lambda x: (x["x"], x["y0"]))
        merged: List[Dict[str, float]] = []
        for ln in lines:
            if not merged:
                merged.append(dict(ln))
                continue
            last = merged[-1]
            x_close = abs(last["x"] - ln["x"]) <= self.COORD_MERGE_TOL
            y_overlap = ln["y0"] <= last["y1"] + self.COORD_MERGE_TOL
            if x_close and y_overlap:
                last["y0"] = min(last["y0"], ln["y0"])
                last["y1"] = max(last["y1"], ln["y1"])
                last["x"] = (last["x"] + ln["x"]) / 2.0
            else:
                merged.append(dict(ln))
        return merged

    def _dedup_boxes(self, boxes: List[RectTuple]) -> List[RectTuple]:
        dedup: List[RectTuple] = []
        for b in boxes:
            cx, cy = self._bbox_center(b)
            exists = False
            for e in dedup:
                ex, ey = self._bbox_center(e)
                if abs(cx - ex) <= 2.0 and abs(cy - ey) <= 2.0:
                    exists = True
                    break
            if not exists:
                dedup.append(b)
        return dedup

    # -------------------- 引擎 1 --------------------

    def _build_table_grids(self, drawing_data: Dict[str, Any], page_num: int) -> List[Dict[str, Any]]:
        h_lines = drawing_data.get("horizontal_lines", [])
        v_lines = drawing_data.get("vertical_lines", [])
        if len(h_lines) < 2 or len(v_lines) < 2:
            return []

        line_nodes: List[Dict[str, Any]] = []
        for h in h_lines:
            bbox = (h["x0"], h["y"] - 0.5, h["x1"], h["y"] + 0.5)
            line_nodes.append({"kind": "h", "bbox": bbox, "line": h})
        for v in v_lines:
            bbox = (v["x"] - 0.5, v["y0"], v["x"] + 0.5, v["y1"])
            line_nodes.append({"kind": "v", "bbox": bbox, "line": v})

        parent = list(range(len(line_nodes)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(line_nodes)):
            for j in range(i + 1, len(line_nodes)):
                if self._intersects(line_nodes[i]["bbox"], line_nodes[j]["bbox"], gap=2.0):
                    union(i, j)

        groups: Dict[int, List[Dict[str, Any]]] = {}
        for i, node in enumerate(line_nodes):
            groups.setdefault(find(i), []).append(node)

        tables: List[Dict[str, Any]] = []
        for group in groups.values():
            gh = [n for n in group if n["kind"] == "h"]
            gv = [n for n in group if n["kind"] == "v"]
            if len(gh) < 2 or len(gv) < 2:
                continue

            # Aggressive mode: only use original vector lines as table boundaries.
            # Do not synthesize extra split lines from segment endpoints.
            xs = [float(v["line"]["x"]) for v in gv]
            ys = [float(h["line"]["y"]) for h in gh]

            x_grid = self._cluster_values(xs, tol=self.COORD_MERGE_TOL)
            y_grid = self._cluster_values(ys, tol=self.COORD_MERGE_TOL)
            if len(x_grid) < 2 or len(y_grid) < 2:
                continue

            bbox = (
                self._round(min(x_grid)),
                self._round(min(y_grid)),
                self._round(max(x_grid)),
                self._round(max(y_grid)),
            )
            if self._bbox_width(bbox) < 40 or self._bbox_height(bbox) < 20:
                continue

            table_h = max(1.0, self._bbox_height(bbox))
            hard_v_boundaries: List[bool] = []
            for x in x_grid:
                segments: List[Tuple[float, float]] = []
                for v in gv:
                    vx = float(v["line"]["x"])
                    if abs(vx - x) > max(1.5, self.COORD_MERGE_TOL):
                        continue
                    y0 = max(float(v["line"]["y0"]), bbox[1])
                    y1 = min(float(v["line"]["y1"]), bbox[3])
                    if y1 > y0:
                        segments.append((y0, y1))
                if not segments:
                    hard_v_boundaries.append(False)
                    continue
                segments.sort(key=lambda s: s[0])
                merged_len = 0.0
                cur0, cur1 = segments[0]
                for s0, s1 in segments[1:]:
                    if s0 <= cur1 + 0.8:
                        cur1 = max(cur1, s1)
                    else:
                        merged_len += cur1 - cur0
                        cur0, cur1 = s0, s1
                merged_len += cur1 - cur0
                coverage = merged_len / table_h
                hard_v_boundaries.append(coverage >= 0.68)
            if hard_v_boundaries:
                hard_v_boundaries[0] = True
                hard_v_boundaries[-1] = True

            cells = []
            for r in range(len(y_grid) - 1):
                for c in range(len(x_grid) - 1):
                    cb = (
                        self._round(x_grid[c]),
                        self._round(y_grid[r]),
                        self._round(x_grid[c + 1]),
                        self._round(y_grid[r + 1]),
                    )
                    if self._bbox_width(cb) < 3 or self._bbox_height(cb) < 3:
                        continue
                    cells.append({"row": r, "col": c, "bbox": cb})

            if len(cells) < 2:
                continue

            tables.append(
                {
                    "page_num": page_num,
                    "bbox": bbox,
                    "row_count": max(0, len(y_grid) - 1),
                    "col_count": max(0, len(x_grid) - 1),
                    "grid_x": [self._round(x) for x in x_grid],
                    "grid_y": [self._round(y) for y in y_grid],
                    "hard_v_boundaries": hard_v_boundaries,
                    "orig_h_lines": [
                        {
                            "x0": self._round(float(h["line"]["x0"])),
                            "x1": self._round(float(h["line"]["x1"])),
                            "y": self._round(float(h["line"]["y"])),
                        }
                        for h in gh
                    ],
                    "orig_v_lines": [
                        {
                            "x": self._round(float(v["line"]["x"])),
                            "y0": self._round(float(v["line"]["y0"])),
                            "y1": self._round(float(v["line"]["y1"])),
                        }
                        for v in gv
                    ],
                    "cells": cells,
                }
            )

        tables.sort(key=lambda t: (t["bbox"][1], t["bbox"][0]))
        for idx, table in enumerate(tables, start=1):
            table["table_id"] = idx
        return tables

    def _get_cell_text_lines(self, cell_bbox: RectTuple, text_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        lines = []
        for ln in text_lines:
            if self._intersects(cell_bbox, ln["bbox"], gap=-1.0):
                lines.append(ln)
        lines.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
        return lines

