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

---

## 六、Phase 2 实现进展（2026-03-24）

### 6.1 已完成部分

Phase 2 分为两个并行收集器，均已实现并经过批量测试验证。

Phase 2A（checkbox 收集）目前运行最为稳定。收集器从 Phase 1 数据中识别 checkbox 组，流程是先收集所有 checkbox 位置（来自 `square_boxes` 和字形符号），再按空间邻近度分组，然后为每个 box 查找右侧选项文字，最后在 h/v 线围成的单元格内或水平带状区域内收集对应 label，并把多 label 的情况拆分为 question + additional_text。6 个测试 PDF 共检出 73 个 checkbox 字段，结果与人工核对一致，没有已知 bug。

存在的bug：还有部分左右label没有融合，比如问题的开头1.跟后面的句子离得太远，被识别成两段左右但是没有融合

Phase 2B（text 字段收集）也已完成，逻辑是两步生成 fill_rect：Step 1 针对短段下划线 h_line 直接生成矩形，Step 2 对剩余 label 分别计算右侧候选和下方候选，选更宽的那个。障碍物系统（h_line、v_line、深色背景条、所有文字 bbox）用于确定每个方向的边界，并在最后通过 `_shrink_rect_no_overlap` 做安全收缩，确保 fill_rect 不与任何已有文字重叠。6 个 PDF 共 574 个 text 字段，其中 4 个（008、013、018、019）完全无重叠，整体通过率良好。

存在的bug：
1. 有些checkbox离得有点距离，导致把checkbox的YES/NO识别成label
2. 有表格形态的非表格被误认为是表格，从而被这一阶段


### 6.2 存在的问题

Phase 2B 仍有两个 PDF 存在残留的重叠问题。001 号 PDF（FDIC f3700-44）有 2 处重叠，成因是页面边缘有一列竖排的页码数字（如"7 7 7 8 8 9"），其 bbox 纵向跨度很大，在水平方向上与 fill_rect 有部分交叉，但由于这个 bbox 的 x 范围并没有完全阻断 fill_rect 的生成路径，`_shrink_rect_no_overlap` 没有将其识别为有效障碍而把 rect 缩短。004 号 PDF（ETA-790）有 6 处重叠，主要出现在相邻 label 之间边界很窄的位置，fill_rect 向右或向下延伸时越界进入了相邻 label 的 bbox 区域，根本原因是障碍物检测的 y 方向容差导致某些 label bbox 未被选为边界截止点。这 8 处残留重叠是当前 Phase 2B 最主要的遗留问题，尚未修复。

### 6.3 代码结构重组

在 Phase 2 实现完成后，对 preprocess 目录做了一次整理。原先 `types.py`、`utils.py`、`extraction.py`、`label_first.py` 四个文件直接散落在 `preprocess/` 根目录下，与 `detector.py` 和 `__init__.py` 混在一起显得杂乱。这次把这四个内部实现文件统一移入新建的 `core/` 子目录，`collector/` 子目录保持不变，根目录只保留 `detector.py`（对外暴露 `NativeDetector`）和 `__init__.py`（包接口）两个面向外部的文件。所有内部 import 路径同步更新，TestSpace 里引用 `preprocess.types` 旧路径的 4 处测试文件也一并修正。重组后跑全套测试（`test_phase1`、`test_checkboxes`、`test_text_fields`、`test_phases_v3`）均通过，无新增 bug。

---

## 七、ODL_FALLBACK 统一语义（2026-04-05）

本轮 debug 后，ODL 在 preprocess 里的定位被进一步收敛并统一命名。

之前代码与实验记录里的表述容易让人误解为 “ODL 只是 checkbox 的 fallback”。这个说法已经不准确。当前更合理的抽象是：

- `ODL_FALLBACK` 是 preprocess 级别的 **文本补全信号**
- 它只参与 `label completion`
- 它不参与几何真值判断

### 7.1 当前覆盖范围

- `checkbox label`
- `checkbox additional_text.label`
- `text field label`

### 7.2 当前明确不覆盖的范围

- `fill_rect` 边界选择
- table / pseudo-table 结构判断
- Phase 1 的 `split`、`separator detection`、`continuation merge` 主规则

### 7.3 代码入口变化

当前主代码统一使用环境变量：

`SMARTFILL_ODL_FALLBACK_RAW_DIR`

它表示：

- 如果设置了该目录，preprocess 允许读取对应 PDF 的 ODL raw JSON
- 然后只在 label completion 场景里用 ODL 候选去补全 native 结果

这样做的原因是：

- PyMuPDF / native preprocess 仍然是几何真源
- ODL 提供的是更强的段落级文本聚合能力
- 两者的合理分工应当是 “native 定几何，ODL 补文本”，而不是让 ODL 接管所有判断

### 7.4 共享模块归位

为避免 `collect_text_fields.py` 继续从 `collect_checkboxes.py` 借用 ODL loader / completion helper，这些 preprocess 级共用能力已整理到：

`backend/app/services/native/preprocess/core/odl_fallback.py`

这样当前结构上的语义是明确的：

- `collector/collect_checkboxes.py`：checkbox 专属几何与归属逻辑
- `collector/collect_text_fields.py`：text field 专属几何与归属逻辑
- `core/odl_fallback.py`：两者共享的 ODL fallback 信号、raw loader 与 label completion helper

---

## 八、Text Rect Generation 重构落地（2026-04-05）

本轮对 `backend/app/services/native/preprocess/collector/collect_text_fields.py` 做了一次局部重构，目标是把 text field 的 `right_rect / below_rect` 生成逻辑从 “大候选框 + shrink 回收” 改成更直接的 obstacle-aware candidate construction。

### 8.1 改动边界

本次只修改 text field 路径：

- `Channel 3: Remaining`
- `Separator-Aware Allowed Region Refinement`

未改动：

- Phase 1 merge
- ODL fallback 行为
- checkbox 收集逻辑

### 8.2 新的 rect 生成方式

- `below_rect`
  - 从 `label.x0` 出发
  - 先用窄探针向下找最近底边
  - 再在该高度内向右找最近右边界
  - 直接生成合法候选，不再先铺大框再 shrink

- `right_rect`
  - 以接近 label 等高的条形候选为基线
  - 允许少量上下微调和轻微降高
  - 如果简单变体都不理想，就让 `below_rect` 自然胜出

- 候选选择
  - 直接比较合法 `right_rect` / `below_rect` 的实际面积
  - 面积相等时 `right_rect` 优先

### 8.3 collision 兜底同步收紧

末尾的全局 collision 兜底从只避开其它 `fill_rect`，扩大为同时避开：

- 其它 field 的 `fill_rect`
- 其它 field 的 `label_bbox`

### 8.4 本轮验证

- `PYTHONPATH=backend ./venv/bin/python TestSpace/preprocess_test_v3/test_text_fields.py --pdf 013 --json`
- `PYTHONPATH=backend ./venv/bin/python TestSpace/preprocess_test_v3/test_text_fields.py --batch`
- `SMARTFILL_ODL_FALLBACK_RAW_DIR=... PYTHONPATH=backend ./venv/bin/python TestSpace/preprocess_test_v3/test_text_fields.py --pdf 008 --json`

关键结果：

- `013 p1 T7 (1. Individual’s Name)` 不再覆盖 `T8 (Last First)`
- 启用 ODL fallback 时，`008 p2` 第 15 题长 label 仍保持完整
- 当前批量几何自检下，`001 / 008 / 013 / 018 / 019` 的 text `fill_rect -> other label_bbox` 重叠为 `0`

残留：

- `004 p9` 免责声明密集区仍有 2 处 text `fill_rect -> other label_bbox` 重叠，后续还需要单独处理
