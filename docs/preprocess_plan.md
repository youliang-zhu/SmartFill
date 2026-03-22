# Native PDF 预处理实现方案（Instafill 路径复现）

> 文档定位：预处理阶段的计划与规范文档（隶属于 v2 架构）。  
> 记录范围：只记录预处理方案、流程规范、接口约束、验收标准及架构调整。  
> 排除范围：不记录 debug 过程、报错细节和临时排障日志。  
> 变更规则：若预处理层面发生架构改变，需追加到本文件；调试过程先记录在 `Preprocess errors summary.md`，待 bug 修复且方案稳定后再同步。  

> 创建时间：2026-03-17
> 目标：参照 Instafill.ai 的 4 引擎 + 8 步几何修正方案，重写 `detector.py` 的上层检测逻辑
> 关联文档：[workflow_research.md](workflow_research.md)、[devplan_v2.md](devplan_v2.md)
> 执行方：本文档将交给 Codex agent 完成全部代码编写

---

## 目录

1. [现有代码结构与改造策略](#1-现有代码结构与改造策略)
2. [新增依赖](#2-新增依赖)
3. [目标文件结构](#3-目标文件结构)
4. [引擎 1：detect_boxes_fitz — 矢量检测主引擎](#4-引擎-1detect_boxes_fitz--矢量检测主引擎)
5. [引擎 2：detect_blanks — 空白区间回退引擎](#5-引擎-2detect_blanks--空白区间回退引擎)
6. [引擎 3：detect_checkboxes — Checkbox 专用引擎](#6-引擎-3detect_checkboxes--checkbox-专用引擎)
7. [引擎 4：synthesize_fields_from_table_cells — 表格合成引擎](#7-引擎-4synthesize_fields_from_table_cells--表格合成引擎)
8. [8 步几何修正流水线](#8-8-步几何修正流水线)
9. [整合入口：detect_all](#9-整合入口detect_all)
10. [可视化测试工具](#10-可视化测试工具)
11. [测试 PDF 与验证标准](#11-测试-pdf-与验证标准)
12. [附录：测试 PDF 页面分析](#12-附录测试-pdf-页面分析)

---

## 1. 现有代码结构与改造策略

### 1.1 现有文件

| 文件 | 说明 | 改造策略 |
|------|------|---------|
| `backend/app/services/native/detector.py` | 当前 Phase 1 检测器（~1050 行） | **重写**：保留底层工具函数，按 4 引擎结构重组上层逻辑 |
| `backend/app/services/native/pipeline.py` | 流水线入口 | **不动**（调用 detector 的接口不变） |
| `backend/app/services/native/__init__.py` | 模块导出 | **不动** |
| `backend/app/services/pdf_pipeline_dispatcher.py` | PDF 分发器 | **不动** |
| `backend/app/config.py` | 配置（已含 VLM 预留） | **不动** |
| `backend/requirements.txt` | 依赖 | **修改**：新增 `pdfplumber` |

### 1.2 detector.py 中要保留的底层工具函数

以下这些**静态方法/类方法**逻辑正确、经过验证，直接保留不改：

```python
# 几何工具
_round(v, ndigits=2)
_rect_tuple(rect: fitz.Rect) -> RectTuple
_bbox_union(a, b) -> RectTuple
_bbox_center(bbox) -> (cx, cy)
_bbox_width(bbox) -> float
_bbox_height(bbox) -> float
_is_valid_rect(bbox) -> bool
_intersects(a, b, gap=0.0) -> bool
_overlap_ratio(a, b) -> float
_cluster_values(values, tol) -> List[float]

# 文本工具
_normalize_text(text) -> str
_word_count(text) -> int
_slug(text, max_len=24) -> str
_is_checkbox_glyph(text) -> bool

# 底层提取（可复用但需要微调）
extract_text_spans(page, page_num) -> List[Dict]      # 保留
_extract_text_lines(page, page_num) -> List[Dict]     # 保留
extract_drawings(page, page_num) -> Dict               # 保留（含线段合并逻辑）
_merge_horizontal_lines(lines) -> List[Dict]           # 保留
_merge_vertical_lines(lines) -> List[Dict]             # 保留
_dedup_boxes(boxes) -> List[RectTuple]                 # 保留
```

### 1.3 要删除/重写的上层逻辑

以下函数将被 4 引擎架构替代，**全部删除**：

```python
# 删除 — 被引擎 1 替代
_candidate_labels()
detect_text_fields()
_detect_table_semantic_fields()
_find_cell_for_bbox()
_find_right_neighbor_cell()
_find_bottom_neighbor_cell()
_cell_lines()
_cell_text()
_is_likely_cell_label()

# 删除 — 被引擎 3 替代
detect_checkboxes()
_find_checkbox_group_label()

# 删除 — 被引擎 4 替代
detect_table_cell_fields()

# 删除 — 被引擎 4 内部逻辑替代
detect_table_structure()   # 重写为 _build_table_grid()，内化到引擎 4

# 删除 — 被新的 detect_all 替代
detect_page()

# 保留常量但部分调整
_is_instructional_text()   # 保留但扩充前缀列表
_is_likely_running_text()  # 保留
```

---

## 2. 新增依赖

在 `backend/requirements.txt` 中新增一行：

```
pdfplumber>=0.10.0
```

---

## 3. 目标文件结构

```
backend/app/services/native/
├── __init__.py              # 不变
├── detector.py              # 重写：4 引擎 + 8 步修正 + detect_all 入口
├── pipeline.py              # 不变
├── vlm_analyzer.py          # 未来 Phase 2（本次不涉及）
└── writer.py                # 未来 Phase 3（本次不涉及）

TestSpace/
├── test_engine1_boxes.py      # 引擎 1 可视化测试
├── test_engine2_blanks.py     # 引擎 2 可视化测试
├── test_engine3_checkboxes.py # 引擎 3 可视化测试
├── test_engine4_tables.py     # 引擎 4 可视化测试
├── test_correction.py         # 8 步修正可视化测试
└── test_all_engines.py        # 全流程整合测试（所有引擎 + 修正）
```

**所有代码都写在一个 `detector.py` 文件中**，不拆分为多个文件。引擎是 `NativeDetector` 类的方法，不是独立模块。

---

## 4. 引擎 1：detect_boxes_fitz — 矢量检测主引擎

### 4.1 职责

从 PyMuPDF 的矢量数据（`page.get_drawings()`）中检测所有**矩形框和下划线**，生成候选字段列表。这是最重要的引擎，覆盖 70-80% 的字段检测。

### 4.2 方法签名

```python
def engine1_detect_boxes(
    self,
    page: fitz.Page,
    page_num: int,
    text_spans: List[Dict],
    text_lines: List[Dict],
    drawing_data: Dict,
) -> List[Dict]:
    """
    引擎 1：从 PyMuPDF 矢量数据中检测矩形框和下划线字段。

    检测对象：
    1. 表格单元格边框 — 由水平线 + 竖直线构成的网格
    2. 独立矩形框 — 非表格的单独矩形（如文本输入框）
    3. 下划线 — 水平线段，用于填写区域

    输入参数均由 detect_all() 预先提取好，引擎内部不重复提取。

    Returns:
        候选字段列表，每个字段包含：
        {
            "label": str,           # 关联的文字标签（如 "Name"）
            "label_bbox": tuple,    # 标签的精确坐标
            "fill_rect": tuple,     # 推断的填写区域 (x0, y0, x1, y1)
            "field_type": str,      # "text" | "date" | "signature"
            "page_num": int,
            "confidence": float,    # 0.0 ~ 1.0
            "options": None,        # 引擎 1 不涉及选项
            "source": "engine1_box" | "engine1_underline",
        }
    """
```

### 4.3 实现逻辑

#### 步骤 1：从 drawing_data 中提取矩形框

利用已有的 `extract_drawings()` 返回的数据。从 `drawing_data["drawings"]` 中筛选出**独立矩形框**（不是表格线的一部分）：

```python
# 筛选条件：
# - 操作类型为 "re"（rectangle）
# - 宽度 >= 30pt，高度 >= 12pt（排除装饰线和小方框）
# - 不是 checkbox 的小正方形（已由引擎 3 处理）
# - 宽高比合理：宽度 > 高度 * 1.5（排除正方形和竖条）

rects = []
for d in drawing_data["drawings"]:
    for item in d["items"]:
        if item["op"] == "re":
            bbox = item["rect"]
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w >= 30 and h >= 12 and w > h * 1.5:
                # 排除 checkbox 尺寸的小正方形
                if not (6 <= w <= 20 and 6 <= h <= 20 and abs(w - h) <= 2):
                    rects.append(bbox)
```

#### 步骤 2：从 drawing_data 中提取下划线

从 `drawing_data["horizontal_lines"]` 中筛选出**可能是填写区域的下划线**：

```python
# 筛选条件：
# - 长度 >= 40pt（排除装饰短线）
# - 不是表格的水平分隔线（后面通过表格网格排除）
# - y 位置在合理范围内（不在页面最顶部或最底部的 margin 区）

page_height = page.rect.height
underlines = []
for ln in drawing_data["horizontal_lines"]:
    length = ln["x1"] - ln["x0"]
    if length >= 40 and 50 < ln["y"] < page_height - 40:
        underlines.append(ln)
```

#### 步骤 3：为每个矩形框关联 label

对每个矩形框，在 `text_lines` 中寻找最近的标签文本：

```python
def _find_label_for_rect(self, rect, text_lines, all_rects):
    """为矩形框找到关联的标签文本。

    搜索策略（按优先级）：
    1. 矩形内部左上角的文字 — 如 018 表格的 "1. Contact's Last (family) Name *"
       条件：文字 bbox 完全在矩形内部，且位于上方 40% 区域
    2. 矩形左侧的文字 — 如 "Name:" 在框的左边
       条件：文字 bbox 右端 < rect.x0 + 5，y 中心在矩形 y 范围内，距离 < 200pt
    3. 矩形上方的文字 — 如 label 在上一行
       条件：文字 bbox 底部 < rect.y0 + 2，x 范围有重叠，垂直距离 < 30pt

    过滤规则：
    - 跳过 _is_checkbox_glyph() 返回 True 的文本
    - 跳过 _is_instructional_text() 返回 True 的文本
    - 跳过超过 200 字符的长文本（段落）
    - 如果一个文本同时是多个矩形的候选 label，只关联距离最近的
    """
```

具体实现：

```python
rx0, ry0, rx1, ry1 = rect
ry_mid = (ry0 + ry1) / 2.0
candidates = []

for ln in text_lines:
    text = ln["text"]
    if not text or self._is_checkbox_glyph(text):
        continue
    if len(text) > 200:
        continue

    lb = ln["bbox"]
    lx0, ly0, lx1, ly1 = lb
    ly_mid = (ly0 + ly1) / 2.0

    # 策略 1：矩形内部左上角文字
    if lx0 >= rx0 - 2 and lx1 <= rx1 + 2 and ly0 >= ry0 - 2 and ly1 <= ry0 + (ry1 - ry0) * 0.5:
        score = 0.0  # 最高优先级
        candidates.append((score, ln, "inside_top"))
        continue

    # 策略 2：左侧文字
    if lx1 <= rx0 + 5 and abs(ly_mid - ry_mid) <= (ry1 - ry0) / 2 + 5:
        dist = rx0 - lx1
        if 0 <= dist <= 200:
            score = 10.0 + dist
            candidates.append((score, ln, "left"))

    # 策略 3：上方文字
    if ly1 <= ry0 + 2:
        overlap_x = max(0, min(lx1, rx1) - max(lx0, rx0))
        vdist = ry0 - ly1
        if overlap_x > 10 and 0 <= vdist <= 30:
            score = 50.0 + vdist * 2.0 - overlap_x * 0.1
            candidates.append((score, ln, "above"))

if not candidates:
    return None, None, "none"

best = sorted(candidates, key=lambda x: x[0])[0]
return best[1]["text"], best[1]["bbox"], best[2]
```

#### 步骤 4：为每个下划线关联 label 并计算 fill_rect

```python
def _find_label_for_underline(self, underline, text_lines):
    """为下划线找到关联的标签文本。

    搜索策略（按优先级）：
    1. 下划线左侧同行文字 — 如 "Name ____________________"
       条件：文字 y 中心与下划线 y 的距离 < 10pt，文字右端 < 下划线起点 + 5
    2. 下划线上方文字 — 如标签在上一行
       条件：文字底部 < 下划线 y，垂直距离 < 20pt，x 范围有重叠

    fill_rect 计算：
    - 如果有左侧同行标签：fill_rect = (max(label.x1 + 2, underline.x0), underline.y - line_height, underline.x1, underline.y)
    - 如果有上方标签或无标签：fill_rect = (underline.x0, underline.y - line_height, underline.x1, underline.y)
    - line_height：从最近文字的 font_size 推算，默认 font_size * 1.3，如果无参考则用 14pt
    """
```

具体实现：

```python
ux0, ux1, uy = underline["x0"], underline["x1"], underline["y"]
candidates = []

for ln in text_lines:
    text = ln["text"]
    if not text or self._is_checkbox_glyph(text):
        continue
    if len(text) > 200:
        continue

    lb = ln["bbox"]
    ly_mid = (lb[1] + lb[3]) / 2.0

    # 策略 1：左侧同行
    if lb[2] <= ux0 + 5 and abs(ly_mid - uy) <= 10:
        dist = max(0, ux0 - lb[2])
        if dist <= 200:
            candidates.append((dist, ln, "left_inline"))

    # 策略 2：上方
    if lb[3] <= uy + 2:
        overlap_x = max(0, min(lb[2], ux1) - max(lb[0], ux0))
        vdist = uy - lb[3]
        if overlap_x > 10 and 0 <= vdist <= 20:
            candidates.append((100 + vdist, ln, "above"))

# 计算 line_height
line_height = 14.0  # 默认值
if candidates:
    # 从最近的 text_span 读取字体大小
    # （需要在 text_spans 中查找与候选 label 位置重叠的 span）
    pass  # 具体实现见下文

# 构造 fill_rect
if candidates:
    best = sorted(candidates, key=lambda x: x[0])[0]
    label_text, label_bbox, label_source = best[1]["text"], best[1]["bbox"], best[2]
    if label_source == "left_inline":
        fill_x0 = max(label_bbox[2] + 2, ux0)
    else:
        fill_x0 = ux0
else:
    label_text, label_bbox, label_source = None, None, "none"
    fill_x0 = ux0

fill_rect = (
    self._round(fill_x0),
    self._round(uy - line_height),
    self._round(ux1),
    self._round(uy + 1),  # 下划线下方留 1pt
)
```

#### 步骤 5：field_type 推断

```python
def _infer_field_type(self, label_text: str) -> str:
    """根据标签文本推断字段类型。"""
    if not label_text:
        return "text"
    lower = label_text.lower()
    if any(w in lower for w in ["date", "dob", "birth"]):
        return "date"
    if any(w in lower for w in ["signature", "sign here"]):
        return "signature"
    if any(w in lower for w in ["phone", "telephone", "fax", "tel"]):
        return "phone"
    if any(w in lower for w in ["email", "e-mail"]):
        return "email"
    if any(w in lower for w in ["zip", "postal"]):
        return "zip"
    return "text"
```

#### 步骤 6：合并输出

将矩形框检测结果和下划线检测结果合并，按阅读顺序排序（先 y 后 x）。

### 4.4 测试要点

- 008 (US Courts): 混合表格框 + 下划线 + checkbox，页面 1 上方有矩形框（Name, Phone Number, Address 等），下方有下划线（citizenship 等）
- 013 (FDIC G-FIN-5): 以下划线为主，大量 `___________` 风格的填写线
- 018 (DOL ETA-9141C): 密集表格框，几乎全是矩形单元格
- 019 (Aetna): 有彩色填充矩形（紫色标题栏、灰色分组背景），需要排除装饰性矩形

---

## 5. 引擎 2：detect_blanks — 空白区间回退引擎

### 5.1 职责

当引擎 1 检测到的字段数少于预期时，使用 pdfplumber 的字符级数据分析文本层，找出**两段文字之间的连续空白区间**作为候选填写区域。

### 5.2 方法签名

```python
def engine2_detect_blanks(
    self,
    pdf_path: str,
    page_num: int,          # 1-based
    page_rect: tuple,       # (0, 0, width, height)
    existing_fields: List[Dict],
    text_lines: List[Dict],
) -> List[Dict]:
    """
    引擎 2：使用 pdfplumber 分析字符级数据，检测文本间空白区间。

    触发条件：引擎 1 检测到的 text/date/signature 类型字段数 < 3 时启用。

    原理：
    1. 用 pdfplumber 提取页面的所有字符（chars）及其精确坐标
    2. 按行分组（y 坐标相近的字符归为同一行）
    3. 在每行内找连续空白间隔（相邻字符之间 x 距离 > 阈值）
    4. 空白间隔即为候选填写区域

    Returns:
        候选字段列表，格式同引擎 1，source="engine2_blank"
    """
```

### 5.3 实现逻辑

```python
import pdfplumber

def engine2_detect_blanks(self, pdf_path, page_num, page_rect, existing_fields, text_lines):
    fields = []

    with pdfplumber.open(pdf_path) as pdf:
        if page_num < 1 or page_num > len(pdf.pages):
            return fields
        plumber_page = pdf.pages[page_num - 1]  # 0-based index
        chars = plumber_page.chars
        if not chars:
            return fields

    # 步骤 1：按行分组
    # 将字符按 top 坐标聚类（tolerance = 3pt）
    sorted_chars = sorted(chars, key=lambda c: (round(float(c["top"]) / 3) * 3, float(c["x0"])))
    lines = []
    current_line = [sorted_chars[0]]
    for ch in sorted_chars[1:]:
        if abs(float(ch["top"]) - float(current_line[0]["top"])) <= 3:
            current_line.append(ch)
        else:
            lines.append(current_line)
            current_line = [ch]
    lines.append(current_line)

    # 步骤 2：在每行内找空白间隔
    MIN_BLANK_WIDTH = 40   # 最小空白宽度（pt）
    page_width = page_rect[2]

    for line_chars in lines:
        if len(line_chars) < 2:
            continue
        sorted_line = sorted(line_chars, key=lambda c: float(c["x0"]))
        line_top = min(float(c["top"]) for c in sorted_line)
        line_bottom = max(float(c["bottom"]) for c in sorted_line)
        line_height = line_bottom - line_top

        # 找相邻字符间的大间隔
        for i in range(len(sorted_line) - 1):
            curr_x1 = float(sorted_line[i]["x1"])
            next_x0 = float(sorted_line[i + 1]["x0"])
            gap = next_x0 - curr_x1

            if gap >= MIN_BLANK_WIDTH:
                blank_rect = (
                    self._round(curr_x1 + 1),
                    self._round(line_top),
                    self._round(next_x0 - 1),
                    self._round(line_bottom),
                )

                # 跳过与已检测字段重叠的区域
                overlaps = any(
                    self._overlap_ratio(blank_rect, f["fill_rect"]) > 0.5
                    for f in existing_fields
                )
                if overlaps:
                    continue

                # 找左侧最近的文本作为 label
                left_text_parts = []
                for c in sorted_line:
                    if float(c["x1"]) <= curr_x1 + 1:
                        left_text_parts.append(c.get("text", ""))
                left_text = "".join(left_text_parts).strip()

                if not left_text:
                    continue

                fields.append({
                    "label": left_text,
                    "label_bbox": (
                        self._round(float(sorted_line[0]["x0"])),
                        self._round(line_top),
                        self._round(curr_x1),
                        self._round(line_bottom),
                    ),
                    "fill_rect": blank_rect,
                    "field_type": self._infer_field_type(left_text),
                    "page_num": page_num,
                    "confidence": 0.55,
                    "options": None,
                    "source": "engine2_blank",
                })

        # 行末空白检测：最后一个字符到页面右边距有大空白
        last_x1 = float(sorted_line[-1]["x1"])
        right_margin = page_width - 36  # 假设右边距 36pt (0.5 inch)
        trailing_gap = right_margin - last_x1
        if trailing_gap >= MIN_BLANK_WIDTH:
            # 检查这行是否以冒号或标签结尾
            line_text = "".join(c.get("text", "") for c in sorted_line).strip()
            if line_text.endswith(":") or line_text.endswith("_"):
                blank_rect = (
                    self._round(last_x1 + 1),
                    self._round(line_top),
                    self._round(right_margin),
                    self._round(line_bottom),
                )
                overlaps = any(
                    self._overlap_ratio(blank_rect, f["fill_rect"]) > 0.5
                    for f in existing_fields
                )
                if not overlaps:
                    fields.append({
                        "label": line_text,
                        "label_bbox": (
                            self._round(float(sorted_line[0]["x0"])),
                            self._round(line_top),
                            self._round(last_x1),
                            self._round(line_bottom),
                        ),
                        "fill_rect": blank_rect,
                        "field_type": self._infer_field_type(line_text),
                        "page_num": page_num,
                        "confidence": 0.50,
                        "options": None,
                        "source": "engine2_blank",
                    })

    return fields
```

### 5.4 注意事项

- pdfplumber 的坐标系和 pymupdf 一致（原点在左上角，单位 pt）
- pdfplumber 打开 PDF 比较慢（需要解析整个文档），所以只在引擎 1 结果不足时才触发
- 每页独立处理，用 `pdfplumber.open()` 打开一次即可遍历多页
- 字符级数据中 `"text"` 字段是单个字符，需要拼接

---

## 6. 引擎 3：detect_checkboxes — Checkbox 专用引擎

### 6.1 职责

检测页面上所有 checkbox / radio button，包括分组和选项文本关联。

### 6.2 方法签名

```python
def engine3_detect_checkboxes(
    self,
    page: fitz.Page,
    page_num: int,
    text_spans: List[Dict],
    text_lines: List[Dict],
    drawing_data: Dict,
) -> List[Dict]:
    """
    引擎 3：检测 checkbox 和 radio button。

    检测来源（并集）：
    1. PyMuPDF drawings 中的小正方形（6-20pt 边长，宽高差 ≤ 2pt）
    2. PyMuPDF text_spans 中的 checkbox 字形（☐☑☒□■ 和 Wingdings 私有区字符）
    3. pdfplumber chars 中的 checkbox 字形（补充 pymupdf 可能遗漏的）

    分组规则：
    - 同一行（y 中心差 ≤ 10pt）的 checkbox 属于同一组
    - 每个 checkbox 右侧最近的非 checkbox 文本是它的选项标签
    - 整组的题干标签：组左侧或上方最近的文本

    Returns:
        候选字段列表，每个字段代表一个 checkbox 组：
        {
            "label": str,              # 题干文本（如 "Marital Status"）
            "label_bbox": tuple,
            "fill_rect": tuple,        # 整组的外包围框
            "field_type": "checkbox",
            "page_num": int,
            "confidence": float,
            "options": ["option1", "option2", ...],  # 每个选项的文本
            "checkbox_positions": [     # 每个 checkbox 的精确位置（用于写入勾选标记）
                {"bbox": tuple, "option": str},
                ...
            ],
            "source": "engine3_checkbox",
        }
    """
```

### 6.3 实现逻辑

#### 步骤 1：收集所有 checkbox 位置

```python
# 来源 A：drawings 中的小正方形
boxes = list(drawing_data.get("square_boxes", []))

# 来源 B：text_spans 中的 checkbox 字形
for span in text_spans:
    if self._is_checkbox_glyph(span["text"]):
        boxes.append(span["bbox"])

# 去重
boxes = self._dedup_boxes(boxes)
```

#### 步骤 2：按行分组

```python
# 按 y 中心排序，相近的归为同一组
ROW_GROUP_TOL = 10.0  # y 中心差 ≤ 10pt 视为同一行

groups = []
for box in sorted(boxes, key=lambda b: self._bbox_center(b)[1]):
    cy = self._bbox_center(box)[1]
    if not groups:
        groups.append([box])
        continue
    last_cy = self._bbox_center(groups[-1][0])[1]
    if abs(cy - last_cy) <= ROW_GROUP_TOL:
        groups[-1].append(box)
    else:
        groups.append([box])
```

#### 步骤 3：为每个 checkbox 找选项文本

```python
for grp in groups:
    grp_sorted = sorted(grp, key=lambda b: b[0])  # 按 x 排序
    options = []
    checkbox_positions = []

    for box in grp_sorted:
        bx1 = box[2]  # checkbox 右边界
        by_mid = self._bbox_center(box)[1]

        # 找右侧最近的非 checkbox 文本
        best_option = None
        best_dist = float("inf")
        for ln in text_lines:
            if self._is_checkbox_glyph(ln["text"]):
                continue
            lb = ln["bbox"]
            ly_mid = (lb[1] + lb[3]) / 2.0
            # 条件：在 checkbox 右侧，y 方向接近，距离合理
            if lb[0] >= bx1 - 2 and abs(ly_mid - by_mid) <= 10 and lb[0] - bx1 <= 100:
                dist = lb[0] - bx1
                if dist < best_dist:
                    best_option = ln["text"]
                    best_dist = dist

        option_text = best_option or ""
        options.append(option_text)
        checkbox_positions.append({
            "bbox": box,
            "option": option_text,
        })

    # 去重选项（保留顺序）
    options = list(dict.fromkeys(options))
```

#### 步骤 4：为每组找题干标签

复用改进后的 `_find_checkbox_group_label()` 逻辑，但放宽对长文本的限制：

```python
def _find_checkbox_group_label(self, union_bbox, text_lines):
    """
    为一组 checkbox 找到题干文本。

    搜索策略（按优先级）：
    1. 组左侧同行文本 — 如 "Check one: Lessor operates as □ individual □ company"
       条件：文字右端 ≤ 组左端 + 8，y 中心差 ≤ 14pt
    2. 组上方文本 — 如 "7. Reason for Termination - Check One:"
       条件：文字底部 ≤ 组顶部 + 2，x 范围有重叠 ≥ 18pt，垂直距离 ≤ 80pt

    注意：不再使用 _is_likely_running_text() 过滤，因为 checkbox 的题干可能
    是一段较长的问题描述（如 "Are you receiving a federal civilian annuity payment?"）。
    只过滤明确的说明性文字（_is_instructional_text）。
    """
    x0, y0, x1, y1 = union_bbox
    y_mid = (y0 + y1) / 2.0
    candidates = []

    for ln in text_lines:
        text = ln["text"]
        if not text or self._is_checkbox_glyph(text):
            continue
        if self._is_instructional_text(text):
            continue

        lb = ln["bbox"]
        ly = (lb[1] + lb[3]) / 2.0

        # 同行左侧
        if lb[2] <= x0 + 8 and abs(ly - y_mid) <= 14:
            dist_x = max(0, x0 - lb[2])
            score = dist_x + abs(ly - y_mid) * 3.0
            candidates.append((score, ln, "left_inline"))

        # 上方
        overlap_x = max(0, min(lb[2], x1) - max(lb[0], x0))
        if lb[3] <= y0 + 2 and overlap_x >= 18:
            vdist = y0 - lb[3]
            if 0 <= vdist <= 80:
                score = 100.0 + vdist * 2.0 - overlap_x * 0.05
                candidates.append((score, ln, "above"))

    if not candidates:
        return "checkbox_group", union_bbox, "fallback"

    best = sorted(candidates, key=lambda x: x[0])[0]
    return best[1]["text"], best[1]["bbox"], best[2]
```

### 6.4 关键改进点（相对于现有代码）

1. **不再过滤长文本作为 label**：现有代码用 `_is_likely_running_text()` 过滤了超过 120 字符或 14 个词的文本，但 checkbox 的题干经常很长（如 008 PDF 的 "Have you received a federal separation incentive payment in the past 5 years?"）
2. **输出 `checkbox_positions`**：每个 checkbox 的精确坐标，供后续写入勾选标记使用
3. **检测单独的 checkbox**（不成组）：如果一行只有一个 checkbox（如简单的 YES/NO 独立存在），也作为一个组输出，options 只有一个元素

---

## 7. 引擎 4：synthesize_fields_from_table_cells — 表格合成引擎

### 7.1 职责

从表格的行列网格中合成字段。这是处理密集表格表单（如 018 DOL 表格）的核心。

### 7.2 方法签名

```python
def engine4_synthesize_table_fields(
    self,
    page: fitz.Page,
    page_num: int,
    text_lines: List[Dict],
    drawing_data: Dict,
    existing_fields: List[Dict],
) -> List[Dict]:
    """
    引擎 4：从表格网格中合成字段。

    流程：
    1. 从水平线和竖直线构建表格网格（复用现有 detect_table_structure 逻辑）
    2. 遍历每个单元格，判断是 "label 单元格" 还是 "填写单元格"
    3. 为填写单元格关联最合适的 label
    4. 跳过与 existing_fields（引擎 1/2/3 已检测的）重叠的单元格

    Returns:
        候选字段列表，source="engine4_table_cell"
    """
```

### 7.3 实现逻辑

#### 步骤 1：构建表格网格

复用现有 `detect_table_structure()` 的核心逻辑（union-find 线段聚类 → 网格构建），重构为内部方法 `_build_table_grids()`：

```python
def _build_table_grids(self, drawing_data, page_num):
    """
    从水平线和竖直线构建表格网格。

    算法（和现有 detect_table_structure 一致）：
    1. 将所有 h_lines 和 v_lines 转为节点，用 bbox 表示
    2. union-find：bbox 相交（gap=2pt）的线段归为同一表格
    3. 对每组表格：
       - 提取所有 x 坐标 → cluster → grid_x
       - 提取所有 y 坐标 → cluster → grid_y
       - 构建 cells: (row, col, bbox) 列表

    Returns: List[Dict]，每个 dict 包含 grid_x, grid_y, cells, bbox, table_id
    """
    # （实现逻辑完全复用现有代码的 detect_table_structure，不再重复写出）
```

#### 步骤 2：判断单元格类型

```python
def _classify_cell(self, cell_bbox, text_lines):
    """
    判断一个单元格是 "label 单元格" 还是 "可填写单元格"。

    规则：
    - 计算单元格内的文字占用面积比
    - 如果文字面积 / 单元格面积 > 0.3 → label 单元格
    - 如果单元格内文字 ≤ 2 个字符（或为空） → 可填写单元格
    - 如果文字以冒号结尾 → label 单元格
    - 如果文字包含 * 或 § → label 单元格（018 表格中的必填标记）

    Returns:
        ("label", text) | ("fillable", text) | ("empty", "")
    """
    inside_lines = []
    for ln in text_lines:
        if self._intersects(cell_bbox, ln["bbox"], gap=-1.0):
            inside_lines.append(ln)

    if not inside_lines:
        return ("empty", "")

    combined_text = " ".join(ln["text"] for ln in inside_lines).strip()

    if len(combined_text) <= 2:
        return ("empty", combined_text)

    # 检查是否为 label 特征
    if combined_text.endswith(":") or combined_text.endswith("*"):
        return ("label", combined_text)
    if "§" in combined_text:
        return ("label", combined_text)

    # 计算文字占比
    text_bbox = inside_lines[0]["bbox"]
    for ln in inside_lines[1:]:
        text_bbox = self._bbox_union(text_bbox, ln["bbox"])
    text_area = self._bbox_width(text_bbox) * self._bbox_height(text_bbox)
    cell_area = self._bbox_width(cell_bbox) * self._bbox_height(cell_bbox)

    if cell_area > 0 and text_area / cell_area > 0.3:
        return ("label", combined_text)

    return ("fillable", combined_text)
```

#### 步骤 3：关联 label 到填写单元格

```python
def _find_label_for_cell(self, cell, table, text_lines):
    """
    为一个可填写单元格找到关联的 label。

    搜索策略（按优先级）：
    1. 同一单元格内部的文字（在上部 40% 区域）— 如 018 的 "1. Contact's Last (family) Name *"
       整个单元格既是 label 又是填写区（label 在上，空白在下）
    2. 左侧相邻单元格 — 如 "Name:" 在左列，填写区在右列
    3. 上方相邻单元格 — 如表头行
    4. 同行第一个 label 单元格 — 兜底

    Returns: (label_text, label_bbox) or (None, None)
    """
    row, col = cell["row"], cell["col"]
    cell_bbox = cell["bbox"]

    # 策略 1：单元格内部上方文字
    inside_lines = self._get_cell_text_lines(cell_bbox, text_lines)
    if inside_lines:
        combined = " ".join(ln["text"] for ln in inside_lines).strip()
        if combined and len(combined) > 2:
            # 文字在单元格上部
            text_bottom = max(ln["bbox"][3] for ln in inside_lines)
            cell_mid_y = (cell_bbox[1] + cell_bbox[3]) / 2
            if text_bottom < cell_mid_y:
                return combined, inside_lines[0]["bbox"]

    # 策略 2：左侧单元格
    left_cell = self._find_neighbor_cell(table, row, col - 1)
    if left_cell:
        cell_type, text = self._classify_cell(left_cell["bbox"], text_lines)
        if cell_type == "label":
            left_lines = self._get_cell_text_lines(left_cell["bbox"], text_lines)
            lbl_bbox = left_lines[0]["bbox"] if left_lines else left_cell["bbox"]
            return text, lbl_bbox

    # 策略 3：上方单元格
    above_cell = self._find_neighbor_cell(table, row - 1, col)
    if above_cell:
        cell_type, text = self._classify_cell(above_cell["bbox"], text_lines)
        if cell_type == "label":
            above_lines = self._get_cell_text_lines(above_cell["bbox"], text_lines)
            lbl_bbox = above_lines[0]["bbox"] if above_lines else above_cell["bbox"]
            return text, lbl_bbox

    # 策略 4：同行第一个 label 单元格
    for c in table["cells"]:
        if c["row"] == row and c["col"] < col:
            cell_type, text = self._classify_cell(c["bbox"], text_lines)
            if cell_type == "label":
                return text, c["bbox"]

    return None, None

def _find_neighbor_cell(self, table, row, col):
    """在表格中找到指定行列的单元格。"""
    for c in table["cells"]:
        if c["row"] == row and c["col"] == col:
            return c
    return None

def _get_cell_text_lines(self, cell_bbox, text_lines):
    """获取单元格内的文本行。"""
    lines = []
    for ln in text_lines:
        if self._intersects(cell_bbox, ln["bbox"], gap=-1.0):
            lines.append(ln)
    lines.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    return lines
```

#### 步骤 4：构造 fill_rect

```python
# 对于 label 在单元格内部上方的情况：
# fill_rect = 从 label 底部到单元格底部的区域
fill_rect = (
    cell_bbox[0] + 2,      # 左边界 + 内边距
    label_bottom + 2,       # label 下方
    cell_bbox[2] - 2,       # 右边界 - 内边距
    cell_bbox[3] - 2,       # 底部 - 内边距
)

# 对于 label 在左侧/上方单元格的情况：
# fill_rect = 整个填写单元格（减去内边距）
fill_rect = (
    cell_bbox[0] + 2,
    cell_bbox[1] + 2,
    cell_bbox[2] - 2,
    cell_bbox[3] - 2,
)
```

---

## 8. 8 步几何修正流水线

### 8.1 方法签名

```python
def correct_fields(
    self,
    fields: List[Dict],
    page_rect: tuple,
    text_lines: List[Dict],
    tables: List[Dict],
) -> List[Dict]:
    """
    8 步几何修正流水线，对所有引擎输出的候选字段进行统一后处理。

    输入：所有引擎输出的候选字段合并列表
    输出：修正后的字段列表
    """
```

### 8.2 各步骤详细实现

#### 步骤 1: synthesize — 合成相邻小矩形

```python
def _step1_synthesize(self, fields):
    """
    将水平相邻、y 范围高度重叠的小矩形合并为一个大字段。

    场景：某些 PDF 中一个填写区域被拆成多个小段线段（如虚线下划线）。

    规则：
    - 两个字段的 y 范围重叠 > 80%
    - 水平间距 < 5pt
    - 合并后 label 取左侧字段的 label
    - 合并后 fill_rect 取两者的 union
    """
    if len(fields) < 2:
        return fields

    merged = [fields[0]]
    for f in fields[1:]:
        last = merged[-1]
        y_overlap = self._overlap_ratio(
            (0, last["fill_rect"][1], 1, last["fill_rect"][3]),
            (0, f["fill_rect"][1], 1, f["fill_rect"][3]),
        )
        x_gap = f["fill_rect"][0] - last["fill_rect"][2]
        if y_overlap > 0.8 and 0 <= x_gap <= 5:
            last["fill_rect"] = self._bbox_union(last["fill_rect"], f["fill_rect"])
            last["confidence"] = max(last["confidence"], f["confidence"])
        else:
            merged.append(f)
    return merged
```

#### 步骤 2: carve — 切割跨列大矩形

```python
def _step2_carve(self, fields, tables):
    """
    如果一个字段的 fill_rect 跨越了表格的多列（覆盖了多个竖直网格线），
    按竖直网格线切割为多个独立字段。

    场景：引擎 1 检测到一个横跨整行的大矩形，但实际上表格有多列。

    规则：
    - 对每个字段，检查其 fill_rect 是否跨越了某个表格的竖直网格线
    - 如果是，按网格线切割，label 复制到第一个子字段，后续子字段标记为 unlabeled
    """
    result = []
    for f in fields:
        rect = f["fill_rect"]
        carved = False
        for table in tables:
            grid_x = table.get("grid_x", [])
            # 找在 rect 内部的竖直网格线
            splits = [x for x in grid_x if rect[0] + 5 < x < rect[2] - 5]
            if not splits:
                continue
            # 按网格线切割
            boundaries = [rect[0]] + sorted(splits) + [rect[2]]
            for i in range(len(boundaries) - 1):
                sub_rect = (boundaries[i], rect[1], boundaries[i + 1], rect[3])
                if self._bbox_width(sub_rect) < 15:
                    continue
                sub_field = dict(f)
                sub_field["fill_rect"] = sub_rect
                if i > 0:
                    sub_field["label"] = f"(continued) {f.get('label', '')}"
                    sub_field["confidence"] = f["confidence"] * 0.9
                result.append(sub_field)
            carved = True
            break
        if not carved:
            result.append(f)
    return result
```

#### 步骤 3: adjust — 对齐到网格线

```python
def _step3_adjust(self, fields, tables):
    """
    将 fill_rect 的边界吸附到最近的表格网格线（tolerance = 3pt）。

    场景：引擎检测到的矩形边界与表格线有微小偏移（1-3pt），导致视觉上不齐。

    规则：
    - 对 fill_rect 的 x0, x1, y0, y1 分别查找最近的网格线
    - 如果距离 ≤ 3pt，吸附到网格线
    """
    all_grid_x = set()
    all_grid_y = set()
    for table in tables:
        all_grid_x.update(table.get("grid_x", []))
        all_grid_y.update(table.get("grid_y", []))

    SNAP_TOL = 3.0

    def snap(val, grid_values):
        for gv in grid_values:
            if abs(val - gv) <= SNAP_TOL:
                return gv
        return val

    for f in fields:
        x0, y0, x1, y1 = f["fill_rect"]
        f["fill_rect"] = (
            self._round(snap(x0, all_grid_x)),
            self._round(snap(y0, all_grid_y)),
            self._round(snap(x1, all_grid_x)),
            self._round(snap(y1, all_grid_y)),
        )
    return fields
```

#### 步骤 4: nudge — 内边距微调

```python
def _step4_nudge(self, fields):
    """
    确保 fill_rect 有合理的内边距，文字不会贴着边框。

    规则：
    - 如果 fill_rect 的边界恰好在网格线上（步骤 3 吸附后），向内收缩 2pt
    - 最小内边距 2pt
    - 不改变 fill_rect 方向（确保 x0 < x1, y0 < y1）
    """
    PADDING = 2.0

    for f in fields:
        x0, y0, x1, y1 = f["fill_rect"]
        x0_new = x0 + PADDING
        y0_new = y0 + PADDING
        x1_new = x1 - PADDING
        y1_new = y1 - PADDING
        # 确保有效矩形
        if x1_new > x0_new and y1_new > y0_new:
            f["fill_rect"] = (
                self._round(x0_new),
                self._round(y0_new),
                self._round(x1_new),
                self._round(y1_new),
            )
    return fields
```

#### 步骤 5: truncate — 边界裁剪

```python
def _step5_truncate(self, fields, page_rect):
    """
    裁剪超出页面边界的 fill_rect。

    规则：
    - fill_rect 的 x0/y0 不能 < 页面左上角坐标
    - fill_rect 的 x1/y1 不能 > 页面右下角坐标
    - 裁剪后如果宽度或高度 < 10pt，删除该字段
    """
    px0, py0, px1, py1 = page_rect
    result = []
    for f in fields:
        x0, y0, x1, y1 = f["fill_rect"]
        x0 = max(x0, px0)
        y0 = max(y0, py0)
        x1 = min(x1, px1)
        y1 = min(y1, py1)
        if x1 - x0 >= 10 and y1 - y0 >= 6:
            f["fill_rect"] = (
                self._round(x0), self._round(y0),
                self._round(x1), self._round(y1),
            )
            result.append(f)
    return result
```

#### 步骤 6: offset — 坐标系偏移补偿

```python
def _step6_offset(self, fields, page: fitz.Page):
    """
    补偿 PDF 坐标系原点差异。

    某些 PDF 的 MediaBox 原点不在 (0, 0)，而是有偏移（如负坐标或非零原点）。
    pymupdf 的 page.rect 已经处理了这个问题，但 pdfplumber 的坐标可能有差异。

    规则：
    - 检查 page.rect.x0 和 page.rect.y0 是否为 0
    - 如果不为 0，对所有 fill_rect 施加偏移
    - 对于引擎 2（pdfplumber 来源的字段），坐标已经是页面坐标系，通常无需偏移
    """
    ox, oy = page.rect.x0, page.rect.y0
    if abs(ox) < 0.01 and abs(oy) < 0.01:
        return fields  # 无偏移

    for f in fields:
        x0, y0, x1, y1 = f["fill_rect"]
        f["fill_rect"] = (
            self._round(x0 - ox), self._round(y0 - oy),
            self._round(x1 - ox), self._round(y1 - oy),
        )
        if f.get("label_bbox"):
            lx0, ly0, lx1, ly1 = f["label_bbox"]
            f["label_bbox"] = (
                self._round(lx0 - ox), self._round(ly0 - oy),
                self._round(lx1 - ox), self._round(ly1 - oy),
            )
    return fields
```

#### 步骤 7: dedup — 去重

```python
def _step7_dedup(self, fields):
    """
    移除重叠字段。

    规则：
    - 如果两个字段的 fill_rect overlap_ratio > 0.7，保留 confidence 更高的
    - 如果 confidence 相同，保留 source 优先级更高的（engine1 > engine4 > engine2）
    """
    SOURCE_PRIORITY = {
        "engine1_box": 0,
        "engine1_underline": 1,
        "engine3_checkbox": 2,
        "engine4_table_cell": 3,
        "engine2_blank": 4,
    }

    # 按 confidence 降序排列
    sorted_fields = sorted(fields, key=lambda f: (
        -f.get("confidence", 0),
        SOURCE_PRIORITY.get(f.get("source", ""), 99),
    ))

    result = []
    for f in sorted_fields:
        overlaps = False
        for existing in result:
            if self._overlap_ratio(f["fill_rect"], existing["fill_rect"]) > 0.7:
                overlaps = True
                break
        if not overlaps:
            result.append(f)
    return result
```

#### 步骤 8: sort — 按阅读顺序排列

```python
def _step8_sort(self, fields):
    """
    按阅读顺序排列：先上后下，同行从左到右。

    规则：
    - 主排序：fill_rect.y0（上边界）
    - 次排序：fill_rect.x0（左边界）
    """
    return sorted(fields, key=lambda f: (f["fill_rect"][1], f["fill_rect"][0]))
```

#### 整合

```python
def correct_fields(self, fields, page, page_rect, text_lines, tables):
    """8 步几何修正流水线。"""
    fields = self._step1_synthesize(fields)
    fields = self._step2_carve(fields, tables)
    fields = self._step3_adjust(fields, tables)
    fields = self._step4_nudge(fields)
    fields = self._step5_truncate(fields, page_rect)
    fields = self._step6_offset(fields, page)
    fields = self._step7_dedup(fields)
    fields = self._step8_sort(fields)
    return fields
```

---

## 9. 整合入口：detect_all

### 9.1 detect_page 重写

```python
def detect_page(self, page: fitz.Page, page_num: int, pdf_path: str) -> Dict:
    """
    检测单页的所有字段。

    流程：
    1. 提取底层数据（text_spans, text_lines, drawings）
    2. 运行引擎 1：矢量检测（矩形框 + 下划线）
    3. 运行引擎 3：checkbox 检测
    4. 运行引擎 4：表格合成
    5. 检查是否需要引擎 2：如果 text/date/signature 类型字段 < 3，触发空白检测
    6. 合并所有引擎结果
    7. 运行 8 步几何修正
    8. 为每个字段分配 field_id

    Args:
        page: pymupdf Page 对象
        page_num: 页码（1-based）
        pdf_path: PDF 文件路径（引擎 2 需要用 pdfplumber 打开）

    Returns:
        {
            "page_num": int,
            "page_size": tuple,
            "text_spans": List[Dict],       # 底层数据，保留供后续使用
            "text_lines": List[Dict],
            "table_structures": List[Dict],
            "detected_fields": List[Dict],  # 最终字段列表
        }
    """
    # 1. 提取底层数据
    text_spans = self.extract_text_spans(page, page_num)
    text_lines = self._extract_text_lines(page, page_num)
    drawing_data = self.extract_drawings(page, page_num)
    tables = self._build_table_grids(drawing_data, page_num)
    page_rect = self._rect_tuple(page.rect)

    # 2. 引擎 1：矢量检测
    engine1_fields = self.engine1_detect_boxes(
        page, page_num, text_spans, text_lines, drawing_data
    )

    # 3. 引擎 3：checkbox
    engine3_fields = self.engine3_detect_checkboxes(
        page, page_num, text_spans, text_lines, drawing_data
    )

    # 4. 引擎 4：表格合成
    engine4_fields = self.engine4_synthesize_table_fields(
        page, page_num, text_lines, drawing_data,
        existing_fields=engine1_fields + engine3_fields,
    )

    # 5. 合并
    all_fields = engine1_fields + engine3_fields + engine4_fields

    # 6. 检查是否需要引擎 2
    non_checkbox_count = sum(
        1 for f in all_fields if f["field_type"] not in ("checkbox",)
    )
    if non_checkbox_count < 3:
        engine2_fields = self.engine2_detect_blanks(
            pdf_path, page_num, page_rect, all_fields, text_lines
        )
        all_fields.extend(engine2_fields)

    # 7. 8 步几何修正
    all_fields = self.correct_fields(all_fields, page, page_rect, text_lines, tables)

    # 8. 分配 field_id
    for idx, field in enumerate(all_fields, start=1):
        field["field_id"] = f"p{page_num}_f{idx:03d}"

    return {
        "page_num": page_num,
        "page_size": page_rect,
        "text_spans": text_spans,
        "text_lines": text_lines,
        "table_structures": tables,
        "detected_fields": all_fields,
    }
```

### 9.2 detect_all 重写

```python
def detect_all(self, pdf_path: Path) -> Dict:
    """
    检测整个 PDF 的所有字段。

    Returns:
        {
            "pdf_path": str,
            "page_count": int,
            "detected_field_count": int,
            "pages": List[Dict],  # 每页的 detect_page() 结果
        }
    """
    doc = fitz.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc, start=1):
        page_result = self.detect_page(page, page_num=i, pdf_path=str(pdf_path))
        pages.append(page_result)
    doc.close()

    total_fields = sum(len(p["detected_fields"]) for p in pages)
    return {
        "pdf_path": str(pdf_path),
        "page_count": len(pages),
        "detected_field_count": total_fields,
        "pages": pages,
    }
```

### 9.3 输出 JSON 不再包含 drawings 原始数据

注意 `detect_page()` 的返回值中**不再包含** `drawings`、`horizontal_lines`、`vertical_lines` 这些原始矢量数据。这些数据只在检测过程中内部使用，不输出到最终 JSON，以大幅减小输出体积。

如果测试脚本需要查看这些数据，可以单独调用 `extract_drawings()` 获取。

### 9.4 CLI 入口保持不变

`_main()` 函数和命令行参数保持不变，调用 `detect_all()` 即可。

---

## 10. 可视化测试工具

### 10.1 通用可视化函数

在每个测试脚本中复用的可视化工具函数。建议写一个共享的 `viz_utils.py` 放在 `TestSpace/` 下：

```python
# TestSpace/viz_utils.py

"""
可视化工具函数 — 在 PDF 页面上叠加标注。
"""
import fitz
from pathlib import Path
from typing import List, Dict, Tuple, Optional


# 颜色定义（RGB, 0-1 范围）
COLOR_GREEN = (0, 0.7, 0)          # 填写区域 fill_rect
COLOR_BLUE = (0, 0, 0.8)           # 标签 label_bbox
COLOR_RED = (0.9, 0, 0)            # checkbox
COLOR_ORANGE = (1, 0.5, 0)        # 引擎 2 空白检测
COLOR_PURPLE = (0.6, 0, 0.8)      # 表格网格线
COLOR_GRAY = (0.5, 0.5, 0.5)      # 低置信度字段
COLOR_YELLOW = (1, 0.9, 0)        # 修正前的原始位置

ALPHA_FILL = 0.15                  # 填充透明度
ALPHA_BORDER = 0.8                 # 边框透明度


def draw_field_overlay(
    page: fitz.Page,
    field: Dict,
    color: Tuple[float, float, float] = COLOR_GREEN,
    label_color: Tuple[float, float, float] = COLOR_BLUE,
    show_label: bool = True,
    show_id: bool = True,
):
    """在 PDF 页面上绘制一个字段的叠加标注。

    绘制内容：
    1. fill_rect — 半透明填充矩形 + 实线边框
    2. label_bbox — 蓝色虚线边框（如果有）
    3. 文字标注 — field_id + label 摘要（在 fill_rect 左上角）
    """
    rect = fitz.Rect(field["fill_rect"])

    # 半透明填充
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(color=color, fill=color, fill_opacity=ALPHA_FILL, width=0.8)
    shape.commit()

    # 实线边框
    shape2 = page.new_shape()
    shape2.draw_rect(rect)
    shape2.finish(color=color, width=1.0)
    shape2.commit()

    # label_bbox 蓝色虚线
    if show_label and field.get("label_bbox"):
        lb_rect = fitz.Rect(field["label_bbox"])
        shape3 = page.new_shape()
        shape3.draw_rect(lb_rect)
        shape3.finish(color=label_color, width=0.5, dashes="[2 2]")
        shape3.commit()

    # 文字标注
    if show_id:
        field_id = field.get("field_id", "")
        label_text = field.get("label", "")[:30]
        conf = field.get("confidence", 0)
        source = field.get("source", "")
        annotation_text = f"{field_id} [{source}] c={conf:.2f}\n{label_text}"

        # 在 fill_rect 左上角写标注
        text_point = fitz.Point(rect.x0, rect.y0 - 2)
        page.insert_text(
            text_point,
            annotation_text,
            fontsize=5,
            color=color,
            fontname="helv",
        )


def draw_table_grid(
    page: fitz.Page,
    table: Dict,
    color: Tuple[float, float, float] = COLOR_PURPLE,
):
    """绘制表格网格线。"""
    grid_x = table.get("grid_x", [])
    grid_y = table.get("grid_y", [])
    bbox = table.get("bbox", (0, 0, 0, 0))

    shape = page.new_shape()

    # 画水平线
    for y in grid_y:
        shape.draw_line(fitz.Point(bbox[0], y), fitz.Point(bbox[2], y))

    # 画竖直线
    for x in grid_x:
        shape.draw_line(fitz.Point(x, bbox[1]), fitz.Point(x, bbox[3]))

    shape.finish(color=color, width=0.5, dashes="[3 3]")
    shape.commit()


def draw_checkbox_positions(
    page: fitz.Page,
    field: Dict,
    color: Tuple[float, float, float] = COLOR_RED,
):
    """绘制 checkbox 组的每个独立 checkbox 位置。"""
    for cb in field.get("checkbox_positions", []):
        cb_rect = fitz.Rect(cb["bbox"])
        shape = page.new_shape()
        shape.draw_rect(cb_rect)
        shape.finish(color=color, fill=color, fill_opacity=0.2, width=1.0)
        shape.commit()

        # 写选项文本
        if cb.get("option"):
            page.insert_text(
                fitz.Point(cb_rect.x1 + 2, cb_rect.y1),
                cb["option"][:20],
                fontsize=5,
                color=color,
                fontname="helv",
            )


def save_annotated_pdf(
    input_pdf_path: str,
    output_pdf_path: str,
    page_fields: Dict[int, List[Dict]],
    page_tables: Dict[int, List[Dict]] = None,
    color_map: Dict[str, Tuple[float, float, float]] = None,
):
    """
    生成标注后的 PDF 文件。

    Args:
        input_pdf_path: 原始 PDF 路径
        output_pdf_path: 输出标注 PDF 路径
        page_fields: {page_num: [fields]} — 每页的字段列表（page_num 为 1-based）
        page_tables: {page_num: [tables]} — 每页的表格列表（可选）
        color_map: {source: color} — 按引擎来源指定颜色（可选）
    """
    if color_map is None:
        color_map = {
            "engine1_box": COLOR_GREEN,
            "engine1_underline": (0, 0.5, 0),
            "engine2_blank": COLOR_ORANGE,
            "engine3_checkbox": COLOR_RED,
            "engine4_table_cell": (0.2, 0.6, 0.8),
        }

    doc = fitz.open(input_pdf_path)

    for page_num, fields in page_fields.items():
        if page_num < 1 or page_num > len(doc):
            continue
        page = doc[page_num - 1]

        # 画表格网格（如果有）
        if page_tables and page_num in page_tables:
            for table in page_tables[page_num]:
                draw_table_grid(page, table)

        # 画字段
        for field in fields:
            source = field.get("source", "")
            color = color_map.get(source, COLOR_GREEN)

            if field.get("field_type") == "checkbox":
                draw_field_overlay(page, field, color=COLOR_RED)
                draw_checkbox_positions(page, field)
            else:
                draw_field_overlay(page, field, color=color)

    doc.save(output_pdf_path)
    doc.close()
    print(f"已保存标注 PDF: {output_pdf_path}")
```

### 10.2 引擎 1 测试脚本

```python
# TestSpace/test_engine1_boxes.py
"""
引擎 1 测试：矢量检测（矩形框 + 下划线）

用法：
    python TestSpace/test_engine1_boxes.py \
        --input TestSpace/pdf_pipeline/output/selected/native/008_xxx.pdf \
        --output TestSpace/engine1_result_008.pdf

效果：
    - 绿色半透明矩形 = 检测到的填写区域 (fill_rect)
    - 蓝色虚线框 = 关联的标签位置 (label_bbox)
    - 左上角小字 = field_id + source + confidence + label 摘要
"""
import sys
sys.path.insert(0, "backend")

import argparse
import fitz
from pathlib import Path
from app.services.native.detector import get_native_detector
from viz_utils import save_annotated_pdf


def main():
    parser = argparse.ArgumentParser(description="引擎 1 可视化测试")
    parser.add_argument("--input", required=True, help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出标注 PDF 路径")
    args = parser.parse_args()

    if not args.output:
        stem = Path(args.input).stem
        args.output = f"TestSpace/engine1_result_{stem[:20]}.pdf"

    detector = get_native_detector()
    doc = fitz.open(args.input)

    page_fields = {}
    page_tables = {}

    for i, page in enumerate(doc, start=1):
        text_spans = detector.extract_text_spans(page, i)
        text_lines = detector._extract_text_lines(page, i)
        drawing_data = detector.extract_drawings(page, i)

        fields = detector.engine1_detect_boxes(
            page, i, text_spans, text_lines, drawing_data
        )

        # 分配临时 field_id
        for idx, f in enumerate(fields, start=1):
            f["field_id"] = f"p{i}_e1_{idx:03d}"

        if fields:
            page_fields[i] = fields
        print(f"Page {i}: {len(fields)} fields (engine1)")

    doc.close()

    save_annotated_pdf(
        args.input, args.output,
        page_fields=page_fields,
        page_tables=page_tables,
    )


if __name__ == "__main__":
    main()
```

### 10.3 引擎 2 测试脚本

```python
# TestSpace/test_engine2_blanks.py
"""
引擎 2 测试：空白区间检测

用法：
    python TestSpace/test_engine2_blanks.py \
        --input TestSpace/pdf_pipeline/output/selected/native/013_xxx.pdf \
        --output TestSpace/engine2_result_013.pdf

效果：
    - 橙色半透明矩形 = 检测到的空白填写区域
    - 引擎 2 是回退引擎，此测试强制在所有页面运行（忽略触发条件）
"""
import sys
sys.path.insert(0, "backend")

import argparse
import fitz
from pathlib import Path
from app.services.native.detector import get_native_detector
from viz_utils import save_annotated_pdf


def main():
    parser = argparse.ArgumentParser(description="引擎 2 可视化测试")
    parser.add_argument("--input", required=True, help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出标注 PDF 路径")
    args = parser.parse_args()

    if not args.output:
        stem = Path(args.input).stem
        args.output = f"TestSpace/engine2_result_{stem[:20]}.pdf"

    detector = get_native_detector()
    doc = fitz.open(args.input)

    page_fields = {}

    for i, page in enumerate(doc, start=1):
        text_lines = detector._extract_text_lines(page, i)
        page_rect = detector._rect_tuple(page.rect)

        # 强制运行引擎 2（忽略触发条件）
        fields = detector.engine2_detect_blanks(
            args.input, i, page_rect,
            existing_fields=[],
            text_lines=text_lines,
        )

        for idx, f in enumerate(fields, start=1):
            f["field_id"] = f"p{i}_e2_{idx:03d}"

        if fields:
            page_fields[i] = fields
        print(f"Page {i}: {len(fields)} fields (engine2)")

    doc.close()

    save_annotated_pdf(
        args.input, args.output,
        page_fields=page_fields,
    )


if __name__ == "__main__":
    main()
```

### 10.4 引擎 3 测试脚本

```python
# TestSpace/test_engine3_checkboxes.py
"""
引擎 3 测试：Checkbox 检测

用法：
    python TestSpace/test_engine3_checkboxes.py \
        --input TestSpace/pdf_pipeline/output/selected/native/008_xxx.pdf \
        --output TestSpace/engine3_result_008.pdf

效果：
    - 红色半透明矩形 = checkbox 组的外包围框
    - 每个 checkbox 位置单独标注
    - 选项文本标注在 checkbox 旁边
"""
import sys
sys.path.insert(0, "backend")

import argparse
import fitz
from pathlib import Path
from app.services.native.detector import get_native_detector
from viz_utils import save_annotated_pdf


def main():
    parser = argparse.ArgumentParser(description="引擎 3 可视化测试")
    parser.add_argument("--input", required=True, help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出标注 PDF 路径")
    args = parser.parse_args()

    if not args.output:
        stem = Path(args.input).stem
        args.output = f"TestSpace/engine3_result_{stem[:20]}.pdf"

    detector = get_native_detector()
    doc = fitz.open(args.input)

    page_fields = {}

    for i, page in enumerate(doc, start=1):
        text_spans = detector.extract_text_spans(page, i)
        text_lines = detector._extract_text_lines(page, i)
        drawing_data = detector.extract_drawings(page, i)

        fields = detector.engine3_detect_checkboxes(
            page, i, text_spans, text_lines, drawing_data
        )

        for idx, f in enumerate(fields, start=1):
            f["field_id"] = f"p{i}_e3_{idx:03d}"

        if fields:
            page_fields[i] = fields
        print(f"Page {i}: {len(fields)} checkbox groups (engine3)")

    doc.close()

    save_annotated_pdf(
        args.input, args.output,
        page_fields=page_fields,
    )


if __name__ == "__main__":
    main()
```

### 10.5 引擎 4 测试脚本

```python
# TestSpace/test_engine4_tables.py
"""
引擎 4 测试：表格合成

用法：
    python TestSpace/test_engine4_tables.py \
        --input TestSpace/pdf_pipeline/output/selected/native/018_xxx.pdf \
        --output TestSpace/engine4_result_018.pdf

效果：
    - 紫色虚线 = 表格网格线
    - 蓝色半透明矩形 = 检测到的表格填写单元格
"""
import sys
sys.path.insert(0, "backend")

import argparse
import fitz
from pathlib import Path
from app.services.native.detector import get_native_detector
from viz_utils import save_annotated_pdf


def main():
    parser = argparse.ArgumentParser(description="引擎 4 可视化测试")
    parser.add_argument("--input", required=True, help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出标注 PDF 路径")
    args = parser.parse_args()

    if not args.output:
        stem = Path(args.input).stem
        args.output = f"TestSpace/engine4_result_{stem[:20]}.pdf"

    detector = get_native_detector()
    doc = fitz.open(args.input)

    page_fields = {}
    page_tables = {}

    for i, page in enumerate(doc, start=1):
        text_spans = detector.extract_text_spans(page, i)
        text_lines = detector._extract_text_lines(page, i)
        drawing_data = detector.extract_drawings(page, i)
        tables = detector._build_table_grids(drawing_data, i)

        fields = detector.engine4_synthesize_table_fields(
            page, i, text_lines, drawing_data,
            existing_fields=[],
        )

        for idx, f in enumerate(fields, start=1):
            f["field_id"] = f"p{i}_e4_{idx:03d}"

        if fields:
            page_fields[i] = fields
        if tables:
            page_tables[i] = tables
        print(f"Page {i}: {len(tables)} tables, {len(fields)} fields (engine4)")

    doc.close()

    save_annotated_pdf(
        args.input, args.output,
        page_fields=page_fields,
        page_tables=page_tables,
    )


if __name__ == "__main__":
    main()
```

### 10.6 几何修正测试脚本

```python
# TestSpace/test_correction.py
"""
几何修正测试：对比修正前后的变化

用法：
    python TestSpace/test_correction.py \
        --input TestSpace/pdf_pipeline/output/selected/native/018_xxx.pdf \
        --output TestSpace/correction_result_018.pdf

效果：
    - 黄色虚线框 = 修正前的原始 fill_rect
    - 绿色实线框 = 修正后的 fill_rect
    - 可直观对比修正的效果（吸附、微调、去重等）
"""
import sys
sys.path.insert(0, "backend")

import argparse
import copy
import fitz
from pathlib import Path
from app.services.native.detector import get_native_detector
from viz_utils import draw_field_overlay, COLOR_YELLOW, COLOR_GREEN


def main():
    parser = argparse.ArgumentParser(description="几何修正可视化测试")
    parser.add_argument("--input", required=True, help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出标注 PDF 路径")
    args = parser.parse_args()

    if not args.output:
        stem = Path(args.input).stem
        args.output = f"TestSpace/correction_result_{stem[:20]}.pdf"

    detector = get_native_detector()
    doc = fitz.open(args.input)

    for i, page in enumerate(doc, start=1):
        text_spans = detector.extract_text_spans(page, i)
        text_lines = detector._extract_text_lines(page, i)
        drawing_data = detector.extract_drawings(page, i)
        tables = detector._build_table_grids(drawing_data, i)
        page_rect = detector._rect_tuple(page.rect)

        # 收集所有引擎的原始结果
        e1 = detector.engine1_detect_boxes(page, i, text_spans, text_lines, drawing_data)
        e3 = detector.engine3_detect_checkboxes(page, i, text_spans, text_lines, drawing_data)
        e4 = detector.engine4_synthesize_table_fields(page, i, text_lines, drawing_data, e1 + e3)
        raw_fields = e1 + e3 + e4

        # 保存修正前的副本
        pre_correction = copy.deepcopy(raw_fields)

        # 运行修正
        corrected = detector.correct_fields(raw_fields, page, page_rect, text_lines, tables)

        # 画修正前（黄色虚线）
        for idx, f in enumerate(pre_correction):
            f["field_id"] = f"pre_{idx}"
            f["source"] = "pre_correction"
            draw_field_overlay(page, f, color=COLOR_YELLOW, show_id=False)

        # 画修正后（绿色实线）
        for idx, f in enumerate(corrected):
            f["field_id"] = f"p{i}_f{idx+1:03d}"
            draw_field_overlay(page, f, color=COLOR_GREEN)

        print(f"Page {i}: {len(pre_correction)} raw → {len(corrected)} corrected")

    doc.save(args.output)
    doc.close()
    print(f"已保存标注 PDF: {args.output}")


if __name__ == "__main__":
    main()
```

### 10.7 全流程整合测试

```python
# TestSpace/test_all_engines.py
"""
全流程整合测试：所有引擎 + 修正

用法：
    python TestSpace/test_all_engines.py \
        --input TestSpace/pdf_pipeline/output/selected/native/008_xxx.pdf \
        --output TestSpace/all_result_008.pdf

    # 批量测试所有 4 个 PDF
    python TestSpace/test_all_engines.py --batch

效果：
    - 不同颜色区分不同引擎的检测结果
    - 绿色 = 引擎 1（矩形框）
    - 深绿 = 引擎 1（下划线）
    - 橙色 = 引擎 2（空白区间）
    - 红色 = 引擎 3（checkbox）
    - 青色 = 引擎 4（表格合成）
    - 紫色虚线 = 表格网格线
"""
import sys
sys.path.insert(0, "backend")

import argparse
import json
import fitz
from pathlib import Path
from app.services.native.detector import get_native_detector
from viz_utils import save_annotated_pdf

TEST_PDFS = [
    "TestSpace/pdf_pipeline/output/selected/native/008_www.uscourts.gov_a28e907f583ea68c_ao078.pdf",
    "TestSpace/pdf_pipeline/output/selected/native/013_www.fdic.gov_9da9a88f0cfc9c18_f6830-03.pdf",
    "TestSpace/pdf_pipeline/output/selected/native/018_www.dol.gov_ca277fcb5e4db464_9141C.pdf",
    "TestSpace/pdf_pipeline/output/selected/native/019_www.aetna.com_9923d5a4a0ab537a_diabetic-supply-order-form.pdf",
]


def test_single(input_path, output_path):
    detector = get_native_detector()
    result = detector.detect_all(Path(input_path))

    # 按页分组
    page_fields = {}
    page_tables = {}
    for p in result["pages"]:
        pn = p["page_num"]
        if p["detected_fields"]:
            page_fields[pn] = p["detected_fields"]
        if p.get("table_structures"):
            page_tables[pn] = p["table_structures"]

    save_annotated_pdf(input_path, output_path, page_fields, page_tables)

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"PDF: {Path(input_path).name}")
    print(f"Pages: {result['page_count']}, Total fields: {result['detected_field_count']}")
    for p in result["pages"]:
        pn = p["page_num"]
        fields = p["detected_fields"]
        if not fields:
            continue
        by_source = {}
        for f in fields:
            src = f.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1
        print(f"  Page {pn}: {len(fields)} fields — {by_source}")

    # 保存 JSON（供调试）
    json_path = output_path.replace(".pdf", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  JSON: {json_path}")


def main():
    parser = argparse.ArgumentParser(description="全流程整合测试")
    parser.add_argument("--input", default="", help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出标注 PDF 路径")
    parser.add_argument("--batch", action="store_true", help="批量测试所有 4 个 PDF")
    args = parser.parse_args()

    if args.batch:
        for pdf_path in TEST_PDFS:
            if not Path(pdf_path).exists():
                print(f"跳过：{pdf_path} 不存在")
                continue
            stem = Path(pdf_path).stem[:20]
            output = f"TestSpace/all_result_{stem}.pdf"
            test_single(pdf_path, output)
    elif args.input:
        if not args.output:
            stem = Path(args.input).stem[:20]
            args.output = f"TestSpace/all_result_{stem}.pdf"
        test_single(args.input, args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

---

## 11. 测试 PDF 与验证标准

### 11.1 测试 PDF 列表

| ID | 路径 | 特征 | 页数 |
|----|------|------|------|
| 008 | `TestSpace/pdf_pipeline/output/selected/native/008_www.uscourts.gov_a28e907f583ea68c_ao078.pdf` | 混合表格 + 下划线 + checkbox（YES/NO），教育经历表格 | 5 |
| 013 | `TestSpace/pdf_pipeline/output/selected/native/013_www.fdic.gov_9da9a88f0cfc9c18_f6830-03.pdf` | 以下划线为主，少量 checkbox，签名区 | 3 |
| 018 | `TestSpace/pdf_pipeline/output/selected/native/018_www.dol.gov_ca277fcb5e4db464_9141C.pdf` | 密集表格，大量 checkbox（☐ 字符），多页 | 4 |
| 019 | `TestSpace/pdf_pipeline/output/selected/native/019_www.aetna.com_9923d5a4a0ab537a_diabetic-supply-order-form.pdf` | 彩色商业表单，曲线路径（c 操作），混合布局 | 1 |

### 11.2 各 PDF 特征分析

#### 008 — Federal Judicial Branch Application for Employment

- **Page 1**: 上方 4 个矩形框（Name, Phone, Address, Email），中间多组 YES/NO checkbox + 下划线
- **Page 2**: 教育经历表格（多列多行），底部 checkbox 组（Bar membership, scholastic standing）
- **矢量数据**: 185 个 `re` 操作，0 个彩色，全黑色框线
- **关键测试**: 引擎 1（矩形 + 下划线）、引擎 3（YES/NO checkbox 分组）、引擎 4（教育表格）

#### 013 — FDIC G-FIN-5 Termination Notice

- **Page 1**: 大量下划线字段（Name, Capacity, SSN, Address 等），一组 checkbox（Resigned/Discharged/Deceased/Transfer/Other），签名区
- **矢量数据**: 26 个 `re` + 9 个 `l`（线段），19 个彩色（深灰近黑的边框 → 需要颜色阈值处理）
- **关键测试**: 引擎 1（下划线检测是核心）、引擎 3（Termination Reason checkbox）

#### 018 — DOL ETA-9141C Prevailing Wage

- **Page 1**: 密集表格，每个 section (A, B, C, D) 是一个表格区域，字段标签在单元格内部上方
- **Page 2**: 大面积文本输入区（Job duties 描述框），底部 checkbox 组
- **矢量数据**: 197 个 `re` 操作，0 个彩色
- **关键测试**: 引擎 4（表格合成是核心，需要处理 label 在同一 cell 内的情况）、引擎 3（☐ 字符 checkbox）

#### 019 — Aetna Diabetes Supply Order Form

- **Page 1**: 彩色表单，紫色标题栏、灰色分组背景、曲线路径（logo/圆角矩形）
- **矢量数据**: 12 个 `re` + 84 个 `l` + 145 个 `c`（曲线），11 个彩色
- **关键测试**: 排除装饰性矩形（彩色填充），引擎 1（下划线），引擎 2（可能需要空白检测补充）

### 11.3 验证标准

每个引擎的可视化测试脚本运行后，打开输出的标注 PDF，人工检查：

| 检查项 | 标准 |
|--------|------|
| 字段不遗漏 | 所有可见的填写位置（矩形框、下划线、空白区）都被检测到 |
| 不误检 | 标题文字、说明段落、装饰线条不被标记为字段 |
| label 关联正确 | 每个字段的 label 标注与视觉上对应的文字一致 |
| fill_rect 位置准确 | 绿色框覆盖在实际应该填写的区域上，不超出边界 |
| fill_rect 大小合理 | 框的高度足以容纳一行文字，宽度覆盖整个填写区 |
| checkbox 分组正确 | 同一问题的选项归为一组，题干 label 正确 |
| checkbox 选项正确 | 每个 checkbox 的选项文本与视觉上的文字一致 |

---

## 12. 附录：测试 PDF 页面分析

### 008 Page 1 预期检测结果

```
矩形框字段（引擎 1）:
- "1. Name (Last, First, Middle Initial)" → 矩形框
- "2. Phone Number" → 矩形框
- "3. Present Address (Street, City, State, Zip)" → 矩形框（跨全宽）
- "4. Email Address" → 矩形框（跨全宽）
- "5. Other Names Previously Used..." → 矩形框（左半）
- "6. Date of Birth..." → 矩形框（右半）

Checkbox 组（引擎 3）:
- "7. Are you a U.S. Citizen?" → YES / NO + 下划线 "Country of citizenship"
- "8.a. Were you ever a federal civilian employee?" → YES / NO + 下划线 "highest civilian grade"
- "8.b. Are you receiving a federal civilian annuity payment?" → YES / NO
- "8.c. Are you receiving federal severance pay?" → YES / NO + 下划线
- "8.d. Have you received a federal separation incentive..." → YES / NO + 下划线
- "9. Do you have any relatives who are Judges..." → YES / NO + 下划线
- "10. Have you ever served on active duty..." → YES / NO

下划线字段（引擎 1）:
- citizenship 下划线
- highest civilian grade 三段下划线（Pay Plan / Grade / Step）
- former agency contact/telephone 下划线
- mo/yr received + agency contact 下划线
- names, positions, relationships 下划线
```

### 013 Page 1 预期检测结果

```
下划线字段（引擎 1）:
- "1. Individual's Name" → 长下划线（Last / First / Middle 三段）
- "2. Capacity" → 下划线
- "3. Social Security Number" → 下划线
- "a. Name" → 长下划线
- "b. Registration Number" → 下划线
- "c. Main Address" → 长下划线 + 两行额外下划线
- "5. Office of Employment Address" → 下划线 + 两行额外下划线
- "6. Date Terminated" → 下划线

Checkbox 组（引擎 3）:
- "7. Reason for Termination - Check One:" →
  Resigned* / Discharged* / Deceased / Transfer* / Other*（每个 checkbox 后跟下划线）
- "8. ...investigation..." → **Yes / No

签名区（引擎 1 下划线）:
- Date 下划线
- Print Name of Supervisor of Individual 下划线
- Signature of Supervisor of Individual 下划线
- Person to Contact for Further Information 下划线

底部（ACKNOWLEDGEMENT 部分）:
- "9. Name of Individual" → 下划线
- "10. Financial Institution Broker or Dealer Name" → 下划线
- "11. Financial Institution Broker or Dealer Address" → 下划线 + 续行
- "12. Attention" → 下划线
```

### 018 Page 1 预期检测结果

```
表格字段（引擎 4）— Section A:
- "1. Indicate the type of visa classification..." → 单元格

表格字段（引擎 4）— Section B:
- "1. Contact's Last (family) Name *" → 单元格
- "2. First (given) Name *" → 单元格
- "3. Middle Name(s) §" → 单元格
- "4. Contact's Job Title *" → 单元格
- "5. Address 1 *" → 单元格
- "6. Address 2 ..." → 单元格
- "7. City *" → 单元格
- "8. State *" → 单元格
- "9. Postal Code *" → 单元格
- "10. Country *" → 单元格
- "11. Province §" → 单元格
- "12. Telephone Number *" → 单元格
- "13. Extension §" → 单元格
- "14. Business Email Address *" → 单元格

表格字段（引擎 4）— Section C:
- "1. Legal Business Name *" → 单元格
- "2. Trade Name/DBA..." → 单元格
- "3. Address 1 *" → 单元格
- ...（类似 Section B）
- "12. Federal Employer Identification..." → 单元格
- "13. NAICS Code *" → 单元格

Section D:
- "1. Job Title *" → 单元格
- "2. Suggested SOC Occupational Code *" → 单元格
- "2a. Suggested SOC Occupation Title *" → 单元格
```

### 019 Page 1 预期检测结果

```
文本字段:
- "Your Information" 区域:
  - Date of Birth → 下划线
  - Member ID → 下划线
  - City → 下划线
  - State → 下划线
  - Phone → 下划线
  - Signature → 下划线
  - Date → 下划线

- "Your Doctor's Information" 区域:
  - Doctor Phone → 下划线
  - Doctor Fax (if available) → 下划线

- "Your Diabetes Supply Order" 区域:
  - 几行 checkbox + 文本

需要排除的装饰性矩形:
- 紫色标题栏 (fill=(0.44, 0.18, 0.57))
- 灰色分组背景 (fill=(0.95, 0.95, 0.95))
- 紫色 VISIT/MAIL TO 标签背景
```

---

