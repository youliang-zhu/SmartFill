# SmartFill v3 进展记录

> 创建时间：2026-03-23
> 定位：本文档记录从 v2 架构开始到 v3 架构确立过程中，已完成的工作内容与已做出的关键决策。
> 不包含：未来实现计划细节（那部分留给后续讨论决定）。

---

## 一、Phase 1 调试与修复阶段

### 1.1 背景

在 v2 架构的基础上，Phase 1 输出已包含：
- `text_spans`：从 PyMuPDF 提取的原始文字片段
- `text_lines`：按行合并的文字行
- `drawing_data`：矢量图形（`horizontal_lines` / `vertical_lines` / `square_boxes` / `drawings`）
- `tables`：从水平线 + 垂直线构建的表格网格（含 `cells`）

### 1.2 Phase 1.5：续行合并（Union-Find）

**问题**：ETA Form 790（004 PDF）的双语 label 跨行分布，采集到的 `text_lines` 把同一 label 切成了多行。

**实现**（在 `extraction.py` 的 `_merge_continuation_lines` 方法中）：
- 算法：Union-Find pairwise，对 `text_lines` 做邻近行合并
- 合并条件（全部满足才合并）：
  1. 行间距 / 字体高度 < `gap_ratio`（默认 0.1）
  2. 两行中心 x 坐标有重叠
  3. 上行末尾不是 checkbox 字形
  4. **矢量边界检查**：两行之间不能有 `horizontal_line` 穿过（用真实字体坐标 `char_y_top / char_y_bottom` 做检查，而非 bbox y 坐标）
  5. **背景色检查**：两行之间不能有不同颜色的填充矩形（防止跨色块合并）
- `_extract_text_lines` 增加了 `font_size`、`char_y_top`、`char_y_bottom` 三个字段（用于矢量边界检查的更精确坐标）

**结论**：Phase 1.5 保留在 `extraction.py`，作为 Phase 1 的一部分，不属于 Phase 2。

---

## 二、重构决定

### 2.1 Phase 2 的根本缺陷分析（以 004 PDF 为例）

在修复 Phase 1.5 后，继续分析 v2 的 Phase 2（label 收集）发现 4 个 bug：

1. **FLC wage 问题**：双语合并后 label 词数超过 `MAX_LABEL_WORDS=28`，被 `_is_likely_running_text` 过滤掉
2. **Yes/No 问题型 label 缺失**：Phase 2 无法识别"数字编号 + 问题句 + Yes/No 选框"三列布局
3. **设备提供问题同上**：同类型布局，同样缺失
4. **`_collect_underline_labels` 只向左和向上搜索**：漏掉了签名行下方的 label（如 "Employer's Printed Name & Title"）

### 2.2 重构决策

**决定**：推倒重做 Phase 2+，只保留 Phase 1（含 1.5）。

**原因**：Phase 2 的四个 bug 并非孤立，而是整体设计思路的问题——把"引擎分类"（underline/colon/enum/table/dotleader）当成主要分类依据，结果每种布局都需要单独 collector，漏掉的布局就是盲区。新方案改为以**几何物体分类**（线段 / 单元格 / 方框）作为驱动。

### 2.3 过度设计的识别

回顾 v2 原 plan（preprocess_plan.md），以下内容被认定为不必要：

| 内容 | 判断 |
|------|------|
| 引擎 2（pdfplumber 空白检测） | 不必要，6 个测试 PDF 都是 native 矢量，没有无线 PDF |
| 8 步几何修正流水线（synthesize/carve/adjust/nudge/offset...） | 大部分是修补 Instafill 自身引擎缺陷的补丁，我们不需要模仿 |
| Phase 3（独立 dedup 阶段） | 3 行代码，放在输出前处理即可 |
| Phase 5/6（独立 checkbox 阶段 + postprocess 阶段） | checkbox 检测和其他字段平行，不需要独立阶段 |
| `confidence` 评分体系 | AI 不需要这个精度的分数 |
| `field_type` 细分（date/phone/email/zip） | AI 从 label 文字自行推断即可 |

---

## 三、已完成的代码变更

### 3.1 文件状态

| 文件 | 操作 | 当前状态 |
|------|------|---------|
| `preprocess/extraction.py` | **维持不动** | Phase 1 全部代码（554 行），Phase 1.5 续行合并在此 |
| `preprocess/label_first.py` | **重写** | 54 行，仅保留 `detect_page_v2` / `detect_page` / `detect_all` 入口，`detected_fields: []` |
| `preprocess/legacy.py` | **删除** | 已删除（1614 行），备份为 `legacy.py.bak` |
| `preprocess/detector.py` | **修改** | 移除 `LegacyEnginesMixin` 导入和继承；类定义改为 `NativeDetector(LabelFirstMixin, ExtractionMixin, UtilityMixin)` |
| `preprocess/utils.py` | 不动 | 共用常量和几何工具函数 |
| `preprocess/types.py` | 不动 | `RectTuple`, `LabelCandidate` |

**备份文件**（保留在 preprocess 目录）：
- `label_first.py.bak`：v2 原始 1123 行版本
- `legacy.py.bak`：v2 原始 1614 行版本

### 3.2 测试基础设施

新建 `TestSpace/preprocess_test_v3/`：

| 文件 | 说明 |
|------|------|
| `common.py` | 公共工具：`TEST_PDFS`、`collect_phase1`、`collect_phase1_with_merge` |
| `test_phase1.py` | Phase 1 验证测试（支持 `--batch`/`--viz`/`--pdf`） |
| `test_phases_v3.py` | 阶段渲染测试，输出标注 PDF 到 `results/` |
| `viz_utils.py` | 软链接到 `preprocess_test_v2/viz_utils.py` |

输出目录 `TestSpace/preprocess_test_v3/results/`：
- `phase1_features/`：Phase 1 特征渲染（文本行=青蓝，水平线=橙，垂直线=紫，方框=红）
- `phase1_merge/before/`：合并前原始行（灰色）
- `phase1_merge/after/`：合并后行（绿色）
- `phase1_merge/merge_stats_*.json`：逐 PDF 的合并统计

### 3.3 Phase 1 测试结果（全部通过）

6 个测试 PDF，40 页，全部 ✓：

| PDF | 页数 | 合并前行数 | 合并后行数 | 节省 |
|-----|------|-----------|-----------|------|
| 001 FDIC (f3700-44) | 16 | 698 | 336 | 362 |
| 004 ETA-790 | 11 | 378 | 206 | 172 |
| 008 US Courts | 5 | 227 | 192 | 35 |
| 013 FDIC (f6830-03) | 3 | 132 | 65 | 67 |
| 018 DOL (9141C) | 4 | 184 | 154 | 30 |
| 019 Aetna | 1 | 59 | 45 | 14 |

---

## 四、已确定的输出 Schema（v3）

### 4.1 整体 Workflow

```
Preprocess (Phase 1 + Phase 2) → detected_fields
    ↓
VLM：纯截图输入 → 输出分组 label
    ↓
Match：VLM 分组 label × detected_fields
    ↓
LLM：填写每个字段的值
    ↓
Writer：按 fill_rect 写入 PDF
```

**核心原则**：
- `fill_rect` 坐标必须来自程序化检测（PyMuPDF 矢量数据），不依赖 VLM 估算
- 条件逻辑（"If Yes, ..."）由 LLM 通过 label 文字推断，Preprocess 不处理语义

### 4.2 三种字段类型

**类型 1：Text**
```json
{
  "field_type": "text",
  "label": "Employer Name",
  "label_bbox": [x0, y0, x1, y1],
  "fill_rect": [x0, y0, x1, y1]
}
```

**类型 2：Checkbox**
```json
{
  "field_type": "checkbox",
  "label": "Are workers covered for Unemployment Insurance?",
  "label_bbox": [x0, y0, x1, y1],
  "fill_rect": [x0, y0, x1, y1],
  "options": [
    {"text": "Yes", "bbox": [x0, y0, x1, y1]},
    {"text": "No",  "bbox": [x0, y0, x1, y1]}
  ],
  "additional_text": [
    {"label": "If Yes, provide policy number", "fill_rect": [x0, y0, x1, y1]},
    {"label": "Carrier name",                 "fill_rect": [x0, y0, x1, y1]}
  ]
}
```

说明：
- `options`：每个选项的文字 + checkbox 方框坐标（Writer 在此打勾）
- `additional_text`：条件触发的后续文本字段，可为空列表 `[]`
- "If Yes/No, ..." 的条件语义不在 Preprocess 里处理，原样保留在 label 文字里，由 LLM 推断

**类型 3：Table**（重复行型）
```json
{
  "field_type": "table",
  "label": "Work History",
  "label_bbox": [x0, y0, x1, y1],
  "columns": ["Employer", "Start Date", "End Date"],
  "rows": [
    [
      {"col": "Employer",   "fill_rect": [x0, y0, x1, y1]},
      {"col": "Start Date", "fill_rect": [x0, y0, x1, y1]},
      {"col": "End Date",   "fill_rect": [x0, y0, x1, y1]}
    ]
  ]
}
```

说明：
- 仅用于**重复行型**表格（多行代表同类实体，如多段工作经历）
- **标签-填写竖列表型**（label 列 + value 列）collapse 进 text 类型处理，不单独作为 table 输出
- LLM 输出 `rows` 对应的值列表，Writer 按坐标填每一格

### 4.3 关键设计决定汇总

| 决定 | 理由 |
|------|------|
| 不做引擎 2（pdfplumber） | 测试 PDF 全是 native 矢量，没有覆盖不到的情况 |
| 不做 8 步几何修正流水线 | 那是修补 Instafill 自身问题的补丁 |
| label-value 竖列表型表格 collapse 进 text | 简化 Preprocess，不影响下游处理 |
| `additional_text` 不标注条件逻辑 | Preprocess 不做语义推断，原样保留给 LLM |
| `options` 必须带 `bbox` | Writer 需要知道在哪里打勾 |
| `field_type` 只分 text / checkbox / table | AI 自行从 label 推断 date/phone 等细分类型 |

---

## 五、当前代码目录结构

```
backend/app/services/native/preprocess/
├── __init__.py          # 导出 NativeDetector, get_native_detector, LabelCandidate, RectTuple
├── types.py             # RectTuple, LabelCandidate
├── utils.py             # 常量 + 几何/文本工具函数
├── extraction.py        # Phase 1：文字/图形提取 + Phase 1.5：续行合并
├── label_first.py       # 入口：detect_page_v2 / detect_all（当前 detected_fields=[]，等待 Phase 2 实现）
├── detector.py          # NativeDetector(LabelFirstMixin, ExtractionMixin, UtilityMixin)
├── label_first.py.bak   # v2 原始备份
└── legacy.py.bak        # v2 原始备份

TestSpace/preprocess_test_v3/
├── common.py
├── test_phase1.py
├── test_phases_v3.py
├── viz_utils.py         # → symlink to preprocess_test_v2/viz_utils.py
└── results/
    ├── phase1_features/
    └── phase1_merge/
        ├── before/
        ├── after/
        └── merge_stats_*.json
```
