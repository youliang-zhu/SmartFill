"""Phase 2B — Text 字段收集器 (v3)

三通道收集 + 面积优先选择 + 确定性冲突消解。

通道优先级: underline > dotleader > remaining
流程:
  1. 过滤噪声 / table zone / checkbox 禁区，收集 label 候选
  2. Channel 1 — 短段 h_line 认领 label（fill_rect = 下划线区域）
  3. Channel 2 — dotleader 模式认领 label（fill_rect = 点线区域）
  4. Channel 3 — 剩余 label 按行组织，右侧/下方候选二选一（面积优先）
  5. 冲突消解：行内裁剪 + 全局兜底
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.native.preprocess.collector.collect_checkboxes import (
    _detect_table_zones,
    _extract_shaded_bars,
    _in_table_zone,
)
from app.services.native.preprocess.core.odl_fallback import (
    _find_odl_label_completion,
    _load_odl_fallback_lines,
)

# ---------------------------------------------------------------------------
# 类型 & 常量
# ---------------------------------------------------------------------------
Obstacle = Tuple[float, float, float, float]

_TOL = 2.0
_ROW_Y_TOL = 8.0              # 同行 y-center 容差
_BELOW_MAX_H_RATIO = 3.0      # below_rect 高度上限 = N × label 行高

# ---------------------------------------------------------------------------
# 噪声过滤
# ---------------------------------------------------------------------------
_RE_PAGE_DASH = re.compile(r"^-\s*\d+\s*-$")
_RE_PAGE_OF = re.compile(r"^Page\s+\d+\s+of\s+\d+", re.IGNORECASE)
_RE_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_FORM_HEADER_PREFIXES = ("OMB ", "OMB#", "OMB Approval", "OMB Control", "OMB NUMBER")

_RE_DOTLEADER = re.compile(
    r"^(.+?)\s*"          # label 文字（lazy）
    r"([._·…]{4,}"        # ≥4 个连续点/下划线
    r"[\s._·…]*)"         # 后续可夹杂空格
    r"\s*$",
)


def _cy(bbox: Tuple[float, ...]) -> float:
    """bbox y-center。"""
    return (bbox[1] + bbox[3]) / 2.0


def _bbox_overlap_x(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _bbox_overlap_y(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    return max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _rect_area(r: Optional[List[float]]) -> float:
    if r is None:
        return 0.0
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _rect_overlaps(a: Tuple[float, ...], b: Tuple[float, ...]) -> bool:
    return _bbox_overlap_x(a, b) > _TOL and _bbox_overlap_y(a, b) > _TOL


def _rect_overlaps_any(rect: List[float], obstacles: List[Obstacle]) -> bool:
    probe = (rect[0], rect[1], rect[2], rect[3])
    for obs in obstacles:
        if _rect_overlaps(probe, obs):
            return True
    return False


def _normalize_rect(rect: List[float]) -> Optional[List[float]]:
    if rect[2] - rect[0] <= _TOL or rect[3] - rect[1] <= _TOL:
        return None
    return rect


def _choose_larger_rect(
    right_rect: Optional[List[float]],
    below_rect: Optional[List[float]],
) -> Optional[List[float]]:
    if right_rect and below_rect:
        if _rect_area(right_rect) >= _rect_area(below_rect):
            return right_rect
        return below_rect
    return right_rect or below_rect


def _is_noise(text: str) -> bool:
    s = text.strip()
    if len(s) <= 2:
        return not re.match(r"^\d\.?$", s)
    if _RE_PAGE_DASH.match(s):
        return True
    if _RE_PAGE_OF.match(s):
        return True
    if _RE_URL.search(s):
        return True
    up = s.upper()
    for pfx in _FORM_HEADER_PREFIXES:
        if up.startswith(pfx.upper()):
            return True
    if re.match(r"^Form\s+[A-Z0-9]", s):
        return True
    return False


# ---------------------------------------------------------------------------
# Checkbox 禁区
# ---------------------------------------------------------------------------
def _build_checkbox_zones(
    checkbox_fields: List[Dict[str, Any]] | None,
) -> List[Obstacle]:
    """从 checkbox 输出提取几何禁区（fill_rect + options bbox + additional_text fill_rect）。"""
    zones: List[Obstacle] = []
    for cf in (checkbox_fields or []):
        fr = cf.get("fill_rect")
        if fr and len(fr) == 4:
            zones.append((float(fr[0]), float(fr[1]), float(fr[2]), float(fr[3])))
        for opt in cf.get("options", []):
            b = opt.get("bbox")
            if b and len(b) == 4:
                zones.append((float(b[0]), float(b[1]), float(b[2]), float(b[3])))
        for at in cf.get("additional_text", []):
            afr = at.get("fill_rect")
            if afr and len(afr) == 4:
                zones.append((float(afr[0]), float(afr[1]), float(afr[2]), float(afr[3])))
    return zones


def _in_checkbox_zone(bbox: Tuple[float, ...], zones: List[Obstacle]) -> bool:
    """label bbox 中心是否落在 checkbox 禁区内。"""
    cx = (bbox[0] + bbox[2]) / 2.0
    cy_ = (bbox[1] + bbox[3]) / 2.0
    for z in zones:
        if z[0] - 2 <= cx <= z[2] + 2 and z[1] - 2 <= cy_ <= z[3] + 2:
            return True
    return False


def _in_shaded_bar(bbox: Tuple[float, ...], shaded_bars: List[Obstacle]) -> bool:
    """label 是否处于深色标题条中。"""
    cx = (bbox[0] + bbox[2]) / 2.0
    cy_ = (bbox[1] + bbox[3]) / 2.0
    for bx0, by0, bx1, by1 in shaded_bars:
        if bx0 - 2 <= cx <= bx1 + 2 and by0 - 2 <= cy_ <= by1 + 2:
            return True
        overlap_x = _bbox_overlap_x(bbox, (bx0, by0, bx1, by1))
        overlap_y = _bbox_overlap_y(bbox, (bx0, by0, bx1, by1))
        if overlap_x > 4.0 and overlap_y > 2.0:
            return True
    return False


# ---------------------------------------------------------------------------
# 障碍物 & 边界搜索
# ---------------------------------------------------------------------------
def _make_static_obstacles(
    h_lines: List[Dict[str, Any]],
    v_lines: List[Dict[str, Any]],
    shaded_bars: List[Obstacle],
    cb_zones: List[Obstacle],
) -> List[Obstacle]:
    """构建静态障碍物（对所有 label 通用）。"""
    obs: List[Obstacle] = []
    for h in h_lines:
        obs.append((h["x0"], h["y"] - 0.5, h["x1"], h["y"] + 0.5))
    for v in v_lines:
        vy0, vy1 = min(v["y0"], v["y1"]), max(v["y0"], v["y1"])
        obs.append((v["x"] - 0.5, vy0, v["x"] + 0.5, vy1))
    obs.extend(shaded_bars)
    obs.extend(cb_zones)
    return obs


def _extract_dark_vertical_edges(drawings: List[Dict[str, Any]]) -> List[Obstacle]:
    edges: List[Obstacle] = []
    for d in drawings:
        fill = d.get("fill")
        rect = d.get("rect")
        if fill is None or rect is None:
            continue
        if not (isinstance(fill, (list, tuple)) and len(fill) >= 3):
            continue
        if sum(float(c) for c in fill[:3]) > 0.25:
            continue
        x0, y0, x1, y1 = [float(v) for v in rect]
        if 0.0 < (x1 - x0) <= 2.0 and (y1 - y0) >= 8.0:
            edges.append((x0, y0, x1, y1))
    edges.sort(key=lambda r: (r[0], r[1]))
    return edges


def _extract_dark_horizontal_edges(drawings: List[Dict[str, Any]]) -> List[Obstacle]:
    edges: List[Obstacle] = []
    for d in drawings:
        fill = d.get("fill")
        rect = d.get("rect")
        if fill is None or rect is None:
            continue
        if not (isinstance(fill, (list, tuple)) and len(fill) >= 3):
            continue
        if sum(float(c) for c in fill[:3]) > 0.25:
            continue
        x0, y0, x1, y1 = [float(v) for v in rect]
        if 0.0 < (y1 - y0) <= 2.0 and (x1 - x0) >= 8.0:
            edges.append((x0, y0, x1, y1))
    edges.sort(key=lambda r: (r[1], r[0]))
    return edges


def _find_right_bound(
    x: float, y0: float, y1: float, obstacles: List[Obstacle],
) -> Optional[float]:
    """从 x 向右，找最近障碍物左边缘（y 范围有重叠）。"""
    best: Optional[float] = None
    for ox0, oy0, ox1, oy1 in obstacles:
        if ox0 > x + _TOL and oy0 < y1 - _TOL and oy1 > y0 + _TOL:
            if best is None or ox0 < best:
                best = ox0
    return best


def _find_bottom_bound(
    y: float, x0: float, x1: float, obstacles: List[Obstacle],
) -> Optional[float]:
    """从 y 向下，找最近障碍物上边缘（x 范围有重叠）。"""
    best: Optional[float] = None
    for ox0, oy0, ox1, oy1 in obstacles:
        if oy0 > y + _TOL and ox0 < x1 - _TOL and ox1 > x0 + _TOL:
            if best is None or oy0 < best:
                best = oy0
    return best


def _find_vertical_edge(
    x0: float,
    y0: float,
    y1: float,
    v_lines: List[Dict[str, Any]],
    dark_vertical_edges: List[Obstacle],
) -> Optional[float]:
    best: Optional[float] = None
    probe = (x0, y0, x0 + 1.0, y1)
    for vl in v_lines:
        vx = float(vl.get("x", 0.0))
        vy0 = float(vl.get("y0", 0.0))
        vy1 = float(vl.get("y1", 0.0))
        if vx <= x0 + _TOL:
            continue
        if _bbox_overlap_y((vx, vy0, vx + 0.1, vy1), probe) > 1.0:
            best = vx if best is None else min(best, vx)
    for ex0, ey0, ex1, ey1 in dark_vertical_edges:
        if ex0 <= x0 + _TOL:
            continue
        if _bbox_overlap_y((ex0, ey0, ex1, ey1), probe) > 1.0:
            best = ex0 if best is None else min(best, ex0)
    return best


def _find_column_right_edge(
    bbox: Tuple[float, ...],
    page_right: float,
    v_lines: List[Dict[str, Any]],
    shaded_bars: List[Obstacle],
    dark_vertical_edges: List[Obstacle],
) -> float:
    lx0, ly0, _lx1, ly1 = bbox
    best = page_right
    for bx0, _by0, bx1, _by1 in shaded_bars:
        if bx0 <= lx0 + _TOL and bx1 > lx0 + _TOL:
            best = min(best, bx1)
    vertical_edge = _find_vertical_edge(lx0, ly0, ly1, v_lines, dark_vertical_edges)
    if vertical_edge is not None:
        best = min(best, vertical_edge)
    return best


def _find_top_bound(
    y: float, x0: float, x1: float, obstacles: List[Obstacle],
) -> Optional[float]:
    """从 y 向上，找最近障碍物下边缘（x 范围有重叠）。"""
    best: Optional[float] = None
    for ox0, oy0, ox1, oy1 in obstacles:
        if oy1 < y - _TOL and ox0 < x1 - _TOL and ox1 > x0 + _TOL:
            if best is None or oy1 > best:
                best = oy1
    return best


def _shrink_rect_no_overlap(
    rect: List[float], obstacles: List[Obstacle],
) -> Optional[List[float]]:
    """贪心裁剪 rect 使其不与任何障碍物重叠。"""
    rx0, ry0, rx1, ry1 = rect
    for _ in range(20):
        hit = False
        for ox0, oy0, ox1, oy1 in obstacles:
            if rx0 >= ox1 - _TOL or rx1 <= ox0 + _TOL:
                continue
            if ry0 >= oy1 - _TOL or ry1 <= oy0 + _TOL:
                continue
            clips: List[Tuple[str, float, float]] = []
            if ox0 > rx0 + _TOL:
                clips.append(("r", (ox0 - rx0) * (ry1 - ry0), ox0))
            if ox1 < rx1 - _TOL:
                clips.append(("l", (rx1 - ox1) * (ry1 - ry0), ox1))
            if oy0 > ry0 + _TOL:
                clips.append(("b", (rx1 - rx0) * (oy0 - ry0), oy0))
            if oy1 < ry1 - _TOL:
                clips.append(("t", (rx1 - rx0) * (ry1 - oy1), oy1))
            if not clips:
                return None
            best = max(clips, key=lambda c: c[1])
            if best[0] == "r":
                rx1 = best[2]
            elif best[0] == "l":
                rx0 = best[2]
            elif best[0] == "b":
                ry1 = best[2]
            else:
                ry0 = best[2]
            hit = True
            break
        if not hit:
            break
    if rx1 - rx0 < _TOL or ry1 - ry0 < _TOL:
        return None
    return [rx0, ry0, rx1, ry1]


def _build_below_rect(
    *,
    lx0: float,
    ly1: float,
    right_limit: float,
    bottom_limit: float,
    obstacles: List[Obstacle],
) -> Optional[List[float]]:
    """直接按障碍物生成下方候选，不再先铺大框后 shrink。"""
    if right_limit - lx0 <= _TOL or bottom_limit - ly1 <= _TOL:
        return None

    probe_right = min(right_limit, lx0 + 1.0)
    if probe_right - lx0 <= _TOL:
        return None

    bottom = _find_bottom_bound(ly1, lx0, probe_right, obstacles) or bottom_limit
    bottom = min(bottom, bottom_limit)
    if bottom - ly1 <= _TOL:
        return None

    right = _find_right_bound(lx0, ly1, bottom, obstacles) or right_limit
    right = min(right, right_limit)
    rect = _normalize_rect([lx0, ly1, right, bottom])
    if rect is None or _rect_overlaps_any(rect, obstacles):
        return None
    return rect


def _build_right_rect(
    *,
    lx1: float,
    ly0: float,
    ly1: float,
    right_limit: float,
    top_limit: float,
    bottom_limit: float,
    obstacles: List[Obstacle],
) -> Optional[List[float]]:
    """构造右侧候选：等高优先，少量上下微调/降高。"""
    if right_limit - lx1 <= _TOL:
        return None

    lh = ly1 - ly0
    if lh <= _TOL:
        return None

    shift = lh * 0.3
    trim = lh * 0.18
    variants = [
        (ly0, ly1),
        (ly0 + shift, ly1 + shift),
        (ly0 - shift, ly1 - shift),
        (ly0 + trim, ly1 - trim),
        (ly0 + shift, ly1 - trim),
    ]

    best: Optional[List[float]] = None
    best_area = 0.0
    seen: Set[Tuple[float, float]] = set()
    for y0, y1 in variants:
        y0 = max(top_limit, y0)
        y1 = min(bottom_limit, y1)
        key = (round(y0, 2), round(y1, 2))
        if key in seen or y1 - y0 <= _TOL:
            continue
        seen.add(key)

        right = _find_right_bound(lx1, y0, y1, obstacles) or right_limit
        right = min(right, right_limit)
        rect = _normalize_rect([lx1, y0, right, y1])
        if rect is None or _rect_overlaps_any(rect, obstacles):
            continue

        area = _rect_area(rect)
        if area > best_area:
            best = rect
            best_area = area

    return best


# ---------------------------------------------------------------------------
# 行分组
# ---------------------------------------------------------------------------
def _group_by_row(indices: List[int], get_bbox) -> List[List[int]]:
    """按 y-center 分行，行内按 x0 排序。"""
    if not indices:
        return []
    ordered = sorted(indices, key=lambda i: (_cy(get_bbox(i)), get_bbox(i)[0]))
    rows: List[List[int]] = [[ordered[0]]]
    for i in ordered[1:]:
        if abs(_cy(get_bbox(i)) - _cy(get_bbox(rows[-1][0]))) <= _ROW_Y_TOL:
            rows[-1].append(i)
        else:
            rows.append([i])
    for row in rows:
        row.sort(key=lambda i: get_bbox(i)[0])
    return rows


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def collect_text_fields(
    phase1_data: Dict[str, Any],
    consumed: Set[str],
    checkbox_fields: List[Dict[str, Any]] | None = None,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Text 字段收集：三通道 + 面积优先 + 行内裁剪。"""

    merged_lines: List[Dict[str, Any]] = phase1_data.get("text_lines", [])
    drawing_data: Dict[str, Any] = phase1_data.get("drawing_data", {})
    tables: List[Dict[str, Any]] = phase1_data.get("table_structures", [])
    h_lines: List[Dict[str, Any]] = drawing_data.get("horizontal_lines", [])
    v_lines: List[Dict[str, Any]] = drawing_data.get("vertical_lines", [])
    raw_drawings: List[Dict[str, Any]] = drawing_data.get("drawings", [])
    pdf_path = str(phase1_data.get("pdf_path", "") or "")

    # 页面尺寸
    page_size = phase1_data.get("page_size")
    if page_size:
        page_width = page_size[2] - page_size[0]
        page_right = page_size[2]
        page_bottom = page_size[3]
    elif h_lines:
        page_width = max(h["x1"] - h["x0"] for h in h_lines) / 0.8
        page_right = page_width
        page_bottom = 792.0
    else:
        page_width = 612.0
        page_right = 612.0
        page_bottom = 792.0

    # 已消耗行
    consumed_line_ids: Set[int] = set()
    for c in consumed:
        if c.startswith("line:"):
            consumed_line_ids.add(int(c.split(":")[1]))

    table_zones = _detect_table_zones(tables, v_lines)
    shaded_bars = _extract_shaded_bars(raw_drawings)
    dark_vertical_edges = _extract_dark_vertical_edges(raw_drawings)
    dark_horizontal_edges = _extract_dark_horizontal_edges(raw_drawings)
    cb_zones = _build_checkbox_zones(checkbox_fields)
    odl_lines = _load_odl_fallback_lines(
        pdf_path=pdf_path,
        page_num=int(phase1_data.get("page_num", 0)),
        page_size=page_size,
    )

    # ==================================================================
    # 收集 label 候选（噪声 + table + checkbox 禁区 + 已消耗 全部过滤）
    # ==================================================================
    # labels[li] = (line_idx, text, bbox)
    labels: List[Tuple[int, str, Tuple[float, ...]]] = []
    for idx, line in enumerate(merged_lines):
        if idx in consumed_line_ids:
            continue
        text = line.get("text", "").strip()
        if not text:
            continue
        bbox = tuple(line.get("bbox", (0, 0, 0, 0)))
        if _in_table_zone(_cy(bbox), table_zones):
            continue
        if _is_noise(text):
            continue
        if _in_checkbox_zone(bbox, cb_zones):
            continue
        if _in_shaded_bar(bbox, shaded_bars):
            continue
        labels.append((idx, text, bbox))

    # 全页文字 bbox（障碍物用，包含已消耗行——物理位置仍存在）
    all_text_bboxes: Dict[int, Tuple[float, ...]] = {}
    for mi, line in enumerate(merged_lines):
        if line.get("text", "").strip():
            all_text_bboxes[mi] = tuple(line["bbox"])

    # 静态障碍物（矢量线 + 背景条 + checkbox 禁区）
    static_obs = _make_static_obstacles(h_lines, v_lines, shaded_bars, cb_zones)
    static_obs.extend(dark_vertical_edges)
    static_obs.extend(dark_horizontal_edges)

    fields: List[Dict[str, Any]] = []
    new_consumed: Set[str] = set()
    used: Set[int] = set()          # 已被通道认领的 label 索引

    def _full_obstacles(exclude_line_idx: int) -> List[Obstacle]:
        """静态障碍物 + 除自身外全部文字 bbox。"""
        return static_obs + [
            b for mi, b in all_text_bboxes.items() if mi != exclude_line_idx
        ]

    # ==================================================================
    # Channel 1: Underline — 短段 h_line 认领最近 label
    # ==================================================================
    short_hlines = [h for h in h_lines if (h["x1"] - h["x0"]) < page_width * 0.6]

    for hl in short_hlines:
        hx0, hx1, hy = hl["x0"], hl["x1"], hl["y"]
        best_li: Optional[int] = None
        best_dist = float("inf")

        for li, (idx, text, bbox) in enumerate(labels):
            if li in used:
                continue
            lx0, ly0, lx1, ly1 = bbox
            lh = ly1 - ly0

            # 上方：label 底 ≤ h_line，距离 < 2× 行高，x 有重叠
            if ly1 <= hy and (hy - ly1) < lh * 2:
                if lx1 > hx0 - 5 and lx0 < hx1 + 5:
                    d = hy - ly1
                    if d < best_dist:
                        best_dist = d
                        best_li = li
                    continue

            # 左侧：label 右边缘在 h_line 左端附近
            if lx1 <= hx0 + 5 and lx1 > hx0 - 30:
                rt = hy - lh
                if ly0 < hy and ly1 > rt:
                    d = max(0.0, hx0 - lx1)
                    if d < best_dist:
                        best_dist = d
                        best_li = li

        if best_li is not None:
            idx, text, bbox = labels[best_li]
            lh = bbox[3] - bbox[1]
            fr = _shrink_rect_no_overlap(
                [hx0, hy - lh, hx1, hy],
                _full_obstacles(idx),
            )
            fields.append({
                "field_type": "text",
                "label": text,
                "label_bbox": list(bbox),
                "fill_rect": fr,
            })
            used.add(best_li)
            new_consumed.add(f"line:{idx}")

    # ==================================================================
    # Channel 2: Dotleader — 文字中含 ≥4 连续点/下划线
    # ==================================================================
    for li, (idx, text, bbox) in enumerate(labels):
        if li in used:
            continue
        m = _RE_DOTLEADER.match(text)
        if not m:
            continue
        label_text = m.group(1).strip()
        if not label_text:
            continue

        lx0, ly0, lx1, ly1 = bbox
        total_len = len(text)
        label_len = len(m.group(1))
        if total_len > 0 and (lx1 - lx0) > 0:
            dot_x0 = lx0 + (label_len / total_len) * (lx1 - lx0)
        else:
            dot_x0 = lx1

        fields.append({
            "field_type": "text",
            "label": label_text,
            "label_bbox": list(bbox),
            "fill_rect": [dot_x0, ly0, lx1, ly1],
        })
        used.add(li)
        new_consumed.add(f"line:{idx}")

    # ==================================================================
    # Channel 3: Remaining — 右侧 vs 下方（面积优先）
    # ==================================================================
    remaining = [li for li in range(len(labels)) if li not in used]
    rows = _group_by_row(remaining, lambda li: labels[li][2])

    # 每行 y-top（用于 below_rect 行间高度限制）
    row_y_tops = [min(labels[li][2][1] for li in row) for row in rows]

    def _find_shaded_right_edge(x: float) -> Optional[float]:
        """找到 x 方向覆盖 label 的 shaded bar 右边缘（列边界推断）。

        shaded bar 视为列标记：只要 label x0 在 bar x 范围内，
        bar 的 x1 就是该列的右边界，不要求 y 重叠。
        """
        best: Optional[float] = None
        for bx0, _by0, bx1, _by1 in shaded_bars:
            if bx0 <= x + _TOL and bx1 > x + _TOL:
                if best is None or bx1 < best:
                    best = bx1
        return best

    for ri, row in enumerate(rows):
        next_row_y = row_y_tops[ri + 1] if ri + 1 < len(rows) else page_bottom

        for pos, li in enumerate(row):
            idx, text, bbox = labels[li]
            lx0, ly0, lx1, ly1 = bbox
            lh = ly1 - ly0

            # 同行下一个 label x0 → 硬右边界
            next_x0 = labels[row[pos + 1]][2][0] if pos + 1 < len(row) else page_right

            obs = _full_obstacles(idx)

            # --- 右侧候选 ---
            right_limit = next_x0
            right_rect = _build_right_rect(
                lx1=lx1,
                ly0=ly0,
                ly1=ly1,
                right_limit=right_limit,
                top_limit=max(0.0, ly0 - lh * 0.4),
                bottom_limit=min(next_row_y, page_bottom),
                obstacles=obs,
            )

            # --- 下方候选 ---
            shaded_edge = _find_shaded_right_edge(lx0)
            below_limit = next_x0
            if shaded_edge is not None:
                below_limit = min(below_limit, shaded_edge)
            below_rect = _build_below_rect(
                lx0=lx0,
                ly1=ly1,
                right_limit=below_limit,
                bottom_limit=min(next_row_y, ly1 + lh * _BELOW_MAX_H_RATIO, page_bottom),
                obstacles=obs,
            )

            # 面积优先；相等时优先右侧
            fr = _choose_larger_rect(right_rect, below_rect)

            fields.append({
                "field_type": "text",
                "label": text,
                "label_bbox": list(bbox),
                "fill_rect": fr,
            })
            new_consumed.add(f"line:{idx}")

    if odl_lines:
        for field in fields:
            label = str(field.get("label", "")).strip()
            label_bbox = field.get("label_bbox")
            if not label or label_bbox is None:
                continue
            odl_label, odl_bbox = _find_odl_label_completion(
                baseline_label=label,
                baseline_bbox=label_bbox,
                odl_lines=odl_lines,
                allow_shorter=False,
                allow_if_prefix=True,
            )
            if odl_label and odl_bbox is not None:
                field["label"] = odl_label
                field["label_bbox"] = list(odl_bbox)

        deduped_fields: List[Dict[str, Any]] = []
        dedup_index: Dict[Tuple[str, Tuple[float, float, float, float]], int] = {}
        for field in fields:
            label = re.sub(r"\s+", " ", str(field.get("label", "")).strip())
            label_bbox = field.get("label_bbox")
            if not label or not label_bbox:
                deduped_fields.append(field)
                continue

            label_core = re.sub(r"^\s*(?:\d+\.\s*|[A-Za-z]\.\s*)", "", label)
            bbox_key = tuple(round(float(v), 2) for v in label_bbox)
            key = (label_core, bbox_key)
            if key not in dedup_index:
                dedup_index[key] = len(deduped_fields)
                deduped_fields.append(field)
                continue

            prev = deduped_fields[dedup_index[key]]
            prev_rect = prev.get("fill_rect")
            curr_rect = field.get("fill_rect")
            if len(label) > len(str(prev.get("label", ""))):
                prev["label"] = label
            if _rect_area(curr_rect) > _rect_area(prev_rect):
                prev["fill_rect"] = curr_rect

        fields = deduped_fields

    # ==================================================================
    # Separator-Aware Allowed Region Refinement
    # ==================================================================
    field_labels = [
        (fi, tuple(field["label_bbox"]))
        for fi, field in enumerate(fields)
        if field.get("label_bbox")
    ]
    field_rows = _group_by_row(list(range(len(field_labels))), lambda li: field_labels[li][1])
    field_row_y_tops = [min(field_labels[li][1][1] for li in row) for row in field_rows]
    field_row_of: Dict[int, Tuple[int, int]] = {}
    for ri, row in enumerate(field_rows):
        for pos, li in enumerate(row):
            field_row_of[li] = (ri, pos)

    field_column_rights: Dict[int, float] = {}
    for fi, bbox in field_labels:
        field_column_rights[fi] = _find_column_right_edge(
            bbox=bbox,
            page_right=page_right,
            v_lines=v_lines,
            shaded_bars=shaded_bars,
            dark_vertical_edges=dark_vertical_edges,
        )

    def _full_obstacles_for_bbox(label_bbox: Tuple[float, ...]) -> List[Obstacle]:
        obs = list(static_obs)
        for b in all_text_bboxes.values():
            same = all(abs(b[i] - label_bbox[i]) <= 0.5 for i in range(4))
            if not same:
                obs.append(b)
        return obs

    for fi, field in enumerate(fields):
        lb = field.get("label_bbox")
        if not lb:
            continue
        bbox = tuple(float(v) for v in lb)
        lx0, ly0, lx1, ly1 = bbox
        lh = ly1 - ly0
        if lh <= 0:
            continue

        ri, pos = field_row_of.get(fi, (0, 0))
        row = field_rows[ri]
        next_x0 = field_labels[row[pos + 1]][1][0] if pos + 1 < len(row) else page_right
        column_right = field_column_rights[fi]

        def _next_value_y(cx0: float, cx1: float) -> float:
            best = page_bottom
            probe = (cx0, ly1, cx1, ly1 + 1.0)
            for oi, obox in field_labels:
                if oi == fi:
                    continue
                if obox[1] <= ly1 + _TOL:
                    continue
                other_col_right = field_column_rights[oi]
                other_value_band = (obox[2], obox[1], other_col_right, obox[3])
                if _bbox_overlap_x(probe, other_value_band) > 1.0:
                    best = min(best, obox[1])
            if best == page_bottom and ri + 1 < len(field_rows):
                best = field_row_y_tops[ri + 1]
            return best

        obs = _full_obstacles_for_bbox(bbox)

        right_rect = _build_right_rect(
            lx1=lx1,
            ly0=ly0,
            ly1=ly1,
            right_limit=min(next_x0, page_right),
            top_limit=max(0.0, ly0 - lh * 0.4),
            bottom_limit=min(_next_value_y(lx1, next_x0), page_bottom),
            obstacles=obs,
        )

        below_rect = _build_below_rect(
            lx0=lx0,
            ly1=ly1,
            right_limit=min(column_right, next_x0),
            bottom_limit=min(_next_value_y(lx0, min(column_right, next_x0)), ly1 + lh * _BELOW_MAX_H_RATIO, page_bottom),
            obstacles=obs,
        )

        fr = _choose_larger_rect(right_rect, below_rect)

        field["fill_rect"] = fr

    # ==================================================================
    # 冲突消解
    # ==================================================================

    # Step 1: 行内裁剪 — 前一个 fill_rect 右边界裁到下一个 label 左边界
    def _get_field_bbox(fi: int) -> Tuple[float, ...]:
        return tuple(fields[fi]["label_bbox"])

    field_rows = _group_by_row(list(range(len(fields))), _get_field_bbox)

    for frow in field_rows:
        for pos, fi in enumerate(frow):
            fr = fields[fi]["fill_rect"]
            if fr is None or pos + 1 >= len(frow):
                continue
            nfi = frow[pos + 1]
            nx0 = fields[nfi]["label_bbox"][0]
            if fr[2] > nx0 - 1:
                fr[2] = nx0 - 1
                if fr[2] <= fr[0] + _TOL:
                    fields[fi]["fill_rect"] = None

    # Step 2: 全局兜底 — 各 field 的 fill_rect 不应与其它 fill_rect / label_bbox 重叠
    sorted_fi = sorted(
        range(len(fields)),
        key=lambda i: (_cy(tuple(fields[i]["label_bbox"])), fields[i]["label_bbox"][0]),
    )
    for fi in sorted_fi:
        fr = fields[fi]["fill_rect"]
        if fr is None:
            continue
        other_rects: List[Obstacle] = []
        for fj in range(len(fields)):
            if fj == fi:
                continue
            ofr = fields[fj]["fill_rect"]
            if ofr is not None:
                other_rects.append((ofr[0], ofr[1], ofr[2], ofr[3]))
            olb = fields[fj].get("label_bbox")
            if olb is not None:
                other_rects.append((olb[0], olb[1], olb[2], olb[3]))
        if other_rects:
            fields[fi]["fill_rect"] = _shrink_rect_no_overlap(fr, other_rects)

    return fields, new_consumed
