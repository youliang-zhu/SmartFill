
# 验收标准与已知 Bug 记录

本文件记录每个阶段的期望输出，以及截至目前具体发现过的 bug 实例。
后续代码每次迭代后，需对本文档列出的所有具体字段逐一验证，确认 bug 不复现。

---

# 阶段1：提取所有 label 字段（Phase 1 + Phase 1.5）

**期望**：每个表单字段的 label 文字被完整提取为一条 merged_line，不被截断、不被拆分。

## bug1：编号前缀与正文没有合并

**描述**：部分 label 的开头编号（如 "1."、"a."）与右侧正文在 PDF 内间距过大，Phase 1.5 续行合并逻辑不处理横向拼接，导致编号单独成一行，正文另成一行，两者没有被融合成一条完整 label。

**具体实例**：尚未在6个测试 PDF 中确认到该 bug 的具体字段（Phase 1.6 的 `_merge_left_right` 已处理了短编号前缀的情况，当前测试中未发现遗漏）。

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