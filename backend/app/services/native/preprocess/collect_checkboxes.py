"""Phase 2A — Checkbox 字段收集器。

从 Phase 1 数据中识别 checkbox 组：
1. 收集所有 checkbox 位置（square_boxes + 字形符号）
2. 按空间邻近度分组（同行或相邻行）
3. 为每个 box 查找右侧选项文字
4. 确定 checkbox 所在的"包含单元格"（h/v_line 围成的矩形），
   在单元格内或水平带状区域内收集所有 label：
   - 有封闭单元格：单元格内无 y 限制，找不到则沿同行向外找
   - 无封闭单元格：水平方向（同行）找所有 label；没有则向上到第一条 h_line 内取最近行
5. 多 label → 最近的是 question，其余是 additional_text（复用 h_line 作为 fill_rect）
6. 标记消耗的资源
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.native.preprocess.types import RectTuple


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_CHECKBOX_GLYPHS = {"☐", "☑", "☒", "□", "■", "✓", "✔", "\uf06f", "\uf0fe"}

# 选项文字搜索参数
_OPT_TEXT_MAX_GAP_X = 120.0   # 选项文字 x0 距 box x1 最大距离
_OPT_TEXT_Y_TOL = 10.0         # 选项文字 y 中心与 box y 中心最大偏差

# 分组参数
_GROUP_Y_TOL = 8.0             # 同组 checkbox 的 y 中心最大偏差
_GROUP_GAP_X = 300.0           # 同行 checkbox 间的 x 最大间距

_HORIZ_LABEL_Y_TOL = 10.0       # _merge_same_row 同行判断的 y 容差
_MAX_CELL_HEIGHT = 80.0          # 封闭单元格最大高度（超过视为页面区域而非表单单元格）
_SHADED_BAR_MIN_WIDTH = 200.0    # 最小宽度才视为"分节标题栏"


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _bbox_center_y(bbox: RectTuple) -> float:
    return (bbox[1] + bbox[3]) / 2.0


def _bbox_center_x(bbox: RectTuple) -> float:
    return (bbox[0] + bbox[2]) / 2.0


def _bbox_union(a: RectTuple, b: RectTuple) -> RectTuple:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _is_checkbox_char(ch: str) -> bool:
    if ch in _CHECKBOX_GLYPHS:
        return True
    return 0xF000 <= ord(ch) <= 0xF0FF


def _is_checkbox_text(text: str) -> bool:
    """text 只含 checkbox 字形（可能有前后空格）"""
    stripped = text.strip()
    if not stripped:
        return False
    return all(_is_checkbox_char(ch) for ch in stripped)


def _starts_with_checkbox(text: str) -> bool:
    """text 以 checkbox 字形字符开头（例如 '\uf071 Yes' 属于选项文字，不是 label）"""
    stripped = text.strip()
    if not stripped:
        return False
    return _is_checkbox_char(stripped[0])


def _detect_table_zones(
    tables: List[Dict[str, Any]],
    all_v_lines: List[Dict[str, float]] | None = None,
) -> List[Tuple[float, float]]:
    """从 table_structures 中检测表格区域的 y 范围。

    算法：
    1. 表格必须含 2×2 的格子块（≥2行 × ≥2列）才算真表格
    2. 从种子行出发向上下蔓延：每到新行检查该行是否有 ≥2 列格子，
       不足则碰到"大海"，停止
    3. 用 orig_v_lines 扩展边界
    4. 用页面所有 vertical_lines 迭代扩展：
       若任意竖线与当前 zone 有交集，则将 zone 对齐到该竖线的末端，
       重复直到不再有新扩展

    返回去重、不重叠的 y 范围列表。
    """
    zones: List[Tuple[float, float]] = []

    for table in tables:
        grid_x = table.get("grid_x", [])
        grid_y = table.get("grid_y", [])
        n_cols = len(grid_x) - 1
        n_rows = len(grid_y) - 1
        if n_cols < 2 or n_rows < 2:
            continue  # 不满足 2×2 最低要求

        # 行高均匀性检查：数据表格行高比较一致，表单排版网格行高差异极大
        row_heights = [grid_y[i + 1] - grid_y[i] for i in range(n_rows)
                       if grid_y[i + 1] - grid_y[i] >= 5.0]
        if len(row_heights) < 2:
            continue
        if max(row_heights) / min(row_heights) > 3.5:
            continue

        # 构建 row→col_count 映射（基于 cells）
        row_cols: Dict[int, int] = {}
        for cell in table.get("cells", []):
            r = cell["row"]
            row_cols[r] = row_cols.get(r, 0) + 1

        # 找种子行：任何连续两行都有 ≥2 列
        seed_row = -1
        for r in range(n_rows - 1):
            if row_cols.get(r, 0) >= 2 and row_cols.get(r + 1, 0) >= 2:
                seed_row = r
                break
        if seed_row < 0:
            continue

        # 向上蔓延
        top_row = seed_row
        while top_row > 0 and row_cols.get(top_row - 1, 0) >= 2:
            top_row -= 1

        # 向下蔓延
        bot_row = seed_row + 1  # 种子包含两行
        while bot_row < n_rows - 1 and row_cols.get(bot_row + 1, 0) >= 2:
            bot_row += 1

        y_top = grid_y[top_row]
        y_bot = grid_y[bot_row + 1]

        # 用 orig_v_lines 的 y 范围扩展边界
        for vl in table.get("orig_v_lines", []):
            y_top = min(y_top, vl["y0"])
            y_bot = max(y_bot, vl["y1"])

        # 用页面所有 vertical_lines 迭代扩展：
        # 排除最左/最右 x 的竖线（页面边框），只用中间的分隔线。
        # 如果某竖线与当前 zone 有交集（允许小间隙，水平线穿越处会断开竖线），
        # 则 zone 边界对齐到该竖线的末端；重复直到稳定
        _VLINE_GAP_TOL = 5.0  # 容许水平线切断竖线产生的间隙
        if all_v_lines:
            all_xs = sorted(set(vl["x"] for vl in all_v_lines))
            if len(all_xs) > 2:
                border_min, border_max = all_xs[0], all_xs[-1]
                inner_v = [vl for vl in all_v_lines
                           if abs(vl["x"] - border_min) > 1.0
                           and abs(vl["x"] - border_max) > 1.0]
            else:
                inner_v = []
            changed = True
            while changed:
                changed = False
                for vl in inner_v:
                    vl_y0, vl_y1 = vl["y0"], vl["y1"]
                    # 竖线与 zone 有交集（含容差）
                    if vl_y0 <= y_bot + _VLINE_GAP_TOL and vl_y1 >= y_top - _VLINE_GAP_TOL:
                        if vl_y0 < y_top:
                            y_top = vl_y0
                            changed = True
                        if vl_y1 > y_bot:
                            y_bot = vl_y1
                            changed = True

        zones.append((y_top, y_bot))

    # 合并重叠区间
    if not zones:
        return []
    zones.sort()
    merged: List[Tuple[float, float]] = [zones[0]]
    for yt, yb in zones[1:]:
        if yt <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], yb))
        else:
            merged.append((yt, yb))
    return merged


def _in_table_zone(cy: float, table_zones: List[Tuple[float, float]]) -> bool:
    """检查中心点 y 是否落在某个表格区域内。"""
    for y_top, y_bot in table_zones:
        if y_top <= cy <= y_bot:
            return True
    return False


def _bbox_inside_any_table(bbox: RectTuple, tables: List[Dict[str, Any]],
                           table_zones: List[Tuple[float, float]]) -> bool:
    """检查 bbox 中心点 y 是否在表格区域内。"""
    return _in_table_zone(_bbox_center_y(bbox), table_zones)


def _extract_shaded_bars(
    drawings: List[Dict[str, Any]],
) -> List[RectTuple]:
    """从 drawings 中提取深色背景填充条（节标题栏）。

    条件：非白色填充、宽度 > _SHADED_BAR_MIN_WIDTH、高度 5~40pt。
    返回按 y 排序的 (x0, y0, x1, y1) 列表。
    """
    bars: List[RectTuple] = []
    for d in drawings:
        fill = d.get("fill")
        if fill is None:
            continue
        # 非白色（r+g+b < 2.5 表示较深色）
        if isinstance(fill, (list, tuple)) and len(fill) >= 3:
            if sum(float(c) for c in fill[:3]) > 2.5:
                continue
        else:
            continue
        rect = d.get("rect")
        if rect is None:
            continue
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            x0, y0, x1, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
        else:
            continue
        w, h = x1 - x0, y1 - y0
        if w >= _SHADED_BAR_MIN_WIDTH and 5 <= h <= 40:
            bars.append((x0, y0, x1, y1))
    # 去重（同位置可能有两层矩形）
    unique: List[RectTuple] = []
    for b in sorted(bars, key=lambda r: r[1]):
        if not unique or abs(b[1] - unique[-1][1]) > 3:
            unique.append(b)
    return unique


def _shaded_bar_between_y(
    y_top: float,
    y_bot: float,
    x_ref: float,
    shaded_bars: List[RectTuple],
) -> Optional[float]:
    """检查 y_top 到 y_bot 之间是否有 shaded_bar 横穿 x_ref。

    返回最靠近 y_bot 的 bar 底边 y（作为向上搜索的边界），或 None。
    """
    best: Optional[float] = None
    for bar in shaded_bars:
        bx0, by0, bx1, by1 = bar
        if by0 >= y_top and by1 <= y_bot and bx0 - 5 <= x_ref <= bx1 + 5:
            if best is None or by1 > best:
                best = by1
    return best


def _v_line_blocks(
    label_bbox: RectTuple,
    group_bbox: RectTuple,
    v_lines: List[Dict[str, float]],
) -> bool:
    """检查 label_bbox 和 group_bbox 之间是否有垂直线横截（阻断 label 归属）。

    仅检查 x 方向上介于两者之间的竖线，且竖线的 y 范围覆盖两者的 y 中心。
    """
    # 确定中间的 x 区间
    x_left = min(label_bbox[2], group_bbox[0])
    x_right = max(label_bbox[2], group_bbox[0])
    if x_left >= x_right:
        return False  # 两者 x 重叠，不存在"之间"

    y_ref = (_bbox_center_y(label_bbox) + _bbox_center_y(group_bbox)) / 2.0

    for vl in v_lines:
        vx = float(vl.get("x", 0.0))
        vy0 = float(vl.get("y0", 0.0))
        vy1 = float(vl.get("y1", 0.0))
        if x_left + 2 <= vx <= x_right - 2 and vy0 <= y_ref <= vy1:
            return True
    return False


def _find_enclosing_cell(
    group_bbox: RectTuple,
    h_lines: List[Dict[str, float]],
    v_lines: List[Dict[str, float]],
) -> Optional[RectTuple]:
    """查找包含 group_bbox 中心的 h/v_line 封闭单元格。

    返回 (x0, y0, x1, y1) 的单元格 bbox，或 None（无封闭单元格）。
    """
    cx = _bbox_center_x(group_bbox)
    cy = _bbox_center_y(group_bbox)

    # 找上方最近的 h_line（其 x 范围覆盖 cx）
    top_y: Optional[float] = None
    for hl in h_lines:
        hy = float(hl.get("y", 0.0))
        hx0 = float(hl.get("x0", 0.0))
        hx1 = float(hl.get("x1", 0.0))
        if hy <= cy and hx0 - 2 <= cx <= hx1 + 2:
            if top_y is None or hy > top_y:
                top_y = hy

    # 找下方最近的 h_line
    bot_y: Optional[float] = None
    for hl in h_lines:
        hy = float(hl.get("y", 0.0))
        hx0 = float(hl.get("x0", 0.0))
        hx1 = float(hl.get("x1", 0.0))
        if hy >= cy and hx0 - 2 <= cx <= hx1 + 2:
            if bot_y is None or hy < bot_y:
                bot_y = hy

    if top_y is None or bot_y is None or top_y >= bot_y:
        return None

    # 找左侧最近的 v_line（其 y 范围覆盖 top_y 到 bot_y 的中点 cy）
    left_x: Optional[float] = None
    for vl in v_lines:
        vx = float(vl.get("x", 0.0))
        vy0 = float(vl.get("y0", 0.0))
        vy1 = float(vl.get("y1", 0.0))
        if vx <= cx and vy0 - 2 <= cy <= vy1 + 2:
            if left_x is None or vx > left_x:
                left_x = vx

    # 找右侧最近的 v_line
    right_x: Optional[float] = None
    for vl in v_lines:
        vx = float(vl.get("x", 0.0))
        vy0 = float(vl.get("y0", 0.0))
        vy1 = float(vl.get("y1", 0.0))
        if vx >= cx and vy0 - 2 <= cy <= vy1 + 2:
            if right_x is None or vx < right_x:
                right_x = vx

    if left_x is None or right_x is None or left_x >= right_x:
        return None

    return (left_x, top_y, right_x, bot_y)


# ---------------------------------------------------------------------------
# 步骤 1：收集所有 checkbox 位置
# ---------------------------------------------------------------------------
def _collect_checkbox_positions(
    square_boxes: List[RectTuple],
    merged_lines: List[Dict[str, Any]],
    text_spans: List[Dict[str, Any]],
    table_zones: List[Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """收集所有 checkbox 位置，来源：square_boxes + 字形符号。"""
    positions: List[Dict[str, Any]] = []

    for box in square_boxes:
        if not _bbox_inside_any_table(box, [], table_zones):
            positions.append({"bbox": box, "source": "square_box"})

    for span in text_spans:
        text = span.get("text", "").strip()
        if not text or not _is_checkbox_text(text):
            continue
        sbbox = span.get("bbox")
        if sbbox is None:
            continue
        bbox = (float(sbbox[0]), float(sbbox[1]), float(sbbox[2]), float(sbbox[3]))
        if _bbox_inside_any_table(bbox, [], table_zones):
            continue
        cx, cy = _bbox_center_x(bbox), _bbox_center_y(bbox)
        dup = any(
            abs(cx - _bbox_center_x(p["bbox"])) <= 3.0 and
            abs(cy - _bbox_center_y(p["bbox"])) <= 3.0
            for p in positions
        )
        if not dup:
            positions.append({"bbox": bbox, "source": "glyph"})

    positions.sort(key=lambda p: (_bbox_center_y(p["bbox"]), p["bbox"][0]))
    return positions


# ---------------------------------------------------------------------------
# 步骤 2：分组
# ---------------------------------------------------------------------------
def _group_checkboxes(
    positions: List[Dict[str, Any]],
    h_lines: List[Dict[str, float]],
) -> List[List[Dict[str, Any]]]:
    """把同行 checkbox 按空间邻近度分组。"""
    if not positions:
        return []

    parent = list(range(len(positions)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    def _h_line_between(a: RectTuple, b: RectTuple) -> bool:
        y_top = min(a[3], b[3])
        y_bot = max(a[1], b[1])
        if y_top >= y_bot:
            return False
        x_left = min(a[0], b[0])
        x_right = max(a[2], b[2])
        for hl in h_lines:
            hy = float(hl.get("y", 0.0))
            if y_top <= hy <= y_bot:
                hx0 = float(hl.get("x0", 0.0))
                hx1 = float(hl.get("x1", 0.0))
                if hx0 <= x_left + 5 and hx1 >= x_right - 5:
                    return True
        return False

    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            bi = positions[i]["bbox"]
            bj = positions[j]["bbox"]
            cy_i, cy_j = _bbox_center_y(bi), _bbox_center_y(bj)
            if abs(cy_i - cy_j) <= _GROUP_Y_TOL:
                gap_x = max(0.0, bj[0] - bi[2])
                if gap_x <= _GROUP_GAP_X and not _h_line_between(bi, bj):
                    union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(len(positions)):
        groups.setdefault(find(i), []).append(i)

    result = [[positions[m] for m in sorted(members)] for members in groups.values()]
    result.sort(key=lambda g: (_bbox_center_y(g[0]["bbox"]), g[0]["bbox"][0]))
    return result


# ---------------------------------------------------------------------------
# 步骤 3：为每个 box 查找右侧选项文字
# ---------------------------------------------------------------------------
def _find_option_text(
    box_bbox: RectTuple,
    merged_lines: List[Dict[str, Any]],
    consumed_line_ids: Set[int],
) -> Tuple[str, Optional[int]]:
    """在 box_bbox 右侧查找最近的选项文字，返回 (text, line_index)。"""
    best_text = ""
    best_idx: Optional[int] = None
    best_dist = float("inf")

    box_cx = box_bbox[2]
    box_cy = _bbox_center_y(box_bbox)

    for idx, line in enumerate(merged_lines):
        if idx in consumed_line_ids:
            continue
        lb = line["bbox"]
        text = line.get("text", "").strip()
        if not text or _is_checkbox_text(text):
            continue
        if abs(_bbox_center_y(lb) - box_cy) > _OPT_TEXT_Y_TOL:
            continue
        gap_x = lb[0] - box_cx
        if gap_x < -3.0 or gap_x > _OPT_TEXT_MAX_GAP_X:
            continue
        if gap_x < best_dist:
            best_dist = gap_x
            best_text = text
            best_idx = idx

    return best_text, best_idx


# ---------------------------------------------------------------------------
# 步骤 4+5：为 checkbox 组查找 label 和 additional_text
# ---------------------------------------------------------------------------
def _find_labels_for_group(
    group_bbox: RectTuple,
    merged_lines: List[Dict[str, Any]],
    consumed_line_ids: Set[int],
    h_lines: List[Dict[str, float]],
    v_lines: List[Dict[str, float]],
    shaded_bars: List[RectTuple] | None = None,
) -> Tuple[str, Optional[RectTuple], int | None, List[Dict[str, Any]]]:
    """为 checkbox 组查找 label 和 additional_text。

    搜索策略：
    A. 紧凑封闭单元格 → 排除 shaded_bar 内文字后，左侧优先取距离
    B. 水平同行搜索 → 左侧 y 重叠判断（相对容差），右侧 = additional
    C. 向上兜底 → 到第一条 h_line 或 shaded_bar 为止

    consumed_line_ids 会被就地更新。
    """
    if shaded_bars is None:
        shaded_bars = []
    group_left = group_bbox[0]

    def _ok(line: Dict[str, Any]) -> Tuple[bool, str]:
        text = line.get("text", "").strip()
        if not text or _is_checkbox_text(text) or _starts_with_checkbox(text):
            return False, ""
        return True, text

    def _inside_shaded_bar(lb: RectTuple) -> bool:
        """文字 bbox 中心是否在某个 shaded_bar 内。"""
        lcy = _bbox_center_y(lb)
        lcx = _bbox_center_x(lb)
        for bar in shaded_bars:
            if bar[0] - 5 <= lcx <= bar[2] + 5 and bar[1] - 2 <= lcy <= bar[3] + 2:
                return True
        return False

    # checkbox 组的行高（用于相对容差）
    group_h = group_bbox[3] - group_bbox[1]

    def _hline_fill(bbox: RectTuple) -> RectTuple:
        """找 bbox 下方最近 h_line 构造 fill_rect。"""
        best_hl: Optional[Dict[str, float]] = None
        best_d = float("inf")
        for hl in h_lines:
            hy = float(hl.get("y", 0.0))
            if hy < bbox[1]:
                continue
            hx0 = float(hl.get("x0", 0.0))
            hx1 = float(hl.get("x1", 0.0))
            if max(0.0, min(hx1, bbox[2]) - max(hx0, bbox[0])) > 0 and hy - bbox[3] < best_d:
                best_d = hy - bbox[3]
                best_hl = hl
        if best_hl is not None:
            hy = float(best_hl["y"])
            return (
                round(float(best_hl["x0"]), 2), round(hy - 1, 2),
                round(float(best_hl["x1"]), 2), round(hy, 2),
            )
        return bbox

    def _to_additional(items: List[Tuple[float, str, RectTuple, int]]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for _, text, bbox, idx in items:
            consumed_line_ids.add(idx)
            result.append({"label": text, "label_bbox": list(bbox), "fill_rect": list(_hline_fill(bbox))})
        return result

    def _merge_same_row(
        cands: List[Tuple[float, str, RectTuple, int]],
    ) -> List[Tuple[float, str, RectTuple, int]]:
        """同行（y 中心相近）候选合并为一条：按 x0 排序拼接文本。"""
        if len(cands) <= 1:
            return cands
        by_y = sorted(cands, key=lambda c: _bbox_center_y(c[2]))
        groups: List[List[Tuple[float, str, RectTuple, int]]] = [[by_y[0]]]
        for c in by_y[1:]:
            if abs(_bbox_center_y(c[2]) - _bbox_center_y(groups[-1][0][2])) <= _HORIZ_LABEL_Y_TOL:
                groups[-1].append(c)
            else:
                groups.append([c])
        merged: List[Tuple[float, str, RectTuple, int]] = []
        for rg in groups:
            rg.sort(key=lambda c: c[2][0])
            text = " ".join(c[1] for c in rg)
            bbox = rg[0][2]
            for c in rg[1:]:
                bbox = _bbox_union(bbox, c[2])
                consumed_line_ids.add(c[3])
            merged.append((min(c[0] for c in rg), text, bbox, rg[0][3]))
        return merged

    # ── A：紧凑封闭单元格 ──────────────────────────────────────────────────
    cell = _find_enclosing_cell(group_bbox, h_lines, v_lines)
    if cell is not None and (cell[3] - cell[1]) <= _MAX_CELL_HEIGHT:
        cx0, cy0, cx1, cy1 = cell
        cands: List[Tuple[float, str, RectTuple, int]] = []
        for idx, line in enumerate(merged_lines):
            if idx in consumed_line_ids:
                continue
            ok, text = _ok(line)
            if not ok:
                continue
            lb = line["bbox"]
            lcx, lcy = _bbox_center_x(lb), _bbox_center_y(lb)
            if not (cx0 - 2 <= lcx <= cx1 + 2 and cy0 - 2 <= lcy <= cy1 + 2):
                continue
            if _inside_shaded_bar(lb):
                continue
            if lb[2] <= group_left and _v_line_blocks(lb, group_bbox, v_lines):
                continue
            # 左侧优先：先看文字右边界到 checkbox 左边界的距离
            if lb[2] <= group_left:
                dist = group_left - lb[2]          # 左侧 → 小值优先
            else:
                dist = lb[0] - group_left + 1000   # 右侧 → 加大偏置
            cands.append((dist, text, lb, idx))
        if cands:
            cands = _merge_same_row(cands)
            cands.sort(key=lambda c: c[0])
            _, q_text, q_bbox, q_idx = cands[0]
            consumed_line_ids.add(q_idx)
            return q_text, q_bbox, q_idx, _to_additional(cands[1:])

        # 单元格内找不到 → 越过边框向左水平找（y 有重叠即可）
        left_outside: List[Tuple[float, str, RectTuple, int]] = []
        for idx, line in enumerate(merged_lines):
            if idx in consumed_line_ids:
                continue
            ok, text = _ok(line)
            if not ok:
                continue
            lb = line["bbox"]
            if lb[2] > cell[0]:          # 文字右边界必须在 cell 左边界之左
                continue
            if _inside_shaded_bar(lb):
                continue
            y_overlap = min(lb[3], group_bbox[3]) - max(lb[1], group_bbox[1])
            if y_overlap <= 0:
                continue
            left_outside.append((cell[0] - lb[2], text, lb, idx))
        if left_outside:
            left_outside.sort(key=lambda c: c[0])  # 最近优先
            _, lo_text, lo_bbox, lo_idx = left_outside[0]
            consumed_line_ids.add(lo_idx)
            return lo_text, lo_bbox, lo_idx, []

        # 封闭单元格内外都找不到 → 放弃，不进 B/C
        return "", None, None, []

    # ── B：水平同行扫描 → y 有重叠即候选，左侧最近=label，右侧全部=additional
    left: List[Tuple[float, str, RectTuple, int]] = []
    right: List[Tuple[float, str, RectTuple, int]] = []
    for idx, line in enumerate(merged_lines):
        if idx in consumed_line_ids:
            continue
        ok, text = _ok(line)
        if not ok:
            continue
        lb = line["bbox"]
        if _inside_shaded_bar(lb):
            continue
        y_overlap = min(lb[3], group_bbox[3]) - max(lb[1], group_bbox[1])
        if y_overlap <= 0:
            continue
        if _v_line_blocks(lb, group_bbox, v_lines):
            continue
        if lb[0] >= group_bbox[2] - 5:
            # 完全在 checkbox 右侧
            gap = lb[0] - group_bbox[2]
            right.append((gap, text, lb, idx))
        else:
            # 在 checkbox 左侧（或横跨）
            dist = group_left - lb[2] if lb[2] <= group_left else 0.0
            left.append((dist, text, lb, idx))

    if left:
        left = _merge_same_row(left)
        left.sort(key=lambda c: c[0])
        _, q_text, q_bbox, q_idx = left[0]
        consumed_line_ids.add(q_idx)
        return q_text, q_bbox, q_idx, _to_additional(right)

    # ── C：向上兜底 → 到第一条 h_line / shaded_bar 为止，取最近一条 ─────────
    gcx = _bbox_center_x(group_bbox)
    nearest_hline_y: Optional[float] = None
    for hl in h_lines:
        hy = float(hl.get("y", 0.0))
        hx0 = float(hl.get("x0", 0.0))
        hx1 = float(hl.get("x1", 0.0))
        if hy < group_bbox[1] and hx0 - 10 <= gcx <= hx1 + 10:
            if nearest_hline_y is None or hy > nearest_hline_y:
                nearest_hline_y = hy

    upper_bound = nearest_hline_y if nearest_hline_y is not None else 0.0

    bar_y = _shaded_bar_between_y(upper_bound, group_bbox[1], gcx, shaded_bars)
    if bar_y is not None and bar_y > upper_bound:
        upper_bound = bar_y

    best_up: Optional[Tuple[float, str, RectTuple, int]] = None
    for idx, line in enumerate(merged_lines):
        if idx in consumed_line_ids:
            continue
        ok, text = _ok(line)
        if not ok:
            continue
        lb = line["bbox"]
        lcy = _bbox_center_y(lb)
        if not (upper_bound - 2 <= lcy < group_bbox[1]):
            continue
        if _inside_shaded_bar(lb):
            continue
        dist_y = group_bbox[1] - lb[3]
        if best_up is None or dist_y < best_up[0]:
            best_up = (dist_y, text, lb, idx)

    if best_up is not None:
        _, q_text, q_bbox, q_idx = best_up
        consumed_line_ids.add(q_idx)
        return q_text, q_bbox, q_idx, []

    return "", None, None, []


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def collect_checkboxes(
    phase1_data: Dict[str, Any],
    consumed: Set[str] | None = None,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """从 Phase 1 数据中收集 checkbox 字段。"""
    if consumed is None:
        consumed = set()

    consumed_update: Set[str] = set()

    merged_lines: List[Dict[str, Any]] = phase1_data.get("text_lines", [])
    text_spans: List[Dict[str, Any]] = phase1_data.get("text_spans", [])
    drawing_data: Dict[str, Any] = phase1_data.get("drawing_data", {})
    tables: List[Dict[str, Any]] = phase1_data.get("table_structures", [])

    square_boxes: List[RectTuple] = drawing_data.get("square_boxes", [])
    h_lines: List[Dict[str, float]] = drawing_data.get("horizontal_lines", [])
    v_lines: List[Dict[str, float]] = drawing_data.get("vertical_lines", [])
    raw_drawings: List[Dict[str, Any]] = drawing_data.get("drawings", [])
    shaded_bars = _extract_shaded_bars(raw_drawings)

    # 计算表格区域（2×2 蔓延算法 + 竖线迭代扩展）
    table_zones = _detect_table_zones(tables, v_lines)

    # 步骤 1：收集 checkbox 位置（排除表格区域内的）
    positions = _collect_checkbox_positions(square_boxes, merged_lines, text_spans, table_zones)
    if not positions:
        return [], consumed_update

    # 步骤 2：分组
    groups = _group_checkboxes(positions, h_lines)

    fields: List[Dict[str, Any]] = []
    consumed_line_ids: Set[int] = set()

    # 先标记纯 checkbox 字形行为已消耗
    for idx, line in enumerate(merged_lines):
        if _is_checkbox_text(line.get("text", "")):
            consumed_line_ids.add(idx)

    for group in groups:
        # 组的总 bbox
        group_bbox = group[0]["bbox"]
        for cb in group[1:]:
            group_bbox = _bbox_union(group_bbox, cb["bbox"])

        # 步骤 3：为每个 box 找选项文字
        options: List[Dict[str, Any]] = []
        for cb in group:
            opt_text, opt_idx = _find_option_text(cb["bbox"], merged_lines, consumed_line_ids)
            options.append({"text": opt_text, "bbox": list(cb["bbox"])})
            if opt_idx is not None:
                consumed_line_ids.add(opt_idx)

        # 步骤 4+5：查找 label 和 additional_text
        q_text, q_bbox, q_idx, additional = _find_labels_for_group(
            group_bbox, merged_lines, consumed_line_ids, h_lines, v_lines,
            shaded_bars=shaded_bars,
        )

        # 组的外包围框（仅 checkbox + options，不含 label）
        fill_rect = group_bbox
        for opt in options:
            fill_rect = _bbox_union(fill_rect, tuple(opt["bbox"]))  # type: ignore[arg-type]

        fields.append({
            "field_type": "checkbox",
            "group_id": len(fields) + 1,
            "label": q_text,
            "label_bbox": list(q_bbox) if q_bbox is not None else None,
            "fill_rect": list(fill_rect),
            "options": options,
            "additional_text": additional,
        })

    # 构建 consumed_update
    for idx in consumed_line_ids:
        consumed_update.add(f"line:{idx}")
    for pos in positions:
        b = pos["bbox"]
        consumed_update.add(f"square_box:{b[0]:.1f},{b[1]:.1f},{b[2]:.1f},{b[3]:.1f}")

    return fields, consumed_update

