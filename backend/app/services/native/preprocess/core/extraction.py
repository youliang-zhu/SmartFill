from __future__ import annotations

import re
from typing import Any, Dict, List

import fitz

from app.services.native.preprocess.core.types import RectTuple


class ExtractionMixin:
    """PDF 文字/矢量提取与表格网格构建。"""

    _FIELD_PREFIX_RE = re.compile(r"^(?:\(?[A-Za-z0-9]{1,3}[.)]|[0-9]{1,2}[A-Za-z]?\.)\s*\S")

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
                font_sizes: list[float] = []
                char_y_tops: list[float] = []
                char_y_bottoms: list[float] = []
                spans_meta: list[Dict[str, Any]] = []
                for span in line_spans:
                    t = self._normalize_text(span.get("text", ""))
                    if not t:
                        continue
                    texts.append(t)
                    sb = self._rect_tuple(fitz.Rect(span.get("bbox")))
                    bbox = sb if bbox is None else self._bbox_union(bbox, sb)
                    spans_meta.append({"text": t, "bbox": sb})
                    font_sizes.append(float(span.get("size", 0.0)))
                    char_y_tops.append(float(sb[1]))
                    origin = span.get("origin")
                    if origin is not None:
                        char_y_bottoms.append(float(origin[1]))
                    else:
                        char_y_bottoms.append(float(sb[3]))
                if not texts or bbox is None:
                    continue
                avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 0.0
                lines_out.append(
                    {
                        "text": self._normalize_text(" ".join(texts)),
                        "bbox": bbox,
                        "font_size": self._round(avg_font_size),
                        "page_num": page_num,
                        "char_y_top": min(char_y_tops),
                        "char_y_bottom": max(char_y_bottoms),
                        "spans_meta": spans_meta,
                    }
                )
        return lines_out

    def _extract_dark_vertical_edges(self, drawings: List[Dict[str, Any]]) -> List[Dict[str, float]]:
        edges: List[Dict[str, float]] = []
        for drawing in drawings:
            fill = drawing.get("fill")
            rect = drawing.get("rect")
            if fill is None or rect is None:
                continue
            if not (isinstance(fill, (list, tuple)) and len(fill) >= 3):
                continue
            r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
            if r + g + b > 1.5:
                continue
            x0, y0, x1, y1 = map(float, rect)
            width = x1 - x0
            height = y1 - y0
            if width > max(4.0, self.LINE_THICKNESS_MAX * 4.0):
                continue
            if height < self.MIN_LINE_LEN:
                continue
            edges.append({"x": (x0 + x1) / 2.0, "y0": y0, "y1": y1})
        return self._merge_vertical_lines(edges)

    def _iter_vertical_separators(self, drawing_data: Dict[str, Any] | None = None) -> List[Dict[str, float]]:
        drawing_data = drawing_data or {}
        base = [dict(v) for v in drawing_data.get("vertical_lines", [])]
        dark = self._extract_dark_vertical_edges(drawing_data.get("drawings", []))
        return self._merge_vertical_lines(base + dark)

    def _looks_like_field_prefix(self, text: str) -> bool:
        return bool(self._FIELD_PREFIX_RE.match(text.strip()))

    def _has_vertical_separator_between(
        self,
        left_bbox: RectTuple,
        right_bbox: RectTuple,
        drawing_data: Dict[str, Any] | None = None,
    ) -> bool:
        if drawing_data is None:
            return False
        gap_left = float(left_bbox[2])
        gap_right = float(right_bbox[0])
        if gap_right <= gap_left:
            return False
        band_y0 = max(float(left_bbox[1]), float(right_bbox[1])) - 1.0
        band_y1 = min(float(left_bbox[3]), float(right_bbox[3])) + 1.0
        if band_y1 <= band_y0:
            return False
        for sep in self._iter_vertical_separators(drawing_data):
            sx = float(sep["x"])
            if not (gap_left <= sx <= gap_right):
                continue
            if float(sep["y0"]) <= band_y1 and float(sep["y1"]) >= band_y0:
                return True
        return False

    def _build_line_from_spans(self, base_line: Dict[str, Any], spans: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not spans:
            return None
        texts = [sp["text"] for sp in spans if sp.get("text")]
        if not texts:
            return None
        bbox = spans[0]["bbox"]
        for sp in spans[1:]:
            bbox = self._bbox_union(bbox, sp["bbox"])
        return {
            "text": self._normalize_text(" ".join(texts)),
            "bbox": bbox,
            "font_size": float(base_line.get("font_size", 0.0)),
            "page_num": base_line.get("page_num", 0),
            "char_y_top": float(base_line.get("char_y_top", bbox[1])),
            "char_y_bottom": float(base_line.get("char_y_bottom", bbox[3])),
            "spans_meta": spans,
        }

    def _split_lines_by_vertical_separators(
        self,
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        if not text_lines:
            return []
        separators = self._iter_vertical_separators(drawing_data)
        if not separators:
            return text_lines

        split_lines: List[Dict[str, Any]] = []
        for line in text_lines:
            spans = [sp for sp in line.get("spans_meta", []) if sp.get("text")]
            if len(spans) < 2:
                split_lines.append(line)
                continue
            candidates = [
                sep for sep in separators
                if float(line["bbox"][0]) + 1.0 < float(sep["x"]) < float(line["bbox"][2]) - 1.0
                and float(sep["y0"]) <= float(line["bbox"][3]) + 1.0
                and float(sep["y1"]) >= float(line["bbox"][1]) - 1.0
            ]
            if not candidates:
                split_lines.append(line)
                continue

            segments = [line]
            for sep in sorted(candidates, key=lambda item: float(item["x"])):
                next_segments: List[Dict[str, Any]] = []
                sx = float(sep["x"])
                for segment in segments:
                    seg_spans = [sp for sp in segment.get("spans_meta", []) if sp.get("text")]
                    if len(seg_spans) < 2:
                        next_segments.append(segment)
                        continue
                    if not (float(segment["bbox"][0]) + 1.0 < sx < float(segment["bbox"][2]) - 1.0):
                        next_segments.append(segment)
                        continue
                    left_spans = []
                    right_spans = []
                    for sp in seg_spans:
                        sb = sp["bbox"]
                        scx = (float(sb[0]) + float(sb[2])) / 2.0
                        if scx < sx:
                            left_spans.append(sp)
                        elif scx > sx:
                            right_spans.append(sp)
                    left_line = self._build_line_from_spans(segment, left_spans)
                    right_line = self._build_line_from_spans(segment, right_spans)
                    if (
                        left_line is None
                        or right_line is None
                        or not self._looks_like_field_prefix(left_line["text"])
                        or not self._looks_like_field_prefix(right_line["text"])
                    ):
                        next_segments.append(segment)
                        continue
                    next_segments.extend([left_line, right_line])
                segments = next_segments
            split_lines.extend(segments)

        return split_lines

    def _merge_continuation_lines(
        self,
        text_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any] | None = None,
        gap_ratio: float = 0.1,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Union-Find pairwise 合并续行。

        对每对行 (i, j) 判断：
        1. 垂直间距（两行 y 边界的最小间距）< 两行字体大小均值 × gap_ratio
        2. x 轴中心点在对方 x 范围内（任一方向满足即可）
        3. 两行都不含 checkbox 字符
        4. 两行之间不存在跨越双方 x 范围的矢量水平边界线

        满足则建边，最终按 Union-Find 连通分量合并。
        返回 (merged_lines, merge_log)。
        """
        if not text_lines:
            return [], []

        n = len(text_lines)
        h_lines: List[Dict[str, float]] = (drawing_data or {}).get("horizontal_lines", [])

        # 构建填充色块查找结构（逆绘制顺序 = 最顶层优先）
        _WHITE = (1.0, 1.0, 1.0)
        _fill_rects: List[tuple] = []  # (x0, y0, x1, y1, (r,g,b))
        for _d in reversed((drawing_data or {}).get("drawings", [])):
            _fill = _d.get("fill")
            if _fill is None:
                continue
            if not (isinstance(_fill, (list, tuple)) and len(_fill) >= 3):
                continue
            _r = _d.get("rect")
            if _r is None:
                continue
            _fill_rects.append((
                float(_r[0]), float(_r[1]), float(_r[2]), float(_r[3]),
                (float(_fill[0]), float(_fill[1]), float(_fill[2])),
            ))

        def _get_bg_color(bbox: tuple) -> tuple:
            """返回覆盖 bbox 中心点的最顶层填充色，无填充则返回白色。"""
            cx = (float(bbox[0]) + float(bbox[2])) / 2.0
            cy = (float(bbox[1]) + float(bbox[3])) / 2.0
            for rx0, ry0, rx1, ry1, color in _fill_rects:
                if rx0 <= cx <= rx1 and ry0 <= cy <= ry1:
                    return color
            return _WHITE

        checkbox_tokens = {"☐", "☑", "☒", "□", "■", "✓", "✔", "\uf06f", "\uf0fe"}

        def _has_checkbox(text: str) -> bool:
            if any(ch in checkbox_tokens for ch in text):
                return True
            return any(0xF000 <= ord(ch) <= 0xF0FF for ch in text)

        def _has_border_between(above_line: Dict[str, Any], below_line: Dict[str, Any]) -> bool:
            """检查两行之间是否有水平矢量边界线。
            以上方行的字体基线（char_y_bottom）为上边界，
            下方行的字体顶部（char_y_top）为下边界，
            避免 bbox padding 导致的漏检。
            """
            above_bbox = above_line["bbox"]
            below_bbox = below_line["bbox"]
            y_top = float(above_line.get("char_y_bottom", above_bbox[3]))
            y_bot = float(below_line.get("char_y_top", below_bbox[1]))
            if y_top >= y_bot:
                return False
            x_left = min(float(above_bbox[0]), float(below_bbox[0]))
            x_right = max(float(above_bbox[2]), float(below_bbox[2]))
            for hl in h_lines:
                hy = float(hl.get("y", 0.0))
                if y_top <= hy <= y_bot:
                    hx0 = float(hl.get("x0", 0.0))
                    hx1 = float(hl.get("x1", 0.0))
                    if hx0 <= x_right and hx1 >= x_left:
                        return True
            return False

        # 预计算
        bboxes = [ln["bbox"] for ln in text_lines]
        font_sizes = [float(ln.get("font_size", 0.0)) for ln in text_lines]
        is_cb = [_has_checkbox(ln["text"]) for ln in text_lines]

        # Union-Find
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # 记录每对合并的 gap 信息
        edge_gaps: List[Dict[str, Any]] = []

        # pairwise 扫描
        for i in range(n):
            if is_cb[i]:
                continue
            bi = bboxes[i]
            i_x0, i_y0, i_x1, i_y1 = float(bi[0]), float(bi[1]), float(bi[2]), float(bi[3])
            i_cx = (i_x0 + i_x1) / 2.0
            fs_i = font_sizes[i]

            for j in range(i + 1, n):
                if is_cb[j]:
                    continue
                bj = bboxes[j]
                j_x0, j_y0, j_x1, j_y1 = float(bj[0]), float(bj[1]), float(bj[2]), float(bj[3])

                # 垂直间距：取两行 y 区间的非重叠部分（重叠时为 0）
                gap = max(0.0, max(j_y0 - i_y1, i_y0 - j_y1))
                avg_fs = (fs_i + font_sizes[j]) / 2.0
                if avg_fs <= 0:
                    continue
                if gap >= avg_fs * gap_ratio:
                    continue

                # x 轴中心点在对方 x 范围内（任一方向）
                j_cx = (j_x0 + j_x1) / 2.0
                cx_i_in_j = j_x0 <= i_cx <= j_x1
                cx_j_in_i = i_x0 <= j_cx <= i_x1
                if not (cx_i_in_j or cx_j_in_i):
                    continue

                # 矢量边界检查：两行之间有水平边界线则拒绝合并
                above_line = text_lines[i] if i_y0 <= j_y0 else text_lines[j]
                below_line = text_lines[j] if i_y0 <= j_y0 else text_lines[i]
                if _has_border_between(above_line, below_line):
                    continue

                # 背景色检查：两行背景色不同则拒绝合并（处于不同表格单元格）
                if _get_bg_color(bi) != _get_bg_color(bj):
                    continue

                # 建边
                union(i, j)
                gap_pct = (gap / avg_fs) * 100.0
                edge_gaps.append({
                    "i": i, "j": j,
                    "gap": round(gap, 2),
                    "avg_font_size": round(avg_fs, 2),
                    "gap_pct": round(gap_pct, 1),
                })

        # 按连通分量分组
        groups: Dict[int, List[int]] = {}
        for i in range(n):
            root = find(i)
            groups.setdefault(root, []).append(i)

        merged: List[Dict[str, Any]] = []
        merge_log: List[Dict[str, Any]] = []

        for members in sorted(groups.values(), key=lambda m: min(m)):
            # 组内按 y 排序
            members.sort(key=lambda idx: (float(bboxes[idx][1]), float(bboxes[idx][0])))
            texts = [text_lines[idx]["text"] for idx in members]
            bbox = bboxes[members[0]]
            for idx in members[1:]:
                bbox = self._bbox_union(bbox, bboxes[idx])
            avg_fs = sum(font_sizes[idx] for idx in members) / len(members)
            merged_text = self._normalize_text(" ".join(texts))
            merged.append({
                "text": merged_text,
                "bbox": bbox,
                "font_size": round(avg_fs, 2),
                "page_num": text_lines[members[0]].get("page_num", 0),
            })

            if len(members) > 1:
                # 收集组内 edge gap 信息
                member_set = set(members)
                group_gaps = [
                    eg for eg in edge_gaps
                    if eg["i"] in member_set and eg["j"] in member_set
                ]
                merge_log.append({
                    "from_texts": texts,
                    "merged_text": merged_text,
                    "line_count": len(members),
                    "gaps": group_gaps,
                })

        return merged, merge_log

    def _merge_left_right(
        self,
        merged_lines: List[Dict[str, Any]],
        drawing_data: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """Phase 1.6：左右融合。

        如果某行以字母或数字开头且总长度 ≤ 10 字符，
        则将其与水平方向右侧最近的同行 label 合并。
        """
        if not merged_lines:
            return merged_lines

        _MAX_LEN = 10
        n = len(merged_lines)
        consumed = [False] * n
        result: List[Dict[str, Any]] = []

        for i in range(n):
            if consumed[i]:
                continue
            text_i = merged_lines[i]["text"].strip()
            # 判断是否为短小左侧片段：以字母/数字开头，长度 ≤ 10
            if (
                text_i
                and text_i[0].isalnum()
                and len(text_i) <= _MAX_LEN
            ):
                bi = merged_lines[i]["bbox"]
                i_cy = (float(bi[1]) + float(bi[3])) / 2.0
                i_h = float(bi[3]) - float(bi[1])
                # 找右侧最近的、y 有重叠的行
                best_j: int | None = None
                best_gap = float("inf")
                for j in range(n):
                    if j == i or consumed[j]:
                        continue
                    bj = merged_lines[j]["bbox"]
                    # j 的左边缘必须在 i 的左边缘右侧（允许部分水平重叠）
                    if float(bj[0]) <= float(bi[0]):
                        continue
                    # y 重叠 > 0
                    y_overlap = min(float(bi[3]), float(bj[3])) - max(float(bi[1]), float(bj[1]))
                    if y_overlap <= 0:
                        continue
                    if self._has_vertical_separator_between(bi, bj, drawing_data=drawing_data):
                        continue
                    gap = float(bj[0]) - float(bi[0])
                    if gap < best_gap:
                        best_gap = gap
                        best_j = j
                if best_j is not None:
                    bj = merged_lines[best_j]["bbox"]
                    new_text = self._normalize_text(text_i + " " + merged_lines[best_j]["text"].strip())
                    new_bbox = self._bbox_union(bi, bj)
                    fs_i = float(merged_lines[i].get("font_size", 0))
                    fs_j = float(merged_lines[best_j].get("font_size", 0))
                    new_fs = round((fs_i + fs_j) / 2.0, 2)
                    consumed[best_j] = True
                    result.append({
                        "text": new_text,
                        "bbox": new_bbox,
                        "font_size": new_fs,
                        "page_num": merged_lines[i].get("page_num", 0),
                    })
                    continue
            result.append(merged_lines[i])

        return result

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
