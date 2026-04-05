
# 验收标准与已知 Bug 记录

本文件记录每个阶段的期望输出，以及截至目前具体发现过的 bug 实例。
后续代码每次迭代后，需对本文档列出的所有具体字段逐一验证，确认 bug 不复现。

---

# 阶段1：提取所有 label 字段（Phase 1 + Phase 1.5）

**期望**：每个表单字段的 label 文字被完整提取为一条 merged_line，不被截断、不被拆分。

## bug1：编号前缀与正文没有合并

**描述**：部分 label 的开头编号（如 "1."、"a."）与右侧正文在 PDF 内间距过大，Phase 1.5 续行合并逻辑不处理横向拼接，导致编号单独成一行，正文另成一行，两者没有被融合成一条完整 label。

### 实例 bug1-1（未完全修复，已做一次阈值调整）
- **PDF**：001 (f3700-44.pdf)，第 6 页
- **字段**：checkbox group_id=1 上方题干，期望为 `c. Lessor has not received any written complaints or otherwise become aware of any problems with respect to that water quality.`
- **Bug 时效果**：Phase 1 输出中该题干被拆成两块：`c. quality.` 和 `Lessor has not received any written complaints or otherwise become aware of any problems with respect to that water`。后续 checkbox 收集阶段只拿到了左侧短块，导致 `label_bbox` 过小且偏左。
- **根因**：原始 PDF 文本层本身把这句画成三段（`c.` / 长句 / `quality.`）；Phase 1.5 先把 `c.` 与 `quality.` 纵向合并为 `c. quality.`，但 Phase 1.6 `_merge_left_right` 只允许长度 `≤ 10` 的左侧碎片继续向右融合，因此 `c. quality.`（11 字符）被卡住，没有再与右侧长句合并。
- **已做改动**：将 `backend/app/services/native/preprocess/core/extraction.py` 中 Phase 1.6 `_merge_left_right` 的短片段阈值从 `10` 提高到 `15`。
- **验证结果**：重新运行 `python3 TestSpace/preprocess_test_v3/test_checkboxes.py --pdf 001 --json` 后，Phase 1 确实把原先分开的两块进一步合并成了一条更长的 merged_line，但结果仍不正确，当前输出变为 `c. quality. Lessor has not received any written complaints or otherwise become aware of any problems with respect to that water`，顺序错误，且末尾 `quality.` 仍未落在正确句尾。因此该 bug 仅部分缓解，尚未完全修复。

### 实例 bug1-2（已修复）
- **PDF**：018 (9141C.pdf)，第 1 页
- **字段**：
  - `7. City *` 与 `8. State *`
  - `5. City *` 与 `6. State *`
- **Bug 时效果**：Phase 1 输出把它们错误合并成单条 merged_line：`7. City * 8. State *`、`5. City * 6. State *`
- **根因**：`_merge_left_right()` 只看“短左片段 + 同行右侧最近 label”，未检查两者之间是否存在竖向分隔线，因此跨列误拼。
- **修复**：为 `_merge_left_right()` 增加竖向分隔检查。若两条同行文字之间存在：
  - `vertical_lines`
  - 竖向深色填充边界
  则拒绝左右融合。
- **验证结果**：重新运行 `PYTHONPATH=backend ./venv/bin/python TestSpace/preprocess_test_v3/test_text_fields.py --pdf 018 --json` 后，page 1 已恢复为独立字段：`7. City *`、`8. State *`、`5. City *`、`6. State *`。

### 实例 bug1-3（已修复）
- **PDF**：018 (9141C.pdf)，第 1 页
- **字段**：`13. Extension §` 与 `14. Business Email Address *`
- **Bug 时效果**：即使不经过左右融合，这两段在原始 PDF 文本层里就已经是一条 line，Phase 1 原样输出为 `13. Extension § 14. Business Email Address *`
- **根因**：PyMuPDF 原始 `line` 跨过了中间列分隔；当前 Phase 1 只有“合并”逻辑，没有“按分隔线拆原始 line”的逻辑。
- **修复**：在 Phase 1 中新增“按竖向分隔线拆 raw line”的前置步骤。若单条 line 跨过竖向分隔线，且分隔线左右两侧都像独立字段前缀（如 `13.` / `14.`），则先拆成两条，再进入后续 merge。
- **验证结果**：重新运行 `PYTHONPATH=backend ./venv/bin/python TestSpace/preprocess_test_v3/test_text_fields.py --pdf 018 --json` 后，page 1 已恢复为独立字段：`13. Extension §`、`14. Business Email Address *`。

**期望效果**：merged_lines 中 "1." 和后续文字合并为 "1. Employer's Name and Address"。
**当前 bug 效果**：merged_lines 中出现 text="1."（单独一条）和 text="Employer's Name and Address"（另一条）。

---

# 阶段2：找到所有 checkbox 并收集 label 与 additional_text

**期望**：
- 每个 checkbox 组关联到正确的 label（通常在左侧）
- "Yes"/"No"/"Male"/"Female" 等简短选项文字进入 `options[].text`
- "If yes, ..."、"If no, ..." 等条件说明长句进入 `additional_text[].label`
- additional_text 中每一条都有对应的 fill_rect（用于后续填写）

## bug2：表格形态的区域被误识别为表格单元格

**描述**：部分 PDF 中存在由水平线和垂直线围成的区域，视觉上像表格，但实际是普通分节布局（如标题行 + 内容区）。这些区域被 `_find_enclosing_cell` 识别为封闭单元格，导致 checkbox 的 label 搜索被限制在错误的范围内，漏掉正确 label 或返回空。

**具体实例**：尚未确认到具体复现字段，已知该风险存在于多条 h_line + v_line 密集的页面（如 004 PDF p1 的复杂网格区）。

**期望效果**：checkbox 正确找到其左侧 label。
**当前 bug 效果**：label 为空，或 label 被错误地来自相邻单元格的文字替代。

## bug3：checkbox 的 YES/NO 被当成 label

**描述**：当 checkbox 组与其左侧正式 label 之间距离较远（超出水平搜索容差），`_find_labels_for_group` 找不到真正的 label，可能将选项文字 "YES NO" 误填入 label 字段。

**具体实例**：在当前6个测试 PDF 的批量运行中未发现实际复现，但理论风险存在。

**期望效果**：label="16. Were you employed here before?"，options=["YES","NO"]。
**当前 bug 效果**：label="YES NO"，options=[]（或类似错误）。

## bug4：additional_text 缺失

**描述**：`_find_option_text` 在搜索每个 checkbox 右侧的选项标签时，词数阈值设置不当，把本应属于 `additional_text` 的条件说明长句（如 "If yes, provide in Section 21 the date..."）误当成选项文字消耗掉，导致后续 `_find_labels_for_group` 找不到这些文字，`additional_text` 返回空列表。

### 实例 bug4-1（已修复）
- **PDF**：008 (ao078.pdf)，第 1 页
- **字段**：checkbox group_id=1，label="7. Are you a U.S. Citizen?"
- **期望**：`additional_text=[{"label": "If no, give the Country of your citizenship", ...}]`
- **Bug 时效果**：`additional_text=[]`，"If no, give the Country of your citizenship" 被放入了 NO checkbox 的 `options[1].text`
- **根因**：该句恰好 8 个词，当时词数阈值为 `> 8`，未被过滤
- **修复**：将 `_find_option_text` 中词数上限从 8 改为 5（`> 5` 才跳过）

### 实例 bug4-2（已修复）
- **PDF**：008 (ao078.pdf)，第 5 页
- **字段**：checkbox group_id=1，label="18. During the last 7 years, have you been convicted, imprisoned, on probation, or on parole? ..."
- **期望**：`additional_text=[{"label": "If yes, provide in Section 21 the date, explanation of violation, place of occurrence, and name/address of police dept or court.", ...}]`
- **Bug 时效果**：`additional_text=[]`，上述长句被放入了 NO checkbox 的 `options[1].text`
- **根因**：词数阈值为 `> 8`，该句 25 词，但 NO box 右边恰好在该文字 x0 范围内（gap_x < 120px）
- **修复**：同实例 bug4-1，阈值改为 5

### 实例 bug4-3（已修复）
- **PDF**：008 (ao078.pdf)，第 5 页
- **字段**：checkbox group_id=2，label="19. Have you been convicted by a military court-martial in the past 7 years?"
- **期望**：`additional_text=[{"label": "If yes, provide in Section 21 the date, explanation of violation, place of occurrence, and name/address of military authority or court.", ...}]`
- **Bug 时效果**：`additional_text=[]`
- **修复**：同 bug4-1

---

# 阶段3：给所有 label 贴上 fill_rect（Phase 2B）

**期望**：每个 text 字段的 fill_rect 不与页面上任何已有文字、label、线条、深色背景条重叠。

## bug5：fill_rect 与页码竖排文字列重叠

**描述**：部分 PDF 页面右侧有竖向排列的章节页码数字（如 "7 7 7 8 8 9"），其 bbox 纵向跨度很大但横向极窄（约 8px 宽）。fill_rect 向右延伸时障碍物检测未能把这类文字识别为右边界的截止点，导致 fill_rect 覆盖了这些页码列。

### 实例 bug5-1（未修复）
- **PDF**：001 (f3700-44.pdf)，第 2 页
- **字段**：text field，label="1. Conflicts of Interest 2. Releases for Less than..."
- **fill_rect（当前）**：[100.8, 442.5, 612.0, 454.8]
- **冲突对象**：label_bbox=[544.3, 366.5, 551.9, 443.8]，text="7 7 7 8 8 9"（页码列）
- **期望效果**：fill_rect 右边界不超过 x=544（页码列左边界），即 fill_rect 应被页码列截断

### 实例 bug5-2（未修复）
- **PDF**：001 (f3700-44.pdf)，第 2 页
- **字段**：text field，label="I. Purpose II. Applicability III. Definitions IV. ..."
- **fill_rect（当前）**：[100.8, 621.7, 612.0, 734.4]
- **冲突对象**：label_bbox=[541.8, 509.5, 554.3, 623.1]，text="11 11 11 13 13 15 16 16 16"（页码列）
- **期望效果**：fill_rect 右边界不超过 x=541

## bug6：fill_rect 向右/向下延伸越过相邻 label

**描述**：PDF 004 中各字段之间排列紧密，fill_rect 向右或向下延伸时，由于障碍物检测的 y 方向容差，未能把紧邻的下一个 label 的 bbox 识别为边界截止点，导致 fill_rect 进入相邻字段的 label 区域。

### 实例 bug6-1（未修复）
- **PDF**：004 (790.pdf)，第 1 页
- **字段**：text field，label="(Print or type in each field block – To ..."
- **fill_rect（当前）**：[16.7, 104.9, 305.2, 128.0]
- **冲突对象**：label_bbox=[22.1, 126.9, 290.6, 160.2]，label="1. Employer's and/or Agent's Name and Address..."
- **期望效果**：fill_rect 底边不超过 y=126.9（下方 label 的顶边）

### 实例 bug6-2（未修复）
- **PDF**：004 (790.pdf)，第 1 页
- **字段**：text field，label="a. SOC (ONET/OES) Occupational Title / T..."
- **fill_rect（当前）**：[307.2, 217.8, 454.5, 240.7]
- **冲突对象**：label_bbox=[312.7, 239.7, 590.9, 262.6]，label="6. Address of Order Holding Office..."
- **期望效果**：fill_rect 底边不超过 y=239.7

### 实例 bug6-3（未修复）
- **PDF**：004 (790.pdf)，第 1 页
- **字段**：text field，label="d) E-mail Address / Dirección de Correo ..."
- **fill_rect（当前）**：[16.7, 331.7, 305.2, 347.9]
- **冲突对象**：label_bbox=[22.1, 346.8, 296.4, 359.3]，label="2. Address and Directions to Work Site..."
- **期望效果**：fill_rect 底边不超过 y=346.8

### 实例 bug6-4（未修复）
- **PDF**：004 (790.pdf)，第 1 页
- **字段**：text field，label="2. Address and Directions to Work Site..."（右侧列）
- **fill_rect（当前）**：[307.2, 346.0, 597.4, 358.6]
- **冲突对象**：label_bbox=[312.7, 357.3, 560.0, 369.8]，label="7. Clearance Order Issue Date..."
- **期望效果**：fill_rect 底边不超过 y=357.3

### 实例 bug6-5（未修复）
- **PDF**：004 (790.pdf)，第 1 页
- **字段**：text field，label="From / Desde:"
- **fill_rect（当前）**：[307.2, 460.1, 464.8, 472.7]
- **冲突对象**：label_bbox=[312.7, 471.3, 557.6, 484.0]，label="10. Number of Workers Requested..."
- **期望效果**：fill_rect 底边不超过 y=471.3

### 实例 bug6-6（未修复）
- **PDF**：004 (790.pdf)，第 1 页
- **字段**：text field，label="12. Anticipated range of hours for diffe..."
- **fill_rect（当前）**：[306.4, 621.4, 598.7, 644.3]
- **冲突对象**：label_bbox=[312.7, 643.3, 536.6, 655.8]，label="13. Collect Calls Accepted from:..."
- **期望效果**：fill_rect 底边不超过 y=643.3

---

# 阶段4：组合 text label+rect 以及 checkbox text+rect

**期望**：最终输出的 `detected_fields` 中，text 类型字段包含完整 label 和不越界的 fill_rect；checkbox 类型字段包含正确 label、所有 options、以及完整的 additional_text 列表（每条附带 fill_rect）。

---

# 附录：`/tmp` 已验证有效方案与主代码迁移状态（2026-04-05）

本节记录本轮 debug 中在 `/tmp` 临时实验里验证过、且效果明确为正向的方案，避免后续迁移时丢失上下文。

说明：
- “已迁移”表示当前主代码中已有对应实现。
- “部分迁移”表示只迁移了其中一部分，仍有关键缺口。
- “未迁移”表示方案仍只存在于 `/tmp` 实验脚本中。

| 方案 | `/tmp` 验证证据 | 主代码迁移状态 | 当前缺口 |
|------|------------------|----------------|---------|
| `checkbox polluted-label split strategy`：把污染组分为 `leading option pollution` / `trailing option pollution`；`leading` 组优先向上找问题 label，`trailing` 组只裁掉尾部 option 污染；同时允许 ODL 修补 option / additional / completion | `/tmp/odl_checkbox_experiment/checkbox_pollution_experiments.py`、`/tmp/odl_checkbox_experiment/checkbox_pollution_experiments.json`、`/tmp/odl_checkbox_experiment/manual_review/`。该策略在 `001 p8`、`004 p5/p6`、`008 p1` 上人工复核后效果最好。 | **已迁移** | 该主线已落在 `backend/app/services/native/preprocess/collector/collect_checkboxes.py`，包括 `_pollution_mode`、`_find_clean_label_above`、`_strip_trailing_option_tail`、`_extract_odl_row_metadata`、`_find_odl_completion_candidate` 等。 |
| `checkbox additional priority rect`：additional label 不再复用“最近 h_line -> 1pt 细线 rect”，而是生成真实可填写区域；该 rect 应作为高优先级保护区，优先于普通 text field | `/tmp/odl_checkbox_priority_experiment/008_p1_checkbox_priority_summary.json`。例如 `008 p1 G5-A1` 在实验里从细线 rect 变为 `[339.84, 367.63, 590.4, 385.62]`。 | **已迁移（ODL 启用时）** | 主代码已在 `backend/app/services/native/preprocess/collector/collect_checkboxes.py` 中增加 additional rect 后处理；但如果未启用 ODL raw dir，某些依赖 ODL completion 的页面仍只能保持 baseline checkbox 结果。 |
| `checkbox additional rect` 的边界计算：right / below 双候选取面积更大者；左边界不应比 additional label 更靠左；边界需同时考虑 `v_lines`、`h_lines`、横向阴影条、竖向黑色填充条 | `/tmp/odl_checkbox_priority_experiment/batch_20260404T200655Z/summary.json` 及对应 overlay。该轮实验修正了 `008 p1` 的 `G1-A1 / G4-A1 / G5-A1 / G6-A1 / G8-A1 / G9-A1` 越过右侧黑色边界的问题。 | **已迁移（ODL 启用时）** | 主代码已迁入 additional rect 的几何后处理；后续仍需继续观察不同 PDF 上是否存在新的过度保守裁剪。 |
| `ODL completion -> absorbed continuation lines consume`：当 checkbox 借助 ODL 把主问题补全后，被补全覆盖的原始续行也要一起 consumed，避免后续再被 `Phase 2B` 生成为独立 text field | `/tmp/odl_checkbox_priority_experiment/008_p1_checkbox_priority_summary.json`。实验中 `in the past 5 years?` 与 `employees of the United States Courts?` 被 absorbed 后，不再出现在 text fields 中。 | **已迁移（ODL 启用时）** | 主代码现已在 checkbox 后处理中吸收这些续行；但该行为同样依赖 ODL completion 被触发。 |
| `text separator-aware allowed region`：每个 text label 的 rect 只能落在自己的允许区域里；允许区域同时受矢量线、表格边框、横向阴影条、竖向黑色填充条、同行下一个 label 的 `x0`、同列下一个 label 的 `y0` 共同约束 | `/tmp/text_rect_separator_experiment.py`、`/tmp/text_rect_separator_experiment/004_p1_separator_aware_text_rects.json`。最早用于修复 `004 p1 T5` 跑到右栏的问题。 | **已迁移** | 已迁移到 `backend/app/services/native/preprocess/collector/collect_text_fields.py`，包括 `_extract_dark_vertical_edges`、`_extract_dark_horizontal_edges`、`_find_vertical_edge`、`_find_column_right_edge`，以及 `Separator-Aware Allowed Region Refinement` 主逻辑。 |
| `text rect collision resolution`：在 allowed-region 之后继续复用正式代码的两步碰撞消解（同行裁剪 + 全局 shrink） | `/tmp/text_rect_separator_experiment.py` 与 batch 结果 `/tmp/text_rect_separator_experiment/batch_text_20260405T101611Z/summary.json`。该轮实验把 batch overlap 从 `26` 压到 `1`。 | **已迁移** | 主代码 `collect_text_fields.py` 末尾已保留并继续使用这两步冲突消解。 |

## 当前主代码与历史状态补充

- 当前 `git log` 中与本轮相关的最近提交可见：
  - `487b560 stable checkbox process`
  - `597433c Add optional ODL-backed checkbox label fallback`
  - `33e1661 unstable fill rect`
- 其中：
  - `checkbox polluted-label split strategy` 属于已落入当前 `collect_checkboxes.py` 的主逻辑。
  - `text separator-aware allowed region + collision resolution` 已迁到当前 `collect_text_fields.py`，但截至 2026-04-05 仍处于本地未提交状态。
  - `checkbox additional priority rect` 与 `absorbed continuation lines consume` 已迁入当前 `collect_checkboxes.py`，但属于 ODL 启用时的增强路径。

## 后续迁移优先级建议

1. 继续做批量回归
- 重点看 `008`、`001`、`004`，确认 high-priority checkbox additional rect 在 ODL 启用的完整链路里稳定保护普通 text field。

2. 评估是否要把 ODL raw dir 配置前移到统一测试入口
- 当前 `text_fields` 侧对 checkbox 的 ODL 增强依赖环境变量；如果测试时不带该变量，会看到 baseline 行为。

3. `ODL_FALLBACK` 语义统一（2026-04-05）
- 当前主代码已不再把 ODL 视为 “checkbox 专属 fallback”。
- `ODL_FALLBACK` 的语义是：当 native preprocess 的程序化文本分组不完整时，允许用 ODL 的段落/文本块结果做 **label completion**。
- 该信号当前覆盖：
  - `checkbox label`
  - `checkbox additional_text.label`
  - `text field label`
- 该信号当前**不**覆盖：
  - `fill_rect` 边界几何
  - table/grid 结构判定
  - Phase 1 的 split / separator / continuation merge 主逻辑
- 当前统一入口环境变量为 `SMARTFILL_ODL_FALLBACK_RAW_DIR`。
- 这样做的原因是：ODL 在本项目中属于“文本补全信号”，不是“几何真值信号”。

## 附录：当前必须考虑的分隔情况（2026-04-05）

当前 preprocess 在做 `merge`、`split`、`fill_rect` 选边界时，至少应把下面这些情况视为“硬分隔”或“优先级很高的分隔信号”：

1. `horizontal_lines`
- 用于阻止跨行 continuation merge
- 也用于约束向下扩展的 rect

2. `vertical_lines`
- 用于阻止同行 label 跨列左右融合
- 也用于限制向右扩展的 rect

3. 表格边框 / 单元格列边界
- 本质上通常来自 `horizontal_lines + vertical_lines`
- 不能跨单元格合并 label，也不能让 rect 穿过列边界

4. 横向深色填充边界
- 例如黑色/深灰色横条、表头色块底边
- 既可能是 continuation merge 的隐式边界，也可能是 rect 的底边约束

5. 竖向深色填充边界
- 例如黑色细竖条、视觉上的列分隔阴影边
- 不能跨越去做左右 merge，也不能让 rect 超过它

6. 相邻 label 的几何位置
- 同行右侧下一个 label 的 `x0` 是当前 rect 的天然右边界
- 同列下一个 label 的 `y0` 是当前 rect 的天然下边界

7. 不同背景色区域
- 如果两行处于不同填充底色区域，默认应拒绝 continuation merge
- 这已经在 Phase 1.5 中作为跨色块保护生效
