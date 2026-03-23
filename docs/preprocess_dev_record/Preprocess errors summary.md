# Preprocess Errors Summary (008 PDF, Page 1)

> 文档定位：预处理阶段错误现象与修复过程的调试记录文档。  
> 记录范围：问题现象、复现证据、根因分析、修复动作与验证结果。  
> 排除范围：不承载长期计划和规范性方案（此类内容写入 `preprocess_plan.md`）。  
> 同步规则：仅在 bug 全部修复且方案架构确定后，再将稳定结论同步到 `preprocess_plan.md`。  

## 1. 查证范围与结论

本次仅针对你反馈的 `008_www.uscourts.gov_a28e907f583ea68c_ao078.pdf` 第 1 页进行逐条核验。  
核验依据：

- 可视化与结构化输出：`TestSpace/preprocess_results/05_integration/all_result_008_www.uscourts.gov_a28.json`
- 原始 PDF 文本坐标（`text_lines`）
- 检测器代码路径：`backend/app/services/native/detector.py`

结论：你描述的主要问题均可复现且成立（你后续撤回的 `8.c` 右侧 `If yes, give former agency contact/telephone` 未计入错误）。

---

## 2. 已确认问题（含证据与根因）

### E-001：`1. Name` 与 `2. Phone Number` 被合并为一个字段

**现象（成立）**

- 当前只生成 1 个字段：
  - `field_id = p1_f001`
  - `source = engine4_table_cell`
  - `label = "1. Name (Last, First, Middle Initial) 2. Phone Number"`
  - `fill_rect = (20.6, 115.2, 591.6, 127.1)`（整行一整块）

**证据**

- Page 1 表格结构为 `4 rows x 1 col`，`grid_x = [18.6, 593.6]`，没有中间列分割。
- 同一行文本同时包含：
  - `1. Name (Last, First, Middle Initial)`（x=21.6-139.7）
  - `2. Phone Number`（x=369.4-429.6）

**根因追溯**

- `_build_table_grids()` 只基于矢量横/竖线建网格，当前页未形成可识别的中间竖线，因此该行被建成单列单元格。
- `engine4_synthesize_table_fields()` 对单元格 1:1 产出字段，缺少“同单元格内多编号标签（1./2.）拆分”能力。

---

### E-002：第 5 点 `Other Names Previously Used for Employment Purposes` 未生成可填写字段

**现象（成立）**

- Page 1 没有任何 `detected_fields` 的 `label` 包含 `Other Names Previously Used...`。
- 该区域没有独立 `fill_rect`。

**证据**

- 原文存在该行：  
  `5. Other Names Previously Used for Employment Purposes`（y=190.7-201.6）。
- 对应表格第 4 行（row=3）单元格分类结果为：
  - `cell_bbox = (18.6, 189.7, 593.6, 235.0)`
  - `_classify_cell(...) -> "label"`
  - 合并文本：`5... 6... GENERAL`

**根因追溯**

- `engine4_synthesize_table_fields()` 对 `cell_type == "label"` 的 cell 直接 `continue`，不生成字段。
- 第 5/6 项与 `GENERAL` 落在同一个大 cell，导致“含标签但可填写”的混合 cell 被整体判为 label 后丢弃。

---

### E-003：第 7 点 `Are you a U.S. Citizen?` 的 checkbox 组标签被错配成 `GENERAL`

**现象（成立）**

- 对应字段：
  - `field_id = p1_f005`
  - `source = engine3_checkbox`
  - `label = "GENERAL"`（应为 `7. Are you a U.S. Citizen?`）
- 该组 checkbox 的 `options = [YES, NO]`，几何位置本身是对的，但组标签错了。

**证据（打分复现）**

- `_find_checkbox_group_label()` 候选中：
  - `GENERAL`（above）得分约 `112.44`
  - `7. Are you a U.S. Citizen?`（left_inline）得分约 `137.00`
- 由于分数更低，最终选中了 `GENERAL`。

**根因追溯**

- `left_inline` 评分对“左侧距离”过于敏感；当 checkbox 区域在页面中部、题干在左侧较远时，会被“上方短标题”抢占。
- 当前策略只选单个最佳候选，无“标题词过滤/section header 降权”。

---

### E-004：第 8.d 标签缺后半句 `in the past 5 years?`

**现象（成立）**

- 对应字段：
  - `field_id = p1_f012`
  - `label = "d. Have you received a federal separation incentive payment"`
- 缺失下一行：
  - `in the past 5 years?`（y=371.8-382.6）

**证据**

- 该后半句文本在原文中存在，且与第 8.d 同左边界块（x≈21.6）连续出现。
- 检测输出中未拼接该第二行。

**根因追溯**

- `_find_checkbox_group_label()` 只返回单个最佳文本行，不做多行标题拼接。

---

### E-005：第 9 点标签缺后半句 `employees of the United States Courts?`

**现象（成立）**

- 对应字段：
  - `field_id = p1_f014`
  - `label = "9. Do you have any relatives who are Judges, Officers or"`
- 缺失下一行：
  - `employees of the United States Courts?`（y=401.8-412.6）

**证据**

- 原文第 9 点明显为两行连续问句。
- 输出只保留第一行。

**根因追溯**

- 与 E-004 相同：checkbox 组标签提取是单行选择，不支持多行合并。

---

### E-006：4 条下划线字段被错误标注为 `NO`

**现象（成立）**

- 以下 4 个字段都被标成 `label=NO`：
  - `p1_f006`, `p1_f011`, `p1_f013`, `p1_f015`
  - `source=engine1_underline`
- 这些线段位于右侧补充信息区，本应关联 `If no...` / `If yes...` 类短语，而不是 `NO` 单词。

**证据（打分复现）**

- 以 y=267.9 线段为例：
  - `NO`（left_inline）得分 `6.87`
  - `If no, give the Country of your citizenship`（above）得分 `116.79`
- 其余 3 条线同样由 `NO` 以最低分当选。

**根因追溯**

- `_find_label_for_underline()` 对 `left_inline` 采用纯距离优先，`NO/YES` 这种短 token 紧邻线起点时会稳定胜出。
- 未对 `YES/NO` 做降权，也未在存在长语义短语时提升 `above` 候选优先级。

---

## 3. 本次未计入错误项


- 你后续自我更正的条目：`8.c` 右侧 `If yes, give former agency contact/telephone`。  
  已核验，不纳入错误列表。

---


## 13. 实验结果分析（2026-03-17）

> 基于 4 份测试 PDF 的可视化标注结果和 JSON 数据，对各引擎和整体 pipeline 进行详细分析。

### 13.1 总体数据概览

| PDF | 页数 | 总检测字段数 | 预期合理范围 | 判定 |
|-----|------|------------|-----------|------|
| 008 (US Courts AO 78) | 5 | 155 | 70-90 | **过多** (大量 (continued) 重复 + text_box 假阳性) |
| 013 (FDIC G-FIN-5) | 3 | 28 | 25-30 | **基本合理** (page 1 佳, pages 2-3 为纯说明页) |
| 018 (DOL ETA-9141C) | 4 | 167 | 50-70 | **严重过多** (carve 步骤产生大量 (continued) 碎片) |
| 019 (Aetna Diabetes) | 1 | 5 | 15-18 | **严重不足** (仅检到 5 个字段, 丢失全部填写行) |

### 13.2 引擎 1 分析：engine1_detect_boxes（矢量矩形框 + 下划线）

#### 13.2.1 矩形框检测

**008 表现（良好）：**
- Page 1: 正确检测到 "Name"、"Address"、"Email Address" 等顶部文本框
- Page 1: "Date of Birth" 矩形框正确标注 (c=0.84)
- Pages 3-5: Work Experience 表格区域的矩形框未被误检（被 `_is_decorative_rect` 和 `w <= h * 1.5` 正确排除）

**问题 1 — "Page X of Y" 和说明性文字框误检：**
- p1_e1_002: "verified and credited)" 被检测为 engine1_box (c=0.84) —— 这是 Q10 的说明文字矩形，不是填写区域
- p2_e1_001: "Page 2 of 5" 被检测为 engine1_box (c=0.84) —— 页码区域
- p5_e1_001: "Page 5 of 5" 同上
- p5_e1_002: "occurrence, and name/address of police d" —— 又一个说明性矩形

**根因：** `_is_decorative_rect()` 仅通过 fill color + area 占比判断装饰性矩形，对 fill=黑色/白色 的矩形直接返回 False。但许多说明文字框（比如"If yes, provide..."的条件说明区）也是黑框白底矩形，和真正的填写框几何特征完全一致。

**修复建议：** 增加基于文字密度的判断——如果矩形内部的文字占据面积 > 矩形面积的 50%，则判定为"标签/说明框"而非"填写框"。

**问题 2 — Page 1 底部大量 text_box 假阳性 (c=0.62)：**
- p1_e1_005 到 p1_e1_015：共 11 个标注为 "text_box" 的 engine1_box 字段
- 从可视化看，这些绿色矩形都落在页面最底部，似乎是 PDF 绘图中的装饰性/边框矩形，被误识别为填写框

**根因：** 这些矩形没有关联到任何文字 label（所以被标记为 "text_box"），但它们通过了 `w > 30`, `h > 12`, `w > h * 1.5` 的几何过滤条件。猜测这些是打印区域标记或边框修饰。

**修复建议：**
1. 对 label 为 None 的矩形框，增加额外过滤——检查矩形是否与页面可见内容区域重叠
2. 对完全没有关联文字的矩形框降低优先级，并在 dedup 阶段被其他引擎的有 label 检测覆盖

#### 13.2.2 下划线检测

**008 Pages 3-5 表现（优秀）：**
- "From:", "To:", "Starting $", "Per", "City", "State", "Final $" 等 Work Experience 区域的下划线全部正确检测
- Label 关联精准，"left_inline" 策略工作良好
- SIGNATURE、DATE SIGNED 的下划线也正确检出

**008 Page 1 表现（良好但有噪声）：**
- p1_e1_016 "NO" (c=0.74) —— 这些是 YES/NO 后面的附加文字区域下划线，应该属于 checkbox 后的条件输入框，关联到 "NO" 不太准确
- p1_e1_021 "mortgage loan))" (c=0.74) —— 下划线关联了错误的 label，实际应该关联到 Q12 的 "If yes, provide..." 条件填写区

**013 Page 1 表现（优秀）：**
- 所有 25 个下划线字段都正确检出
- Label 关联精准：1. Individual's Name, 2. Capacity, 3. Social Security Number, a. Name, b. Registration Number, c. Main Address, 5. Office of Employment Address, 6. Date Terminated, Person to Contact, 9-12 ACKNOWLEDGEMENT 区域
- 这是最理想的测试用例，说明引擎 1 的下划线检测在标准政府表单上效果极好

**019 表现（严重不足）：**
- Engine 1 仅检出 3 个字段：p1_e1_001 "Your Information" (box), p1_e1_002 + p1_e1_003 (underline)
- **完全未检测到任何填写下划线**——Name, Date of Birth, Member ID, Address, City, State, ZIP Code, Phone, Signature, Date, Doctor Name, Doctor Phone, Doctor Fax 全部漏检

**根因：** Aetna 表单的填写行使用的是**点线（dotted line）**而非实线。从 engine1 可视化看，这些点线不会被 PyMuPDF 识别为 horizontal_lines（它们可能是由大量短小 line segment 或点字符组成的）。Engine 1 的 `extract_drawings()` 方法依赖 `page.get_drawings()` 获取矢量线段，对点线/虚线支持不足。

**修复建议：**
1. **在 engine1 中增加虚线/点线合并逻辑：** 检查同一 Y 坐标上连续的短线段，如果间距均匀且总跨度 > MIN_UNDERLINE_W，合并为一条长下划线
2. **或者：** 让 Engine 2 对 019 这类情况触发——但目前 Engine 2 的触发条件是 `non_checkbox_count < 3`，而 019 检到了"Your Information" box 等 3-5 个字段，所以 Engine 2 **不会被触发**。需要降低阈值或改用比例触发（如 fields/page_area < 某阈值）

### 13.3 引擎 2 分析：engine2_detect_blanks（pdfplumber 空白区间回退）

**008 表现分析：**
- 从 Engine 2 单独可视化看，它在 page 1 检测了 22 个空白区间（橙色标注），pages 3-4 各检测了 24 个
- 检测结果包含 "Dates of Employment", "From: To:", "Starting $ Per", "City", "State", "Name and Title of Immediate Supervisor" 等正确字段
- 但也包含一些噪声：比如 "7. Are you a U.S. Citizen?" 行的 YES/NO 之间的空白被当做可填区间

**关键问题 — ENGINE2_TRIGGER_THRESHOLD 过于保守：**
- 当前设置为 3，意味着只有在引擎1+3+4 合计非 checkbox 字段 < 3 时才触发
- 这导致 019 (Aetna) 这种引擎1几乎失效但有少量误检的情况下，Engine 2 不会触发
- **013 page 2-3** 的情况：page 2 是纯说明页（instructions），page 3 是纯说明页的延续，理论上不需要 Engine 2。但从结果看 page 2 只检出了 2 个 unlabeled underline（p2_f001, p2_f002），这是合理的因为 page 2 确实没有需要填写的字段

**修复建议：**
1. 将 ENGINE2_TRIGGER_THRESHOLD 改为**基于页面内容密度**的动态阈值，而非硬编码 3
2. 或者将触发条件改为：`if non_checkbox_count < max(3, expected_fields_by_text_analysis * 0.3)`
3. 特别关注：对于引擎1完全不产出结果（如虚线表单）的页面，应该**无条件触发** Engine 2

### 13.4 引擎 3 分析：engine3_detect_checkboxes（Checkbox 专用引擎）

**008 表现（优秀）：**
- Page 1: 正确检测到 9 组 checkbox（Q7-Q12），每组都有 YES/NO 选项
- 标注位置精准，红色方框覆盖 YES 和 NO 区域
- Label 关联正确："GENERAL" → Q7, "8. a. Were you ever..." → Q8a, 以此类推
- Page 2: 正确检测 5 组（Q13a 的 YES/NO, Q16a, Bar membership ACTIVE/INACTIVE, scholastic standing UPPER ½/⅓/¼, Q16c）
- Page 5: 正确检测 3 组（Q18-Q20）

**013 表现（良好）：**
- Page 1: 正确检测 2 组——"7. Reason for Termination" (5 个选项: Resigned/Discharged/Deceased/Transfer/Other), "8. While associated...Yes/No"
- 多选项 checkbox group 的分组和文字关联正确

**018 表现（良好）：**
- 正确检测到 "4. Does this position supervise..." Yes/No
- "4b. subordinate/peer" checkbox 对
- "Education" 多选 checkbox (None/High School/Associate's/Bachelor's/Master's/Doctorate/Other)
- "6. Will travel be required" Yes/No
- "4a. OES Wage level" I/II/III/IV/N/A 选项
- "5. Per:" Hour/Week/Bi-Weekly/Month/Year/Piece Rate 选项

**问题 — checkbox 没有在 Page 3-4 (008) 被检出：**
- 这是正确的行为，因为 pages 3-4 的 Work Experience 区域没有 checkbox
- 但注意 pages 3-4 中没有检出 "Number of hours worked per week" 和 "Exact Title of Your Position" 的填写框——这些是 engine1 underline 和 engine4 table cell 的职责

**总体评价：** Engine 3 是 4 个引擎中表现最稳定的，几乎没有误检和漏检。

### 13.5 引擎 4 分析：engine4_synthesize_table_fields（表格合成引擎）

**008 Page 1 表现（良好）：**
- 正确检测到 3 个表格单元格：Name/Phone Number 行, Address 行, Email Address 行
- 蓝色矩形位置精准

**008 Page 2 表现（严重问题 — carve 碎片化）：**
- Education 表格区域（b. Name and location of colleges...）生成了大量碎片字段
- 从整合结果看：p2_f004 到 p2_f041 共 38 个字段，大部分是 `(continued)` 标签
- 5 行 x 7 列的表格每个空单元格都被检测为一个字段（这是正确的），但 carve 步骤又把跨表格边线的字段再切分了一次，造成重复
- 例如：p2_t1_r1_c0 被 carve 切成了 6-7 个 `(continued) p2_t1_r1_c0` 碎片

**根因：** `_step2_carve` 在 table 区域内对**已经是 engine4 产出的 table_cell 字段**再次用 grid_x 切分。Engine 4 本身已经按 cell 边界生成了字段，carve 步骤不应该再次切分这些已按 cell 生成的字段。

**修复建议：** 在 `_step2_carve` 中增加跳过条件——如果字段的 source 是 "engine4_table_cell"，则跳过 carve（因为这些字段已经按 cell 边界精确生成了）。

**008 Pages 3-4 表现（可接受但有小问题）：**
- Work Experience 的表格结构被正确识别
- "Business Telephone" 和 "Reason for Leaving" 的分格结构正确
- 但每个表格只检出了 4 个单元格（2个第一行 + Reason for Leaving + 1个 Description 区），较多重要单元格（如 "Number of hours worked per week", "Exact Title of Your Position", "Pay Plan/Grade"）未被检测为独立字段

**根因：** 这些是含有 label 但内容为空的 table cell，`_classify_cell` 方法将其判断为 "label"（label 文字面积 > cell 面积 * LABEL_AREA_RATIO）而排除。实际上这些 cell 既有 label 又需要用户填写。

**修复建议：** 对含 label 的 cell，如果 cell 面积显著大于 label 文字面积（例如空白区域 > 60%），应该生成一个 fill_rect 覆盖空白区域。

**018 表现（严重的 carve 碎片问题）：**
- Page 1: 生成了 92 个字段，其中大量是 `(continued)` 碎片
- 几乎每个 table_cell 都被 carve 步骤再次切分成 2-6 个碎片
- 例如 "B. Requestor Point of Contact Information" 行被切成了 5-6 个碎片
- "1. Legal Business Name *" 被切成了 6 个碎片
- 这导致 JSON 数据膨胀到 305KB，字段数 167 远超实际需要的 50-70 个

**019 表现（不足）：**
- 仅检出 2 个 engine4 字段：p1_t1_r0_c0 (无标签) 和 "MAIL TO:" 相关单元格
- 原因同引擎 1：Aetna 表单的表格结构使用彩色背景块和点线而非标准矩形边框，PyMuPDF 无法正确提取表格网格

### 13.6 8 步几何修正分析

#### Step 1 - synthesize（合并重叠字段）
- 工作正常，将完全包含的小字段合并到大字段中

#### Step 2 - carve（按 table grid 切分字段）⚠️ **最大问题源**
- **核心缺陷：** 对 engine4_table_cell 产出的字段执行了不必要的二次切分
- 这是 008 Page 2 产出 38 个碎片字段、018 产出 167 个字段的直接原因
- **(continued)** 标签泛滥使 JSON 数据对 VLM 语义分析产生大量噪声
- **修复：** 在 carve 开头增加 `if f.get("source") == "engine4_table_cell": result.append(f); continue`

#### Step 3 - adjust（snap to grid）
- 工作正常

#### Step 4 - nudge（内缩 2px 边距）
- 工作正常，避免文字写在边框上

#### Step 5 - truncate（裁剪到页面范围）
- 工作正常

#### Step 6 - offset（处理非零原点页面）
- 工作正常（测试 PDF 都是 (0,0) 原点）

#### Step 7 - dedup（去重） ⚠️ **阈值可能不足**
- 当前使用 overlap_ratio > 0.7 去重
- 问题：carve 产生的碎片字段之间 overlap_ratio 都 < 0.7（因为它们是被切开的不同区域），所以无法被去重
- 真正需要去重的是：engine1 和 engine4 对同一区域产出的重叠字段。从 008 Page 1 看，engine1 和 engine4 分别检出了 "Name" 行——engine1 作为 underline/box, engine4 作为 table_cell——dedup 应该保留 engine4 的结果（因为 table_cell 更精确），但实际情况需验证

#### Step 8 - sort（按位置排序）
- 工作正常

### 13.7 各 PDF 整体评价

#### 008 (US Courts AO 78) — 评分：60/100
**优点：**
- Checkbox 检测完美（9+5+3 组 = 17 组，全部正确）
- Work Experience 页的下划线检测精准
- 顶部 Name/Address/Email 表格单元格正确检出

**问题：**
1. Page 1 底部 11 个 text_box 假阳性（可视化中密集排列在页面底部的绿色矩形）
2. Page 2 Education 表格 carve 碎片化严重（38 个字段 vs 预期约 10 个）
3. "Page X of Y" 和说明文字矩形被误检为 engine1_box
4. 总计 155 个字段中约 60-70 个是有效的，其余为碎片或假阳性

#### 013 (FDIC G-FIN-5) — 评分：85/100
**优点：**
- Page 1 检出 25 个字段，几乎完美覆盖所有填写区域
- 下划线 + label 关联精准
- Checkbox (Reason for Termination, Yes/No) 正确检出
- Page 2-3 为纯说明页，仅检出 2+1 个字段（合理，因为这些页确实没有填写区域）

**问题：**
1. p1_f001 "OMB #3064-0093" 被误检为 engine1_box —— 这是页头信息框
2. p1_f020 "CRIMINAL VIOLATIONS. (See 18 U.S.C. 1001..." 的下划线被误检为可填区域
3. p3_f001 "Public reporting burden..." 段落矩形被误检为 engine1_box
4. Page 2 的 "financial institution government securities broker or dealer" 等术语定义中的下划线可能是印刷下划线（强调标记），非填写区域

#### 018 (DOL ETA-9141C) — 评分：35/100
**优点：**
- Checkbox 检测正确（4. supervise Yes/No, education level, travel, wage level, per 等）
- 表格结构被正确识别（grid_x, grid_y 提取正确）

**问题：**
1. **carve 碎片化是最严重的问题** — 167 个字段中约 100 个是 `(continued)` 碎片
2. Page 1 每行表格字段（如 "1. Contact's Last (family) Name *"）被切成 5-6 个碎片
3. "U.S. Department of Labor" 页头下划线在每页都被误检为字段 (p1_f001, p2_f001, p3_f001, p4_f001)
4. 表单底部的 "PW Tracking Number / Case Status / Determination Date / Validity Period" 行（FOR DEPARTMENT USE ONLY）也被检测为字段
5. 去除碎片和假阳性后，有效字段约 50 个，这个数字是合理的

#### 019 (Aetna Diabetes Supply Order Form) — 评分：15/100
**优点：**
- "Your Information" 矩形框被正确检出

**问题：**
1. **致命缺陷：** 所有填写行（Name, Date of Birth, Member ID, Address, City, State, ZIP, Phone, Signature, Date, Doctor Name, Doctor Phone, Doctor Fax）全部漏检
2. Checkbox（OneTouch Verio Flex / Accu-Chek Guide / Accu-Chek Guide Me / opt-out box）全部漏检
3. 根因是 Aetna 表单使用**点线（dotted lines）**作为填写行，这种绘图方式不被 PyMuPDF 的 `get_drawings()` 识别为连续水平线段
4. Engine 2 因为 non_checkbox_count >= 3 而未触发（p1_f001 "Your Information" box + 2 个误检的 underline）
5. Engine 3 未检出任何 checkbox，说明 Aetna 的 checkbox 使用了特殊的绘制方式（可能是 symbol/glyph 而非矢量方块）

### 13.8 需要修复的问题优先级

#### P0（必须修复 — 否则影响核心功能）

**1. _step2_carve 不应对 engine4_table_cell 字段二次切分**
- 影响范围：所有含表格的 PDF（008, 018 严重受影响）
- 修改位置：`detector.py:_step2_carve()` (约第 1237 行)
- 修改方式：在 for 循环开头增加：
```python
if f.get("source") == "engine4_table_cell":
    result.append(f)
    continue
```

**2. Engine 2 触发条件过于保守**
- 影响范围：点线/虚线表单（019 类型）完全失效
- 修改位置：`detector.py:detect_page()` (约第 1443 行)
- 修改方式：将触发条件从 `non_checkbox_count < 3` 改为更智能的策略：
```python
# 方案 A：对引擎1下划线产出为0的情况也触发
underline_count = sum(1 for f in all_fields if f.get("source") == "engine1_underline")
if non_checkbox_count < self.ENGINE2_TRIGGER_THRESHOLD or underline_count == 0:
    # 触发 Engine 2
```

#### P1（应该修复 — 提升检测质量）

**3. 增加矩形框的文字密度过滤**
- 影响范围：说明文字框被误检为填写框（008 p1, 013 p3）
- 修改位置：`detector.py:engine1_detect_boxes()` 矩形处理部分
- 修改方式：在 `rects.append(bbox)` 之前，检查矩形内文字占据的面积比例。如果 > 50%，跳过。
```python
# 需要写诊断脚本确认阈值
def _rect_text_fill_ratio(self, rect, text_spans):
    """计算矩形内文字面积占矩形面积的比例"""
    rect_area = self._bbox_width(rect) * self._bbox_height(rect)
    text_area = 0.0
    for sp in text_spans:
        sb = sp["bbox"]
        overlap = self._intersection_area(rect, sb)
        text_area += overlap
    return text_area / max(1.0, rect_area)
```

**4. 增加 "Page X of Y" 和页头信息的过滤**
- 影响范围：所有 PDF 的页码区域
- 修改位置：`engine1_detect_boxes()` 矩形检测
- 修改方式：如果矩形的 label 文字匹配 `r"Page \d+ of \d+"` 或 "OMB #" 或 "FOR DEPARTMENT" 等模式，标记为 decorative 并跳过

**5. 点线（dotted line）下划线合并**
- 影响范围：019 类型的商业表单
- 修改位置：`extract_drawings()` 或新增一个后处理步骤
- 修改方式：
```python
# 诊断脚本：需要先分析 019 的 page.get_drawings() 返回什么数据
# 如果点线被拆成多个短线段，则在 extract_drawings 阶段合并
def _merge_dotted_lines(self, horizontal_lines):
    """将同一 Y 坐标上间距均匀的短线段合并为一条长下划线"""
    # 按 y 坐标分组（容差 1.5pt）
    # 同组内按 x0 排序
    # 如果相邻线段间距 < 5pt 且单段长度 < 10pt，则合并
```

**6. _classify_cell 应支持"含 label 的可填单元格"**
- 影响范围：008 Pages 3-4 的 Work Experience 表格（Number of hours, Exact Title, Pay Plan/Grade 等缺失）
- 修改位置：`engine4_synthesize_table_fields()` 中的 `_classify_cell()`
- 修改方式：如果 cell 中有 label 但空白区域 > cell 面积的 60%，将 fill_rect 设为 label 右侧或下方的空白区域

#### P2（可以后续修复 — 锦上添花）

**7. dedup 的 overlap_ratio 阈值调优**
- 可以在修复 carve 后重新评估是否需要

**8. "FOR DEPARTMENT USE ONLY" 区域排除**
- 修改方式：检测到 "FOR...USE ONLY" 文字后，排除其下方的所有字段
- 优先级较低因为 VLM 语义分析阶段可以识别并跳过这些字段

**9. Engine 1 下划线 label 关联的边界情况**
- 如 "NO" 被关联为下划线 label（实际应该是 "If no, give the Country..."）
- 可以通过检查 label 是否为单个 YES/NO/checkbox 选项词来过滤

### 13.9 建议的诊断脚本

以下脚本用于进一步定位问题，建议在修复代码前先运行确认假设：

#### 脚本 1：分析 019 的 drawings 数据
```python
"""诊断 019 的 dotted line 问题"""
import fitz
import json

doc = fitz.open("TestSpace/.tempdocs/019_www.aetna.com_9923d5.pdf")
page = doc[0]
drawings = page.get_drawings()

# 统计水平线段
h_lines = []
for d in drawings:
    for item in d["items"]:
        if item[0] == "l":  # line
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) < 1.0:  # horizontal
                h_lines.append({
                    "x0": min(p1.x, p2.x),
                    "x1": max(p1.x, p2.x),
                    "y": p1.y,
                    "length": abs(p2.x - p1.x)
                })

# 按 y 排序并查看短线段分布
h_lines.sort(key=lambda l: (round(l["y"], 1), l["x0"]))
for l in h_lines:
    print(f"y={l['y']:.1f}  x=[{l['x0']:.1f}, {l['x1']:.1f}]  len={l['length']:.1f}")

# 查看 "re" (rectangle) 操作
for d in drawings:
    for item in d["items"]:
        if item[0] == "re":
            print(f"rect: {item[1]}")

doc.close()
```

#### 脚本 2：统计 carve 碎片影响
```python
"""统计 carve 前后的字段数差异"""
import json

for pdf_name in ["008", "013", "018", "019"]:
    # 读取 integration 结果 JSON
    # 统计 (continued) 标签的数量
    # 统计不同 source 的字段数量
    pass
```

#### 脚本 3：分析 engine1 text_box 假阳性的几何特征
```python
"""分析 008 Page 1 的 text_box 字段的位置和大小"""
import json

with open("TestSpace/preprocess_results/05_integration/all_result_008_www.uscourts.gov_a28.json") as f:
    data = json.load(f)

for page in data["pages"]:
    for field in page["detected_fields"]:
        if field.get("label") == "text_box":
            print(f"  {field['field_id']} rect={field['fill_rect']}")
```

### 13.10 修复后的预期效果

| PDF | 修复前 | 修复后预期 | 主要改善 |
|-----|-------|---------|-------|
| 008 | 155 字段 | ~80 字段 | P0-1 去除 carve 碎片, P1-3 去除 text_box 假阳性 |
| 013 | 28 字段 | ~25 字段 | P1-4 去除 OMB/CRIMINAL 误检 |
| 018 | 167 字段 | ~55 字段 | P0-1 去除 carve 碎片 (消除约 110 个 continued 碎片) |
| 019 | 5 字段 | ~17 字段 | P0-2 触发 Engine 2 + P1-5 点线合并 |

### 13.11 总结

**整体评价：pipeline 架构正确，4 引擎分工合理，主要问题集中在以下 3 点：**

1. **_step2_carve 对 engine4 输出的二次切分** — 这是最影响输出质量的 bug，修复后预计消除 60% 以上的无效字段
2. **Engine 2 触发条件过于保守** — 导致点线/虚线表单完全失效，需要更智能的触发策略
3. **点线下划线无法被 PyMuPDF 识别** — 这是一个底层限制，需要增加短线段合并逻辑或依赖 Engine 2 作为兜底

修复优先级：先解决 P0 的两个问题（carve 跳过 + Engine 2 触发条件），这两个改动代码量小但效果显著。然后按 P1 顺序逐步优化。

---

## 14. 008 Page 1 逐条错误分析与修复决策（2026-03-17）

> 基于 `docs/Preprocess errors summary.md` 中确认的 6 个 Page 1 错误，结合可视化标注 PDF 复核，
> 逐条判定是否需要在 preprocess 阶段修复，以及与 YOLO / VLM 的职责划分。

### 14.1 决策原则

1. **preprocess 的职责是尽可能准确地产出 fill_rect**，给 VLM 提供最少噪声的输入
2. **VLM 负责"填写目标确定"和"分组"**：确认哪些 field 真正需要填写、补充语义信息、拆分/合并字段
3. **如果 preprocess 不产出 rect，VLM 无法凭空创造**——所以漏检必须在 preprocess 修
4. **如果 preprocess 产出了 rect 但 label 不够完整，VLM 可以补全**——所以标签截断可以留给 VLM
5. **跨模板泛化 > 单模板数字好看**——只修有明确泛化意义的 bug，不为 4 份测试 PDF 调参

### 14.2 逐条分析

#### E-001：`1. Name` 与 `2. Phone Number` 被合并为一个字段

**现象：** engine4_table_cell 产出一个横跨整行的 field，label = "1. Name (Last, First, Middle Initial) 2. Phone Number"，fill_rect 覆盖了 Name 和 Phone 两个区域。

**根因：** 原 PDF 在 Name 和 Phone 之间没有竖线分隔，`_build_table_grids` 基于矢量线段建网格，建出 `grid_x = [18.6, 593.6]`（单列），这是正确行为——没有竖线就不应该凭空造一列。

**决策：不修，留给 VLM。**

理由：
- 如果硬编码"遇到多编号标签就拆 cell"，泛化风险极高——很多表格的 cell 合法地包含多个编号段落（如说明性条款 "1. ... 2. ..."）但不需要拆分成填写区域
- VLM 天然能处理：它看到图片中 "1." 和 "2." 是两个独立问题，可以在语义阶段将一个 fill_rect 拆成两个填写目标
- 这正是 VLM "填写目标确定" 的核心价值——preprocess 给出一个合理的候选区域，VLM 决定如何使用

#### E-002：第 5 点 `Other Names Previously Used for Employment Purposes` 未生成可填写字段

**现象：** Page 1 没有任何 field 对应 "5. Other Names..." 的填写区域。该区域完全漏检。

**根因：** 该行位于 table 第 4 行（row=3），cell_bbox = (18.6, 189.7, 593.6, 235.0)。cell 内同时包含 "5. Other Names..." + "6. Date of Birth..." + "GENERAL" 三段文字。`_classify_cell()` 计算后判定为 "label"（因为文字面积占比超过 LABEL_AREA_RATIO），直接 continue 不生成字段。但实际上这个 cell 的下半部分是空白填写区域。

**决策：应该修，这是 preprocess 能力范围内的 bug。**

理由：
- 如果 preprocess 不产出 rect，VLM 无法凭空创造一个填写区域
- 这是 `_classify_cell` 的逻辑缺陷：对"上半部有 label、下半部空白"的混合 cell 应该判定为 fillable

**修复方案：** 在 `_classify_cell` 中，当判定为 "label" 时增加二次检查：

```python
# detector.py _classify_cell() 末尾，在 return ("label", combined_text) 之前
# 二次检查：label 文字是否只占据 cell 顶部，下方有大片空白
if text_ratio > self.LABEL_AREA_RATIO:
    # 检查 label 文字是否集中在 cell 上半部
    text_bottom = text_bbox[3]
    cell_bottom = cell_bbox[3]
    remaining_height = cell_bottom - text_bottom
    cell_height = self._bbox_height(cell_bbox)
    if remaining_height > cell_height * 0.4 and remaining_height > self.MIN_FIELD_HEIGHT:
        # label 只占上半部，下方空白足够填写 → 判定为 fillable
        return ("fillable", combined_text)
    return ("label", combined_text)
```

泛化安全性：这个逻辑对任何"标题在上、填写区在下"的 table cell 都适用，是通用的表格布局模式。

#### E-003：第 7 点 `Are you a U.S. Citizen?` 的 checkbox 组标签被错配成 `GENERAL`

**现象：** p1_f005 的 source = engine3_checkbox，label = "GENERAL"（应为 "7. Are you a U.S. Citizen?"）。可视化中红色 checkbox 框标注了 "GENERAL" 作为组标签。

**根因：** `_find_checkbox_group_label()` 中 "GENERAL" 作为 `above` 候选得分约 112.44，而 "7. Are you a U.S. Citizen?" 作为 `left_inline` 候选得分约 137.00。分数更低者胜出，所以选中了 "GENERAL"。

"GENERAL" 是 section header（章节标题），不是字段标签。当前评分逻辑没有区分 section header 和 field label。

**决策：应该修，简单的评分修正且泛化意义明确。**

理由：
- Section headers（全大写、不含数字编号的短标题）在所有表单中都不应该作为字段标签
- 这个模式在美国政府表单中极其普遍：GENERAL、EDUCATION、BACKGROUND INFORMATION、WORK EXPERIENCE、APPLICANT CERTIFICATION 等
- 不修的话，任何 section header 下方的第一个 checkbox/underline 都会被错配标签

**修复方案：** 在 `_find_checkbox_group_label` 和 `_find_label_for_underline` 的候选评分中，对 section header 模式加罚分：

```python
# detector.py 新增类常量
SECTION_HEADER_PENALTY = 200.0

# 在 _find_checkbox_group_label 的 candidates.append 之前
def _is_section_header(self, text: str) -> bool:
    """全大写、不含数字编号、3 词以内的短标题 → section header"""
    if not text.isupper():
        return False
    if re.search(r'\d', text):
        return False
    if len(text.split()) > 4:
        return False
    return True

# 使用：
if self._is_section_header(text):
    score += self.SECTION_HEADER_PENALTY
```

泛化安全性：全大写 + 无数字 + 短文本是 section header 的强特征，误伤风险极低。

#### E-004：第 8.d 标签缺后半句 `in the past 5 years?`

**现象：** p1_f012 的 label = "d. Have you received a federal separation incentive payment"，缺失第二行 "in the past 5 years?"。

**根因：** `_find_checkbox_group_label()` 只返回单个最佳文本行，不做多行标题拼接。当问题文本跨两行时，只取了第一行。

**决策：不修，留给 VLM。**

理由：
- 多行标签拼接的边界条件极其复杂——什么时候两行属于同一标签？什么时候是两个独立字段？纯几何规则无法可靠判断
- 当前截断的标签已经包含了**足够多的语义信息**："d. Have you received a federal separation incentive payment" 已经清楚表达了问题含义
- VLM 能看到完整 PDF 图片，可以在语义阶段补全截断的标签文本——这是 VLM "语义理解" 的强项
- 强行在 preprocess 做多行合并，泛化风险大（可能把不相关的两行文字误合并）

#### E-005：第 9 点标签缺后半句 `employees of the United States Courts?`

**现象与根因：** 与 E-004 完全相同——`_find_checkbox_group_label()` 的单行选择限制。

**决策：不修，留给 VLM。** 理由同 E-004。

#### E-006：4 条下划线字段被错误标注为 `NO`

**现象：** p1_f006, p1_f011, p1_f013, p1_f015 这 4 个 engine1_underline 字段的 label 都是 "NO"。这些是 YES/NO checkbox 右侧的条件填写行（如 "If no, give the Country of your citizenship"），应该关联到条件说明短语而非 "NO" 单词。

**根因：** `_find_label_for_underline()` 对 `left_inline` 候选采用纯距离优先。"NO" 紧邻下划线起点（距离 6.87），而真正的条件短语 "If no, give the Country of your citizenship" 在上方（得分 116.79）。距离碾压导致错选。

**决策：应该修，这是明确的 bug 且有极好的泛化意义。**

理由：
- YES/NO 作为 checkbox 选项文本紧邻下划线的模式，在美国政府表单中是**标准范式**——几乎所有带条件分支的问题都是 "YES □ NO □ If yes/no, [下划线填写区]" 的布局
- 不修的话，任何此类表单的条件填写行都会被错标签
- YES/NO 作为独立下划线标签的合法场景几乎不存在（下划线字段的标签通常是 "Name:", "Date:", "Address:" 这类描述性文本）

**修复方案：** 在 `_find_label_for_underline` 中对孤立的 YES/NO 词加罚分：

```python
# detector.py _find_label_for_underline() 中，candidates.append 之前
# YES/NO 作为 checkbox 选项文本，不应该成为下划线的标签
YES_NO_PENALTY = 150.0

# 在 left_inline 分支中：
if re.match(r'^(YES|NO|Yes|No|yes|no)$', text.strip()):
    dist += YES_NO_PENALTY  # 强制让它输给 above/其他候选
```

同样的降权也应用于 `_find_label_for_rect`（如果该方法也有类似的候选评分逻辑）。

泛化安全性：正则严格匹配完整的 YES/NO 词，不会影响包含 YES/NO 的长文本（如 "If yes, provide..."）。

### 14.3 修复决策汇总

| 编号 | 问题 | 修？ | 阶段 | 理由 |
|------|------|------|------|------|
| E-001 | Name+Phone 合并 | **否** | VLM | 无竖线=无法拆；VLM 语义拆分 |
| E-002 | Other Names 漏检 | **是** | preprocess | 不产出 rect 则 VLM 无法补救 |
| E-003 | GENERAL 错标签 | **是** | preprocess | section header 降权，泛化通用 |
| E-004 | 标签截断 in the past 5 years | **否** | VLM | 已有足够语义；多行合并泛化风险大 |
| E-005 | 标签截断 employees of... | **否** | VLM | 同 E-004 |
| E-006 | 4 条下划线标签=NO | **是** | preprocess | YES/NO 降权，泛化通用 |

加上此前已确认的 P0 修复：

| 编号 | 问题 | 来源 |
|------|------|------|
| P0-1 | carve 跳过 engine4（synthesize 也跳过） | 13.8 节 |
| P0-2 | engine2 触发条件加 `underline_count == 0` | 13.8 节 |

**本轮共需修复 5 个点：P0-1, P0-2, E-002, E-003, E-006。**

### 14.4 关于 YOLO 的决策：不采用

**结论：跳过 YOLO，当前 4 引擎 + VLM 的两阶段架构已经足够。**

#### 不用 YOLO 的理由

1. **检测能力已经足够。** 从测试结果看，engine1+3+4 在结构化表单上的召回率已经很高（013 得分 85/100），主要问题是 label 质量和触发条件，不是检测覆盖面不足。修复上述 5 个点后，4 引擎的检测能力可以覆盖绝大多数 native PDF。

2. **YOLO 会制造更多问题。**
   - YOLO 检测出的是像素级 bounding box，需要 pixel→PDF 坐标转换（DPI 对齐、缩放系数），引入额外误差
   - YOLO 无法区分"填写框"和"说明文字框"——它会把所有矩形区域都检出来，false positive 更高
   - 训练数据要求高：需要大量标注好的 PDF 表单图片，且不同表单风格差异大，模型泛化难度高

3. **成本不对等。** 加 YOLO 意味着每页需要渲染为图片 + GPU 推理，破坏了 "Stage A < 1s, 0 tokens" 的设计目标。当前问题用 5 个局部规则修正就能解决，代价远低于引入一个新的 ML 模型。

4. **YOLO 有价值的唯一场景：扫描后矢量化的 PDF。** 这类 PDF 没有真正的矢量元素，4 引擎完全失效。但这属于 scanned PDF 分类，应走 OCR pipeline（Phase 0 已有分类逻辑），不在 native pipeline 的范围内。

#### YOLO 的替代策略

对于 4 引擎覆盖不到的边界情况（如非常规布局的商业表单），VLM 本身就能充当"视觉检测器"的角色：
- VLM 看到 PDF 渲染图片后，可以指出 preprocess 遗漏的填写区域
- VLM 的指令可以包含 "如果你发现图片中有填写区域但 preprocess 未检出，请补充其坐标"
- 这比 YOLO 更灵活——不需要额外的模型部署和训练，且天然具备语义理解能力

### 14.5 VLM 阶段的职责边界（明确化）

基于上述分析，明确 preprocess 与 VLM 的分工：

| 职责 | preprocess | VLM |
|------|-----------|-----|
| 检测 fill_rect | **主责** — 4 引擎产出所有候选 rect | **补漏** — 发现遗漏区域时补充坐标 |
| 标签关联 | **尽力而为** — 几何规则匹配最近 label | **纠正/补全** — 修正错配、补全截断标签 |
| 字段拆分 | 不做（无语义能力） | **主责** — 如 E-001 的 Name+Phone 拆分 |
| 分组 | 不做 | **主责** — 将字段组织为逻辑组 |
| 过滤假阳性 | **尽力而为** — 规则过滤明确的假阳性 | **兜底** — 过滤剩余的假阳性 |
| checkbox 选项 | **主责** — engine3 已做得很好 | 验证/补全 |

### 14.6 修复后的完整代码变更清单

以下是 5 个修复点的具体代码变更，均在 `backend/app/services/native/detector.py` 中：

#### 变更 1：P0-1 — step1_synthesize 和 step2_carve 跳过 engine4

位置：`_step1_synthesize()` (~L1233) 和 `_step2_carve()` (~L1256)

`_step1_synthesize` 已在上轮确认中增加了 engine4 跳过逻辑（代码中已体现）。
`_step2_carve` 需确认跳过条件使用 `startswith("engine4")` 而非精确匹配：

```python
# _step2_carve 开头
if str(f.get("source", "")).startswith("engine4"):
    result.append(f)
    continue
```

#### 变更 2：P0-2 — engine2 触发条件

位置：`detect_page()` (~L1475)

```python
# 替换原有触发条件
engine1_underline_count = sum(1 for f in all_fields if f.get("source") == "engine1_underline")
if (
    non_checkbox_count < self.ENGINE2_TRIGGER_THRESHOLD
    or engine1_underline_count == 0
):
    engine2_fields = self.engine2_detect_blanks(...)
```

#### 变更 3：E-002 — _classify_cell 支持混合 cell

位置：`_classify_cell()` (~L1063)

```python
# 在 return ("label", combined_text) 之前插入二次检查
if text_ratio > self.LABEL_AREA_RATIO:
    # 二次检查：label 文字是否集中在 cell 上部，下方有大片空白
    text_bottom = text_bbox[3]
    cell_bottom = cell_bbox[3]
    remaining_height = cell_bottom - text_bottom
    cell_height = self._bbox_height(cell_bbox)
    if remaining_height > cell_height * 0.4 and remaining_height > self.MIN_FIELD_HEIGHT:
        return ("fillable", combined_text)
    return ("label", combined_text)
```

#### 变更 4：E-003 — section header 降权

位置：新增 `_is_section_header()` 方法 + 修改 `_find_checkbox_group_label()` 和 `_find_label_for_underline()`

```python
# 新增类常量
SECTION_HEADER_PENALTY = 200.0

# 新增方法
def _is_section_header(self, text: str) -> bool:
    """全大写、不含数字编号、4 词以内的短标题 → section header"""
    text = text.strip()
    if not text.isupper():
        return False
    if re.search(r'\d', text):
        return False
    if len(text.split()) > 4:
        return False
    if len(text) < 3:
        return False
    return True

# 在 _find_checkbox_group_label 的两个 candidates.append 之前：
if self._is_section_header(text):
    score += self.SECTION_HEADER_PENALTY

# 在 _find_label_for_underline 的两个 candidates.append 之前：
if self._is_section_header(text):
    dist += self.SECTION_HEADER_PENALTY
```

#### 变更 5：E-006 — YES/NO 降权

位置：修改 `_find_label_for_underline()`

```python
# 新增类常量
YES_NO_LABEL_PENALTY = 150.0

# 在 _find_label_for_underline 的 left_inline 分支 candidates.append 之前：
if re.match(r'^(YES|NO|Yes|No)$', text.strip()):
    dist += self.YES_NO_LABEL_PENALTY
```

### 14.7 修复后预期效果（更新）

结合 13.10 节的预期和本轮新增的 3 个修复：

| PDF | 修复前 | 修复后预期 | 变化明细 |
|-----|-------|---------|---------|
| 008 | 155 字段 | ~75 字段 | carve 碎片消除(-40), text_box 假阳性(-11), E-002 新增(+1), 标签质量提升 |
| 013 | 28 字段 | ~25 字段 | section header 误检排除(-2), OMB 误检排除(-1) |
| 018 | 167 字段 | ~55 字段 | carve 碎片消除(-110), 页头 underline 排除(-4) |
| 019 | 5 字段 | ~17 字段 | engine2 触发后补检(+12), 假阳性排除(-3) |

### 14.8 后续验证计划

修复完成后的验证步骤：

1. **重跑 4 份测试 PDF 的 integration test**，生成新的 JSON + 可视化 PDF
2. **逐页人工复核可视化结果**，确认：
   - 008 Page 1: E-002 的 "Other Names" 出现了、E-003 的 checkbox 标签不再是 "GENERAL"、E-006 的下划线标签不再是 "NO"
   - 008 Page 2: Education 表格不再有 (continued) 碎片
   - 018: 字段数从 167 降到 50-60 范围
   - 019: engine2 触发，Name/DOB/Address 等填写行被检出
3. **新增 3-5 份不同风格的测试 PDF**，验证泛化能力：
   - 纯下划线表单（无表格）
   - 带彩色背景的商业表单（类似 019）
   - 密集多列表格表单
   - 混合中英文表单（如果产品需要支持）
4. **字段数只作为 sanity check**，视觉正确性是唯一标准

---

## 15. 第二轮测试结果分析（2026-03-20, run 20260320T140118Z）

> 基于 P0/E-003/E-006 修复后的代码，对 6 份 PDF（原 4 份 + 新增 001、004）的全流程测试结果进行详细分析。
> 分析依据：可视化标注 PDF + JSON 字段数据 + 代码状态。

### 15.1 总体数据对比

| PDF | 页数 | 上轮字段数 | 本轮字段数 | 趋势 | 评价 |
|-----|------|---------|---------|------|------|
| 008 (US Courts AO 78) | 5 | 155 | 158 | ↑3 | **未改善** — text_box 假阳性仍在，E-002 未修复 |
| 013 (FDIC G-FIN-5) | 3 | 28 | 28 | → | **持平** — 本身质量较好 |
| 018 (DOL ETA-9141C) | 4 | 167 | 191 | ↑24 **恶化** | **严重恶化** — engine4 子单元格膨胀 |
| 019 (Aetna Diabetes) | 1 | 5 | 9 | ↑4 | **仍然失败** — engine2 触发但检出全是垃圾 |
| 001 (FDIC Leasing) | 16 | — | 130 | 新增 | **问题较多** — 大量假阳性（目录页、页脚线） |
| 004 (DOL 790) | 11 | — | 100 | 新增 | **中等** — 双语表格子单元格膨胀 |

### 15.2 修复验证结果

#### ✅ E-003 已修复：section header 降权生效

008 Page 1 的 checkbox 组标签已正确：
- `p1_f005` label = `"7. Are you a U.S. Citizen?"` ← 之前是 `"GENERAL"`
- 所有 9 组 checkbox（Q7-Q12, Q18-Q20）标签均正确

#### ✅ E-006 已修复：YES/NO 降权生效

008 Page 1 下划线字段标签已正确：
- `p1_f006` label = `"If no, give the Country of your citizenship"` ← 之前是 `"NO"`
- `p1_f013` label = `"If yes, state mo/yr received and former..."` ← 之前是 `"NO"`
- 所有 4 条之前标为 "NO" 的下划线现在都关联到了正确的条件短语

#### ✅ Carve 跳过 engine4 生效

008 Page 2 不再有 `(continued)` 碎片标签（之前有 38 个带 `(continued)` 的 engine4 碎片）。engine4_table_cell 字段不再被 carve 二次切分。

#### ✅ Engine2 触发条件生效

019 的 `engine1_underline_count = 2 ≤ 2`，engine2 被触发，检出 4 个 engine2_blank 字段。触发逻辑本身正确。

#### ❌ E-002 未修复：_classify_cell 二次判定未实现

008 Page 1 仍然没有 "5. Other Names Previously Used..." 的字段。`_classify_cell` 的 `remaining_height` 二次检查代码**未被实现**。这是一个遗漏的修复点。

### 15.3 新发现的问题

---

#### B-007：engine4 子单元格膨胀（018 核心问题）

**现象：** 018 Page 1 检出 89 个 engine4_table_cell，但实际只有 ~30 个逻辑字段。

**证据：**
- `"1. Legal Business Name *"` 出现 6 次
- `"5. Address 1 *"` 出现 6 次
- `"B. Requestor Point of Contact Information"` 出现 5 次
- 总计 93 个字段但只有 36 个唯一标签

**根因：** 018 的表格 grid 有 10 条 x 线（9 列），列宽不均匀（4.6pt ~ 148.5pt）：
```
grid_x = [63.1, 211.6, 265.6, 288.1, 292.6, 337.6, 427.6, 441.1, 490.7, 576.0]
```
一个逻辑字段行（如 "1. Legal Business Name *"）跨越了 6 列，engine4 为每列都生成了一个独立的 table_cell。这些子单元格有不同的 fill_rect 但共享同一个 label。

**与 carve 碎片的区别：** 这不是 carve 造成的（carve 已跳过 engine4），而是 engine4 `_build_table_grids` + `engine4_synthesize_table_fields` **本身产出就过于细粒度**。

**修复方案（preprocess 阶段可修）：**

在 `engine4_synthesize_table_fields` 末尾增加**同行同标签合并**逻辑：
```python
def _merge_same_label_cells(self, fields):
    """将同一行、相同 label 的相邻 engine4 cell 合并为一个字段"""
    if not fields:
        return fields
    merged = []
    fields_sorted = sorted(fields, key=lambda f: (f["fill_rect"][1], f["fill_rect"][0]))
    current = fields_sorted[0]
    for f in fields_sorted[1:]:
        same_row = abs(f["fill_rect"][1] - current["fill_rect"][1]) < 3.0
        same_label = f.get("label") == current.get("label")
        adjacent = f["fill_rect"][0] - current["fill_rect"][2] < 10.0
        if same_row and same_label and adjacent:
            # 合并：扩展 fill_rect
            current["fill_rect"] = (
                current["fill_rect"][0],
                min(current["fill_rect"][1], f["fill_rect"][1]),
                f["fill_rect"][2],
                max(current["fill_rect"][3], f["fill_rect"][3]),
            )
        else:
            merged.append(current)
            current = f
    merged.append(current)
    return merged
```

**泛化安全性：** 合并条件是"同行 + 同 label + 相邻"，不会误合并不同行或不同标签的字段。只对 engine4 产出生效。

**预期效果：** 018 Page 1 从 89 个 engine4 字段降到 ~30 个。

**优先级：P0** — 这是导致 018 恶化的直接原因。

---

#### B-008：engine1_underline 仍然被 carve 切分

**现象：** 018 Page 2 有 6 个 `(continued) underline_field`，Page 4 有 5 个 `(continued) 8. Determination date`。source 均为 `engine1_underline`。

**根因：** `_step2_carve` 只跳过了 `source.startswith("engine4")`，但 engine1_underline 字段如果跨越了 table grid 的竖线，仍然会被切分。

**证据：** detector.py:1286 — `if str(f.get("source", "")).startswith("engine4")` 只保护了 engine4。

**修复方案：**

方案 A：carve 只对**无标签**的字段执行切分（有标签的已经有了语义归属，不应该被机械切分）：
```python
if f.get("label") and f["label"] not in ("text_box", "underline_field"):
    result.append(f)
    continue
```

方案 B：carve 同时跳过 engine1 和 engine3（只保留对未来可能出现的大矩形的切分能力）：
```python
if not f.get("source", "").startswith("engine1_box"):
    # 除了 engine1_box 大矩形外，其他都不切
    result.append(f)
    continue
```

**建议采用方案 A**——基于语义（有标签就不切）比基于来源更通用。

**优先级：P1** — 影响 018 的 11 个碎片字段。

---

#### B-009：019 点线（dot-leader）完全无法检测

**现象：** 019 的所有实际可填字段（Name, Date of Birth, Member ID, Address, City, State, ZIP, Phone, Signature, Date, Doctor Name, Doctor Phone, Doctor Fax = 共约 15 个）**全部漏检**。engine2 触发后检出的 4 个 blank 都是垃圾（邮寄地址静态文本）。

**根因（已验证）：**
- 019 的填写行是**点号文本字符**（`"."`），不是画出来的线：
  ```
  Name line: "Name..................................." (221 chars)
  ```
  - "Name" 结束于 x=72.8，第一个 "." 开始于 x=72.7（无间隙！）
  - 每个 "." 是一个独立的 pdfplumber 字符，x0/x1 紧密相连
- Engine1 看不到：`get_drawings()` 只返回 19 条水平线，最长的是 y=148.3 和 y=312.9 的分割线，没有填写行区域的线段
- Engine2 看不到：字符之间没有 gap（dots 是连续的文本字符），`min_blank_width = 40.0` 的阈值永远不会被满足
- Engine3 看不到：checkbox 使用的可能是 glyph/symbol 而非矢量方块

**这是一个新的表单模式，当前 4 引擎架构完全无法处理。**

**修复方案——增加 dot-leader 检测（在 engine2 中扩展）：**

在 `engine2_detect_blanks` 的字符行分析中，增加对连续 "." 字符序列的识别：

```python
def _detect_dot_leaders(self, line_chars, line_top, line_bottom, page_width):
    """检测点线填写行：label + 连续点号 → fillable area"""
    sorted_line = sorted(line_chars, key=lambda c: float(c.get("x0", 0)))

    # 找到连续 "." 字符序列
    dot_start = None
    dot_count = 0
    label_end_x = 0

    for i, c in enumerate(sorted_line):
        if c.get("text") == ".":
            if dot_start is None:
                dot_start = i
                label_end_x = float(sorted_line[i-1].get("x1", 0)) if i > 0 else 0
            dot_count += 1
        else:
            if dot_count >= 10:  # 至少 10 个连续点号才算 dot-leader
                dot_end_x = float(sorted_line[dot_start + dot_count - 1].get("x1", 0))
                # 生成 fillable area
                yield {
                    "label_end_x": label_end_x,
                    "fill_x0": label_end_x + 2.0,
                    "fill_x1": dot_end_x,
                    "fill_y0": line_top,
                    "fill_y1": line_bottom,
                    "label_chars": sorted_line[:dot_start],
                }
            dot_start = None
            dot_count = 0

    # 处理行尾的 dot-leader
    if dot_count >= 10:
        dot_end_x = float(sorted_line[dot_start + dot_count - 1].get("x1", 0))
        yield { ... }
```

**泛化安全性：**
- `dot_count >= 10` 避免误检普通句号（"Mr. Smith" 只有 1 个点）
- 连续点号序列是 dot-leader 的唯一标识特征，误伤风险极低
- 这个模式在商业表单中非常普遍（保险表单、订单表等大量使用）

**优先级：P0** — 不修的话 019 类型的表单完全无法使用。

**替代方案：** 如果不在 preprocess 修，就需要 VLM 从图片中识别所有字段并回传坐标。但这要求 VLM 有精准的 bbox 回传能力，且违背了"preprocess 产出 rect, VLM 只做语义"的架构分工。

---

#### B-010：engine2 目录页/索引页假阳性

**现象：** 001 Page 2 是目录页（TABLE OF CONTENTS），engine2 检出 18 个 engine2_blank，全部是假阳性。

**证据：**
- `p2_f001` label = `"Part I – Certifications Concerning the Premises, the Building, and the Land"` — 这是目录标题
- `p2_f003` label = `"1. Conflicts of Interest"` — 这是目录条目
- 所有 18 个字段都是"目录条目 + 右侧页码之间的空白"被当作可填区域

**根因：** 目录页的排版是"标题/条目.........页码"，标题和页码之间有大段空白或点线。engine2 的字符间隙检测把这些间隙当成了可填空白。

**修复方案（简单高效）：**

在 engine2 的 blank 生成前增加**页码右对齐检测**：如果行尾字符是纯数字且靠近右边距，则整行跳过（这是目录/索引行的强特征）。

```python
# 在 engine2_detect_blanks 的 for line_chars in lines: 循环开头
last_chars_text = "".join(c.get("text","") for c in sorted_line[-3:]).strip()
if re.match(r'^\d{1,3}$', last_chars_text):
    last_x1 = float(sorted_line[-1].get("x1", 0))
    if last_x1 > page_width * 0.85:  # 右对齐页码
        continue  # 跳过整行
```

**泛化安全性：** 目录行特征（右对齐纯数字）在正常表单中不会出现。

**优先级：P1** — 影响有目录页的长文档（001 有 16 页但目录页贡献了 18 个假阳性）。

---

#### B-011：页脚装饰线被检测为 underline_field

**现象：** 001 的 Page 1, 3, 4, 11-16 各检出 1 个 `underline_field`，来自页面底部的装饰性水平线（如 "FDIC 3700/44 (12-18)  Page X of 16" 上方的分割线）。共 8 个假阳性。

**可视化确认：** 001 Page 1 的可视化中，底部有一条绿色标注的横线覆盖整个页面宽度（y≈727），这是页脚分割线。

**根因：** `engine1_detect_boxes` 的下划线过滤条件 `if not (50.0 < ln["y"] < page_height - 40.0)` 只排除了距页面底部 40pt 以内的线段。但 001 的页脚线在 y=727 处，而页面高度 792pt，727 < 792-40=752，所以通过了过滤。

**修复方案：** 增加**整页宽度下划线**的过滤——如果下划线宽度 > 页面宽度的 90%（即横跨整页的分割线），则视为装饰性线段跳过：

```python
if length > (page_width - page_rect[0]) * 0.9:
    continue  # 横跨整页的线段是页眉/页脚分割线
```

**泛化安全性：** 合法的填写下划线几乎不可能跨越整个页面宽度（总有 label 在左侧占据一部分空间）。

**优先级：P2** — 每个页脚只贡献 1 个假阳性，VLM 可以轻松过滤。但修复简单，可以顺手做。

---

#### B-012：008 Page 1 底部 11 个 text_box 假阳性仍存在

**现象：** `p1_f023` 到 `p1_f033` 共 11 个 `engine1_box` 字段，`label="text_box"`，`confidence=0.62`。这些绿色矩形框密集排列在页面底部 y=615~775 区域。

**可视化确认：** 008 Page 1 可视化中，页面下半部分有密集的绿色矩形条——这些区域在原始 PDF 中是空白的，没有任何文字或线段，但 `get_drawings()` 返回了矩形绘图元素。

**根因：** 这些矩形通过了 `w > 30, h > 12, w > h * 1.5` 的几何过滤但没有关联到任何文字标签。可能是 PDF 绘制的打印区域标记、裁切线或其他非用户可见元素。

**修复方案：** 对 `label` 为 `None`（被标记为 "text_box"）的 engine1_box 字段，增加**文字密度检查**——如果矩形内部及其周围（上方/左侧 30pt 范围内）没有任何 text_span，则降为低置信度或直接丢弃：

```python
# engine1_detect_boxes 矩形处理末尾
if label_text is None:
    # 检查矩形周围是否有文字（标签候选）
    nearby_spans = [s for s in text_spans
                    if abs(s["bbox"][1] - bbox[1]) < 30
                    or abs(s["bbox"][3] - bbox[3]) < 30]
    if not nearby_spans:
        continue  # 周围无文字的无标签矩形 → 丢弃
```

**优先级：P1** — 减少 008 Page 1 约 11 个假阳性。

---

#### B-013：008 Page 1 的 "verified and credited)" 等说明性文字框误检

**现象：**
- `p1_f017` label=`"verified and credited)"`, source=`engine1_box` — Q10 说明文字的矩形框
- `p1_f021/022` label=`"mortgage loan))."` — Q12 说明文字的矩形框
- `p5_f005` label=`"occurrence, and name/address of police d"` — Q18 说明文字框

**根因：** 这些矩形是说明性文字的边框（用来框住补充说明），内部已经有密集文字，不是用户需要填写的空白区域。当前 `_is_decorative_rect` 只检查填充颜色和面积比，没有检查内部文字密度。

**修复方案：** 与 B-012 相同的文字密度检查逻辑。如果矩形内部文字面积 > 矩形面积的 40%，则判定为说明框并跳过。

**优先级：P1** — 减少 008 每页 2-3 个假阳性。

---

### 15.4 各 PDF 逐页评价（更新）

#### 008 (US Courts AO 78) — 158 字段 → 修复后预期 ~70

| 页 | 字段数 | 评价 | 主要问题 |
|---|-------|------|---------|
| 1 | 33 | ⚠️ 中等 | 11 个 text_box 假阳性 (B-012)；3 个说明框误检 (B-013)；E-002 漏检 (未修)；E-003/E-006 ✅ 已修 |
| 2 | 53 | ⚠️ 中等 | 41 个 engine4 table_cell 较多但**基本合理**（7列×6行教育表格确实需要这么多单元格）；2 个 text_box 假阳性 |
| 3 | 32 | ✅ 良好 | 24 个 underline + 8 个 table_cell，Work Experience 检测正确 |
| 4 | 32 | ✅ 良好 | 同 Page 3 |
| 5 | 8 | ✅ 良好 | 3 个 checkbox + 3 个 underline + 1 个 text_box 假阳性 + 1 个说明框误检 |

**Page 2 的 41 个 engine4_table_cell 需要人工复核**——打开 `all_result_008_www.uscourts.gov_a28.pdf` Page 2，检查蓝色矩形框是否正确覆盖了教育表格的每个空白单元格（7 列 × 6 行 = 42 个单元格减去表头行 ≈ 35-36 个可填单元格 + 几个有标签的列头）。如果蓝色框与实际表格单元格 1:1 对应，则 41 个是正确的。

#### 013 (FDIC G-FIN-5) — 28 字段 → 修复后预期 ~25

基本无变化，质量已经较高。可能的改善：
- `p1_f001` "OMB #3064-0093" engine1_box — 可通过 DECORATIVE_LABEL_PATTERNS 过滤
- `p3_f001` "Public reporting burden..." engine1_box — 可通过文字密度过滤

#### 018 (DOL ETA-9141C) — 191 字段 → 修复后预期 ~55

| 页 | 字段数 | 评价 | 主要问题 |
|---|-------|------|---------|
| 1 | 93 | ❌ 严重 | 89 个 engine4_table_cell 中约 60 个是子单元格膨胀 (B-007)；2 个 engine1_underline 误检（"U.S. Department of Labor"、"IMPORTANT..."） |
| 2 | 40 | ⚠️ 中等 | 26 个 engine4 较多但部分合理；6 个 (continued) underline 碎片 (B-008)；"U.S. Department of Labor" 误检 |
| 3 | 17 | ✅ 良好 | engine4 + engine2 + checkbox 组合检测效果好 |
| 4 | 41 | ⚠️ 中等 | 30 个 engine4 大部分合理（工资表区域）；5 个 (continued) underline 碎片 (B-008)；"U.S. Department of Labor" 误检 |

**人工复核重点：** 打开 `all_result_018_www.dol.gov_ca277fcb.pdf` Page 1，检查蓝色矩形框。如果一个逻辑字段（如 "1. Legal Business Name *"）被多个蓝色小框覆盖而非一个大框，则确认 B-007 存在。

#### 019 (Aetna Diabetes) — 9 字段 → 修复后预期 ~17

| 页 | 字段数 | 评价 | 主要问题 |
|---|-------|------|---------|
| 1 | 9 | ❌ 失败 | 所有 9 个字段都是假阳性或无关检测；15 个实际可填字段全部漏检 (B-009) |

**可视化确认：** 019 的标注 PDF 清晰可见——"Your Information" 下方的 Name, Date of Birth, Member ID 等所有点线行**没有任何彩色标注框**。上方的误检集中在 MAIL TO 和营销文字区域。checkbox 区域（OneTouch Verio Flex / Accu-Chek Guide / Accu-Chek Guide Me / opt-out box）也完全没有标注。

#### 001 (FDIC Leasing) — 130 字段

| 页 | 字段数 | 评价 | 主要问题 |
|---|-------|------|---------|
| 1 | 1 | ❌ | 封面页，1 个页脚线假阳性 (B-011) |
| 2 | 19 | ❌ | 目录页，18 个 engine2 假阳性 (B-010) + 1 个页脚线 |
| 3 | 3 | ⚠️ | 说明页，3 个 underline 可能是超链接下划线（非填写区域） |
| 4 | 7 | ⚠️ | 说明页，"following address:" 下划线合理，其余可能是超链接 |
| 5 | 10 | ✅ 良好 | 7 个 True/False checkbox 正确，3 个 underline 合理 |
| 6-8 | 8/8/13 | ✅ 良好 | 同 Page 5，checkbox 检测优秀 |
| 9 | 34 | ⚠️ | 24 个 engine4_table_cell 需要人工验证 |
| 10 | 21 | ⚠️ | 13 个 underline + 8 个 table_cell 需人工验证 |
| 11-16 | 各 1 | ❌ | 说明页/附录页，各 1 个页脚线假阳性 (B-011) |

**人工复核重点：**
- Page 2：打开 PDF 确认整页都是目录，所有橙色框都应该删除
- Page 5-8：确认 True/False checkbox 检测是否正确
- Page 9-10：确认表格单元格和下划线是否覆盖了实际填写区域

#### 004 (DOL 790) — 100 字段

| 页 | 字段数 | 评价 | 主要问题 |
|---|-------|------|---------|
| 1 | 17 | ⚠️ | 4 个 engine1_box 需验证，6 个 table_cell 需验证 |
| 2 | 1 | ⚠️ | 仅 1 个 underline，可能欠检 |
| 3 | 7 | ✅ | 6 个 checkbox + 1 个 engine2_blank |
| 4 | 56 | ❌ | 39 个 engine4 子单元格膨胀（双语表格，类似 018 的 B-007）；10 个 engine2 检出有噪声 |
| 5 | 5 | ✅ | 4 个 checkbox + 1 个 table_cell |
| 6-10 | 1-4 | ⚠️ | 主要是 underline_field，需人工验证是否有漏检 |
| 11 | 0 | ❓ | 需确认是空白页还是有漏检 |

---

### 15.5 修复优先级汇总（更新）

#### P0 — 必须修复

| 编号 | 问题 | 影响 | 代码量 |
|------|------|------|--------|
| B-007 | engine4 同行同标签子单元格合并 | 018(−60), 004(−20) | ~30 行 |
| B-009 | 增加 dot-leader 检测 | 019(+15) | ~40 行 |
| E-002 | _classify_cell remaining_height 二次判定 | 008(+1) | ~10 行 |

#### P1 — 应该修复

| 编号 | 问题 | 影响 | 代码量 |
|------|------|------|--------|
| B-008 | carve 只对无标签字段执行切分 | 018(−11) | ~5 行 |
| B-010 | engine2 目录页/索引页过滤 | 001(−18) | ~5 行 |
| B-012 | engine1_box 无标签+无周围文字 → 丢弃 | 008(−11) | ~10 行 |
| B-013 | engine1_box 内部文字密度过高 → 丢弃 | 008(−5) | ~15 行 |

#### P2 — 锦上添花

| 编号 | 问题 | 影响 | 代码量 |
|------|------|------|--------|
| B-011 | 页脚整页宽度下划线过滤 | 001(−8) | ~3 行 |
| — | "U.S. Department of Labor" 等页头 underline 过滤 | 018(−4) | ~5 行（DECORATIVE_LABEL_PATTERNS） |

### 15.6 修复后预期效果（更新）

| PDF | 当前 | P0 后 | P0+P1 后 | 合理目标 |
|-----|------|-------|---------|---------|
| 008 | 158 | ~157 (+E-002) | ~70 (-text_box -说明框) | 70-80 |
| 013 | 28 | 28 | ~25 | 25-28 |
| 018 | 191 | ~130 (-子单元格合并) | ~55 (-carve碎片 -页头) | 50-60 |
| 019 | 9 | ~20 (+dot-leader) | ~17 (-垃圾engine2过滤) | 15-18 |
| 001 | 130 | 130 | ~105 (-目录-页脚) | 需人工确认 |
| 004 | 100 | ~80 (-子单元格合并) | ~70 | 需人工确认 |

### 15.7 关于 YOLO 的再确认

**结论不变：不采用 YOLO。**

新增的两个 PDF（001、004）进一步验证了这个判断：
- 001 的主要问题是假阳性过多（目录页、页脚线），YOLO 只会让假阳性更多
- 004 的子单元格膨胀问题与 018 相同，YOLO 无法解决表格列合并问题
- 019 的 dot-leader 问题需要字符级分析，YOLO 做不到（YOLO 是像素级检测）

### 15.8 VLM 阶段的输入质量评估

假设 P0+P1 全部修复后：

| PDF | 预期字段数 | 假阳性率 | 漏检率 | VLM 负担 |
|-----|---------|--------|-------|---------|
| 008 | ~70 | <10% | <5% (仅 E-001 合并问题) | **低** — 只需过滤少量假阳性 + 拆分 Name/Phone |
| 013 | ~25 | <10% | <5% | **极低** — 几乎可以直接使用 |
| 018 | ~55 | <15% (FOR DEPT USE ONLY 区域) | <5% | **低** — 主要过滤 "FOR DEPARTMENT USE ONLY" 下方字段 |
| 019 | ~17 | <10% | ~20% (checkbox 漏检) | **中等** — 需要补充 checkbox 检测 |
| 001 | ~105 | <15% | 需人工确认 | **中等** — 长文档，需要 VLM 过滤说明页内容 |
| 004 | ~70 | <15% | 需人工确认 | **中等** |

**总体判断：修复 P0+P1 后，preprocess 的输出质量可以满足 VLM 阶段的输入要求。** VLM 的主要工作是：
1. 确认哪些 field 是真正需要填写的（过滤假阳性）
2. 分组和语义标注
3. 对 E-001 类合并字段进行拆分
4. 补充 019 类表单的 checkbox 检测

### 15.9 人工复核指南

你需要人工查看以下标注 PDF，重点关注我无法通过代码验证的部分：

#### 必查项

1. **018 Page 1** — `TestSpace/preprocess_results/05_integration/all_result_018_www.dol.gov_ca277fcb.pdf`
   - 目的：确认 B-007 子单元格膨胀现象
   - 看什么：蓝色矩形框（engine4_table_cell）。如果一行内有多个相同标签的小蓝框并排排列（如 "1. Legal Business Name *" 被 6 个小蓝框覆盖），则 B-007 成立
   - 与原始 PDF 对比：`TestSpace/pdf_pipeline/output/selected/native/018_www.dol.gov_ca277fcb5e4db464_9141C.pdf`

2. **008 Page 2** — `all_result_008_www.uscourts.gov_a28.pdf` Page 2
   - 目的：验证教育表格的 41 个 engine4_table_cell 是否合理
   - 看什么：蓝色矩形框是否与教育表格的每个空白单元格 1:1 对应。如果是，则 41 个合理；如果有重叠或错位，则需要进一步分析

3. **001 Page 2** — `all_result_001_www.fdic.gov_a0aa537.pdf` Page 2
   - 目的：确认目录页假阳性
   - 看什么：橙色矩形框（engine2_blank）。如果所有橙色框都出现在目录条目和页码之间的空白处，则 B-010 成立

4. **001 Pages 5-8** — 同上 PDF Page 5-8
   - 目的：验证 True/False checkbox 检测质量
   - 看什么：红色矩形框（engine3_checkbox）是否准确覆盖了每个 True/False 选择区域

#### 可选查项

5. **004 Page 4** — `all_result_004_www.dol.gov_4ece685d.pdf` Page 4
   - 目的：确认双语表格的子单元格膨胀是否与 018 类似

6. **001 Pages 9-10** — 同上 PDF
   - 目的：确认表格区域的 engine4 检测是否正确


---

## 16. 第三轮补记（2026-03-22）

> 说明：本节为 2026-03-20 之后的补记，只记录此前文档未落盘的修复与 debug，不重复旧内容。

### 16.1 本轮新增问题与修复（补记）

#### B-014：004 大单元格内 `a)/b)/c)/d)` 子项未拆分，导致 FEIN/Telephone/Fax/E-mail 漏出可填框

**现象：**
- 在 `004` 的综合结果中，`a) Federal Employer Identification Number (FEIN)`、`b) Telephone Number`、`c) Fax Number`、`d) E-mail Address` 没有独立可填区域。

**原因：**
- 旧逻辑主要按“单元格级”产出字段，未对同一单元格内部的枚举子项做稳定拆分。

**修复：**
- 扩展枚举前缀规则，支持 `a.`/`A.`/`1.`、`a)`/`A)`/`1)`、`a:`/`1:`。
- 在 engine4 中对“可填单元格且枚举命中>=2行”也触发子项拆分（不再只限 label cell）。
- 子项填充区域支持三路候选：右侧空白、右侧下划线、下方空白区域。

**改动位置：**
- `backend/app/services/native/detector.py`
  - `ENUM_PREFIX_RE / ENUM_PREFIX_EMBEDDED_RE`
  - `_extract_subfields_from_enumerated_label_cell`
  - `engine4_synthesize_table_fields` 的 `should_try_subfields` 分支

**效果：**
- 004 中 `a)/b)/c)/d)` 类字段可稳定产出独立 `engine4_table_cell`（紫框+蓝框）。

---

#### B-015：004 中“文本识别到了，但没有给 fill_rect”（尤其长句问题 14/15、地址类提示）

**现象：**
- 问题文本存在，但未生成可填写区域；可视化上只有文本，没有对应框。

**原因：**
- 旧逻辑偏向“同行右侧空白”，对“标签下方是一大片空白”的版式覆盖不足。

**修复：**
- 新增全局 prompt fallback：`_extract_prompt_below_blank_fields`。
- 只要是 prompt-like label（枚举开头或包含 `:`），都会尝试：
  1. 先找右侧可填区域；
  2. 右侧不成立时，尝试下方大空白区域；
  3. 用文字密度阈值（覆盖率 <= 8%）避免把说明段误当填写区。
- 通过 `_find_prompt_horizontal_bounds` 结合矢量竖线约束左右边界，避免越界。

**改动位置：**
- `backend/app/services/native/detector.py`
  - `_is_prompt_like_label`
  - `_find_prompt_horizontal_bounds`
  - `_extract_prompt_below_blank_fields`
  - `engine4_synthesize_table_fields` 中 fallback 注入

**效果：**
- 004 的长提示行（含问题 14/15 类）在“右侧无明显空白”时可回退到“下方空白”产出填写框。

---

#### B-016：`From / Desde:` 与 `To / Hasta:` 同行相邻时，`From` 框吞并 `To` 区域

**现象：**
- `From` 的 fill_rect 过宽，侵入 `To` 的填写区。

**原因：**
- 冒号标签右侧扩展默认到行尾，未考虑“同一行后续还有下一个 prompt 标签”。

**修复：**
- 在 colon 分支新增“同行下一个 prompt”截断：
  - 找到下一标签 `x0` 后，将当前 `right_cap` 限制到 `next_prompt_x0 - 2`。

**改动位置：**
- `backend/app/services/native/detector.py`
  - `_extract_prompt_below_blank_fields`（same-row next prompt cap）

**效果（004 Page 1 实测）：**
- `From / Desde:` `fill_rect = [385.97, 456.51, 460.77, 467.04]`
- `To / Hasta:` `fill_rect = [508.74, 456.51, 596.97, 467.04]`
- 两者分离，不再互相吞并。

---

#### B-017：用户反馈“紫色切分线过度切块”

**现象：**
- 一些字段在几何修正阶段被继续切碎，视觉上紫色分割过多。

**原因：**
- carve 阶段对多类型字段都可能触发切分。

**修复：**
- `carve` 收敛为仅对 `engine1_box` 生效，其余 source 全部跳过。

**改动位置：**
- `backend/app/services/native/detector.py`
  - `_step2_carve`：`source != engine1_box` 直接保留

**效果：**
- `engine1_underline` / `engine2_blank` / `engine4_table_cell` 不再被 carve 二次切碎。

---

#### B-018：008 `Name` 与后续表格字段重叠风险（要求“rect 不能与表格字段重叠”）

**现象：**
- 用户观察到 `Name` 区可能压到后续字段（如 phone 行），担心跨字段覆盖。

**原因：**
- 非表格引擎框（engine1/2）在校正后可能大面积压住 table cell。

**修复：**
- 新增表格重叠阻断步骤：
  - 对非 `engine4_table_cell` 且非 checkbox 字段，若与任一 table cell 重叠比例 > 0.35，则丢弃。

**改动位置：**
- `backend/app/services/native/detector.py`
  - `_step8_block_table_overlap`
  - `correct_fields` 流程接入 step8

**效果（008 实测）：**
- `Name` 与 `2. Phone Number` 重叠面积 = `0.0`。
- 非表格字段与 table field 的重叠违规数（>0.35）= `0`。

---

#### B-019：目录页（TOC）仅跳过 engine2（含 dot-leader）

**现象：**
- 目录页会触发大量 engine2 假阳性。

**修复：**
- 增加 `_is_toc_page` 判定（`table of contents` 或右侧页码行>=5）。
- 在 `detect_page` 中：TOC 页只禁用 engine2；engine1/3/4 继续执行。

**改动位置：**
- `backend/app/services/native/detector.py`
  - `_is_toc_page`
  - `detect_page` 中 engine2 触发门控

**效果：**
- 满足“TOC 只跳 engine2，不影响其他引擎”的策略。

---

#### B-020：B-012 实施落地（本轮确认）

**现象：**
- 008 底部存在一批无标签 text_box 假阳性。

**修复：**
- 对 `engine1_box` 增加过滤：`label_text is None` 且上方 `20pt` 内无文字时，直接跳过。

**改动位置：**
- `backend/app/services/native/detector.py`
  - `engine1_detect_boxes`
  - `_has_text_above_rect(max_gap=20.0)`

**效果：**
- 无语义、无上下文支撑的孤立文本框显著减少。

### 16.2 本轮测试与结果产物

#### 定向复测（2026-03-22）
- 命令：`test_all_engines.py --input 004`、`--input 008`
- 结果：
  - 004：`Total fields = 121`
  - 008：`Total fields = 147`
- 关键验证：
  - 004：`From / Desde:`、`To / Hasta:` 已有独立 `fill_rect`
  - 008：`Name` 与 `Phone` 无重叠

#### 全量回归（2026-03-22, run `20260322T110415Z`）
- `TOTAL=33 PASS=33 FAIL=0`
- 汇总文件：`TestSpace/preprocess_results/run_logs/20260322T110415Z_colon_contains_summary.tsv`
- 全日志：`TestSpace/preprocess_results/run_logs/20260322T110415Z_colon_contains_full_preprocess_and_tests.log`

#### 当前综合可视化输出（最新）
- `TestSpace/preprocess_results/05_integration/all_result_004_www.dol.gov_4ece685d.pdf`
- `TestSpace/preprocess_results/05_integration/all_result_004_www.dol.gov_4ece685d.json`
- `TestSpace/preprocess_results/05_integration/all_result_008_www.uscourts.gov_a28.pdf`
- `TestSpace/preprocess_results/05_integration/all_result_008_www.uscourts.gov_a28.json`

### 16.3 结论（补记）

- 004 中“冒号/分项字段无填充框”的主问题已完成修复并落盘。
- 008 中“跨字段重叠”已加入硬阻断，当前验证通过。
- 本轮按你的策略执行：`B-013` 继续不做，仅保留 `B-012`。

---

## 17. Preprocess v2 重构后首次审查（2026-03-22）

### 17.0 概述

v2 基于 "Label-first" 架构完成重构，代码位于 `backend/app/services/native/preprocess/`，测试位于 `TestSpace/preprocess_test_v2/`。

6份测试 PDF 全部通过 constraint 硬性检查（no_fill_rect=0, rect_overlap=0, rect_left_of_label=0, rect_exceeds_page=0），Gate3/Gate5 也全部 PASS。018 page 1 从 v1 的 78 字段降至 34 字段，表明 label-first + dedup 架构有效解决了 v1 的核心重复问题。

**测试总结：**

| PDF | Pages | Total Fields | Hard Constraints | duplicate_label (warn) |
|-----|-------|-------------|-----------------|----------------------|
| 001 | 16 | 167 | PASS | 18 |
| 004 | 11 | 88 | PASS | 17 |
| 008 | 5 | 94 | PASS | 31 |
| 013 | 3 | 39 | PASS | 4 |
| 018 | 4 | 91 | PASS | 0 |
| 019 | 1 | 12 | PASS | 0 |

Phase3 dedup 效果显著：018 page 1 从 107 raw → 42 unique（去除 65 重复）。所有页面 residual_dup=0。

---

### 17.1 BUG-V2-001: Underline 收集器误收超链接/强调下划线

**严重程度：中**

**现象：** 004 page 10 有 3 个 underline labels，全部是 URL 文本或被强调的文本，而非表单字段：

```
src=underline     text='http://www.foreignlaborcert.doleta.gov/adverse.cfm...'
src=underline     text='Hourly Rate Equivalent'
src=underline     text='http://www.dol.gov/opa/media/press/eta/ETA20111794fs.pdf .'
```

这些文本下方的水平线是超链接下划线或强调线，不是表单填写区的下划线。Phase 4 正确地未能为它们分配 fill_rect（最终 0 个 field），但它们不应进入 Phase 2 的 label 收集。

**根因：** `_collect_underline_labels` 仅过滤了 table border 线和长度 < 40 的短线，但没有过滤：
1. 文本内容为 URL 的情况（以 `http://` 或 `www.` 开头）
2. 下划线恰好在文本正下方且完全覆盖文本宽度的情况（这是强调线/超链接线，不是填写区下划线）

**建议修复：**

```python
# 在 _collect_underline_labels 中增加 URL 过滤
if re.match(r'^https?://', text) or re.match(r'^www\.', text):
    continue

# 增加"下划线完全覆盖文本"检测（强调线判定）
# 如果下划线起点在文本左边界附近，且终点在文本右边界附近，说明是文字强调线
label_bbox = best_label["bbox"]
label_x0, label_x1 = label_bbox[0], label_bbox[2]
underline_coverage = (min(x1, label_x1) - max(x0, label_x0)) / max(1.0, label_x1 - label_x0)
if underline_coverage > 0.85 and x0 <= label_x0 + 5.0:
    continue  # 下划线几乎完全覆盖文本 → 是强调线，跳过
```

---

### 17.2 BUG-V2-002: "underline_field" 回退标签产生大量无意义重复

**严重程度：中**

**现象：** 当 underline 收集器找不到下划线左侧的文本时，回退到上方文本或默认标签 "underline_field"。在有多个独立下划线的页面中产生大量同名字段：

```
001 Page 9:  5 个 "underline_field"
001 Page 10: 8 个 "underline_field"
004 Page 4:  2 个 "underline_field"
013 Page 1:  4 个 "underline_field"
```

这些字段虽然 fill_rect 各不相同，但标签完全一致，对 VLM 阶段和最终用户都没有区分价值。

**根因：** `_collect_underline_labels` 第 119 行的 fallback 逻辑：
```python
label_text = ... if above_label else "underline_field"
```

**建议修复：** 用位置信息生成唯一标签：
```python
label_text = f"field_line_{int(y)}"  # 或 f"p{page_num}_line_{idx}"
```
或者，使用上方文本 + 行号组合来生成更有意义的标签。

**需要确认：** 这个问题对 VLM 阶段的影响有多大？如果 VLM 主要依赖 fill_rect 位置而非 label 文本，则优先级可降低。

---

### 17.3 BUG-V2-003: 节标题被 enum 收集器误检为字段标签

**严重程度：中**

**现象：** 018 page 1 的检测结果中包含明显的节标题：

```
p1_f001  enum  conf=0.65  label='U.S. Department of Labor'
p1_f003  enum  conf=0.65  label='A. Employment-Based Visa Information'
```

"U.S. Department of Labor" 不是表单字段。"A. Employment-Based Visa Information" 是节标题，不是可填写字段。

**根因：** `_collect_enum_labels` 检测以 `A.`、`1.` 等编号开头的文本行，但没有对节标题做特殊过滤。v1 中有 `_is_section_header` 检查和 `SECTION_HEADER_PENALTY`，但 v2 的 enum 收集器没有应用它。

**建议修复：**

```python
# 在 _collect_enum_labels 第一轮循环中增加
if self._is_section_header(content_after_prefix):
    continue
# 或者用更宽泛的规则：如果去掉编号前缀后剩余文本全大写且 ≤4 词，跳过
```

但需要注意：某些表单中编号项确实是字段（如 "1. Name"），需要区分"节标题"和"带编号的字段标签"。

**需要确认：** 对于 v2，是否希望在 Phase 2 就过滤节标题，还是交给 VLM 过滤？如果交给 VLM，则此项可标记为低优先级。

---

### 17.4 BUG-V2-004: Unicode PUA 字符被当作表格标签收集

**严重程度：低**

**现象：** 004 page 4 有多个 `\uf071` 标签（Unicode 私有区字符，通常是 checkbox 图标字体）：

```
table  conf=0.66  label='\uf071'
table  conf=0.66  label='\uf071'
underline  conf=0.5  label='\uf071'
```

**根因：** `_collect_table_labels` 调用了 `_is_instructional_text` 和长度过滤，但没有检查 `_is_checkbox_glyph`。包含 PUA 字符的文本通常是 checkbox 图标或装饰符号。

**建议修复：**

```python
# 在 _collect_table_labels 和 _collect_underline_labels 中增加
if self._is_checkbox_glyph(combined_text):
    continue
```

同时应在 `_is_checkbox_glyph` 方法中扩展 PUA 范围检查，确保 `\uf071` 等字符被覆盖。目前的 `0xF000 <= ord(ch) <= 0xF0FF` 应该已经覆盖了 `\uf071`，但 `_collect_table_labels` 没有调用此方法。

---

### 17.5 BUG-V2-005: "$ $" 等占位符文本被当作表格标签

**严重程度：低**

**现象：** 004 page 4 有多个仅包含 `$ $` 的表格标签：

```
table  conf=0.66  label='$ $'
table  conf=0.66  label='$ $'
table  conf=0.66  label='$ $'
```

这些是金额栏的格式占位符（类似于 `$____`），不是有意义的字段标签。

**根因：** `_collect_table_labels` 没有过滤纯符号/短占位符文本。

**建议修复：**

```python
# 增加有效内容检测
alpha_count = sum(1 for ch in combined_text if ch.isalpha())
if alpha_count < 2:
    continue  # 纯符号或单字母不是有意义的标签
```

---

### 17.6 BUG-V2-006: "NO" 被检测为 underline 字段标签

**严重程度：低**

**现象：** 008 page 1 中 "NO" 出现两次作为 underline 标签：

```
underline  conf=0.74  label='NO'
underline  conf=0.74  label='NO'
```

这是 YES/NO checkbox 选项文本，位于 checkbox 旁边，恰好其右侧有一条下划线。

**根因：** v1 对 YES/NO 文本有 `YES_NO_LABEL_PENALTY = 150.0` 的惩罚分数，会降低匹配优先级。但 v2 的 `_collect_underline_labels` 使用 `_find_text_left_of` 直接找最近的左侧文本，没有 YES/NO 惩罚机制。

**建议修复：**

```python
# 在 _collect_underline_labels 中增加 YES/NO 过滤
if re.match(r'^(YES|NO|Yes|No|yes|no)$', text.strip()):
    continue
```

或者将 confidence 大幅降低，让其在 dedup 阶段被同位置的 checkbox 覆盖。

---

### 17.7 DESIGN-V2-001: v2 未使用 engine1_box（显式矩形框）作为 fill_rect 来源

**严重程度：待评估**

**现象：** v1 的 engine1_box 检测 PDF 中显式绘制的矩形框（如输入框、文本框），直接将矩形作为 fill_rect，是最高置信度来源（0.84）。v2 的 label-first 流程不检测显式矩形，仅通过 `_find_right_blank` / `_find_below_blank` 从空白空间推断 fill_rect。

**影响分析：** 从当前 6 份测试 PDF 的结果看，v2 通过 underline / table / blank space 检测，仍然能覆盖大部分字段。但对于使用大面积矩形框作为输入区域的 PDF（非表格场景），v2 的 fill_rect 精度可能不如 v1。

**当前状态：** 所有 6 份 PDF 的 constraint 检查全部 PASS。未观察到明显的字段遗漏。但测试集较小，不能排除在其他 PDF 上出现问题。

**需要确认：** 是否要在 Phase 4 中增加"检测显式矩形框"作为额外的 fill_rect 候选来源？实现方式可以是：
- 在 `_assign_fill_rects` 中，如果 `_find_right_blank` 和 `_find_below_blank` 都失败，尝试查找 label 附近的显式矩形绘图
- 或者新增一个 `_find_rect_box` 方法，在 drawing_data 中查找匹配的矩形

---

### 17.8 WARN-V2-001: 008 duplicate_label 警告数量高（31个）

**严重程度：信息/预期行为**

**现象：** 008 (AO-78 求职表) 有 31 个 duplicate_label 警告，主要来源：
- Page 3 和 Page 4 是完全相同的"就业历史"重复页面，所有字段标签天然重复（"from:", "to:", "city", "state", "per" 等）
- "underline_field" 回退标签重复

**结论：** 跨页面的相同标签名不应视为问题 — 这是设计如此的重复表格页。可以考虑将 duplicate_label 检查改为仅检查同一页面内的重复，或标注哪些重复来自同页 vs 跨页。

---

### 17.9 总结与优先级

| 编号 | 问题 | 严重程度 | 建议 |
|------|------|---------|------|
| V2-001 | URL/强调线被误收为 underline 标签 | 中 | 增加 URL 过滤 + 强调线检测 |
| V2-002 | "underline_field" 回退标签重复 | 中 | 用位置信息生成唯一标签 |
| V2-003 | 节标题被 enum 误检 | 中 | 增加 section_header 过滤（或交给 VLM） |
| V2-004 | PUA 字符被当作标签 | 低 | 增加 checkbox_glyph 检查 |
| V2-005 | "$ $" 占位符被当作标签 | 低 | 增加最少字母数过滤 |
| V2-006 | YES/NO 被检测为 underline 标签 | 低 | 增加 YES/NO 过滤 |
| V2-007 | 无 engine1_box fill_rect 来源 | 待评估 | 需确认是否需要补充 |
| V2-008 | 008 duplicate_label 高 | 信息 | 预期行为，可优化检查逻辑 |

**需要你确认的问题：**

1. **V2-003（节标题误检）**：在 Phase 2 阶段过滤节标题，还是交给 VLM 阶段处理？
2. **V2-007（缺少 engine1_box）**：是否需要在 Phase 4 中补充显式矩形框检测？当前测试集全部通过，但覆盖面不够广。
3. **V2-002（underline_field 回退标签）**：VLM 阶段是否依赖 label 文本？如果 VLM 主要看 fill_rect 位置，此问题优先级可以降低。
