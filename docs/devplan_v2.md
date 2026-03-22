# SmartFill v2 开发计划 — Native PDF 智能填写

> 文档定位：v2 整体架构与大方向规划主文档。  
> 记录范围：只记录架构目标、模块边界、阶段路线与关键架构变更。  
> 排除范围：不记录具体 debug 过程、错误日志或临时排障细节。  
> 更新规则：当 v2 大方向或架构发生变化时，统一追加到本文件。  
> 边界说明：`dev_v1` 相关文档与实现保持不动，仅作为历史基线。  

> 版本：v2.0
> 创建时间：2026-03-13
> 状态：规划中

---

## 1. 项目定位与目标

### 1.1 v2 定位

v1 解决了 Fillable PDF（带 AcroForm 字段）的自动填写问题。v2 的目标是攻克 **Native PDF**（无表单字段，只有静态文字和线条的 PDF）的智能填写。

当前版本 **不考虑**：
- Fillable PDF（v1 已解决，代码保留不动）
- 扫描件/图片 PDF（未来 v3 方向）
- XFA Forms（极少见，暂不支持）

### 1.2 目标 PDF 范围

- 英语表单，有清晰表格线条的政府/保险/申请表单
- 典型代表：TestSpace/Native.pdf（瑞士健康保险表单）
- 预留接口支持未来扩展到其他语言和表单类型

### 1.3 产品目标

**不追求 100% 准确填写**，而是追求：

| 指标 | 目标 |
|------|------|
| 填写速度 | 用户上传到获得结果 < 30 秒 |
| 字段识别率 | ≥ 95%（不遗漏字段） |
| 填写准确率 | ≥ 90%（字段内容匹配正确） |
| 坐标精度 | 文字不超出单元格边界，视觉上整齐 |

剩余 10% 的错误或困难 case，通过 **用户手动预览+编辑** 来兜底（v2.1 实现）。

### 1.4 产品终极交互流程

```
v2.0: 上传 PDF → 输入信息 → AI 填写 → 下载
v2.1: 上传 PDF → 输入信息 → AI 填写 → 预览 → 手动微调 → 确认下载
```

---

## 2. 技术方案

### 2.1 核心原理

Native PDF 填写的本质 = **准确的 rect + 正确的内容**。

浏览器手动填写 PDF 时，创建的是 FreeText Annotation（`/Subtype /FreeText`）。我们用 pymupdf 的 `page.add_freetext_annot()` 实现同样的效果，不直接操作 PDF 源码。

### 2.2 两阶段混合方案

**核心原则：程序能做的不交给 AI，AI 只做"理解"这一件事。**

```
阶段 A: 程序化检测（pymupdf，保证不遗漏）
├── 提取所有 text spans + 精确坐标
├── 提取所有 drawings（线条/矩形/表格边框）
├── 规则推断: 候选字段列表（label + 填写区域 rect）
├── checkbox 检测: 找小正方形 + 特殊字符（☐ = \uf071）
└── 表格结构分析: 行列识别

阶段 B: VLM 语义理解（1 次调用，保证分组正确）
├── 输入: PDF 渲染图片 + 阶段 A 的候选列表 + 用户信息
├── 输出: 确认/过滤/分组/命名 + 填写内容映射
└── checkbox 选择判断
```

**为什么不用纯 VLM：**
- VLM 不擅长穷举（容易遗漏字段），但擅长语义理解
- VLM 给出的坐标是像素估算，有误差；程序提取的坐标是 PDF 原生精度
- 程序化检测成本为 0 token，< 1 秒

**同行对比：**

| 方案 | 代表 | 字段检测 | 语义理解 | 坐标精度 |
|------|------|---------|---------|---------|
| 纯规则 | Adobe Acrobat "Prepare Form" | 矢量分析 + 启发式 | 无 | 高 |
| 纯深度学习 | LayoutLMv3 + FUNSD | 需 OCR + 微调 | 关系抽取模型 | 中 |
| 纯 VLM | 直接用 GPT-4o | VLM 识别 | VLM 理解 | 低（像素级） |
| **混合（我们）** | Instafill.ai 类似 | pymupdf 矢量分析 | VLM 理解 | **高（PDF 原生）** |

Instafill.ai（目前最完整的商业 PDF 填写工具）也是这个架构：PyMuPDF 矢量分析做检测（95-98% 准确率），GPT 只做语义匹配。区别是他们用大量手写规则，我们用 VLM 视觉理解替代，更通用。

### 2.3 已识别的技术难点

| # | 难点 | 说明 | 解决思路 |
|---|------|------|---------|
| 1 | 字段分组 | "Name:" 和右边空白是一组，同行多个字段要分开 | 程序检测表格结构 + VLM 视觉理解 |
| 2 | 不遗漏字段 | 表格多行、小勾选框、页面底部字段容易漏 | 程序化穷举检测（宁多勿漏），VLM 过滤确认 |
| 3 | 语义匹配 | 用户信息映射到字段 | VLM/LLM（v1 已验证可行） |
| 4 | Rect 精度 | 文字不能溢出、位置要准确 | 从 drawings 的表格线精确计算，不依赖 VLM |
| 5 | Checkbox 勾选 | 不是填文字，需要画 ✓ 或 X | 检测小正方形 + `\uf071` 字符，VLM 判断选哪个 |
| 6 | 表格多行字段 | 如"家庭成员"表格，结构重复 | 程序检测行列结构，VLM 理解语义 |
| 7 | 文字溢出 | 长文本超出 rect 宽度 | 计算文字像素宽度，超出则缩小字号 |
| 8 | 字体一致性 | 填入文字的字体/字号/颜色要和原表单协调 | 从相邻 text span 读取字体信息来匹配 |

---

## 3. 代码架构

### 3.1 设计原则

- v1 Fillable PDF 代码**不动**，保持向后兼容
- v2 Native PDF 代码**新建独立模块**，pipeline 完全隔离
- 共享基础设施（文件管理、验证、配置、API 入口）
- 后端根据 PDF 类型自动分流到不同 pipeline
- VLM 接口抽象，支持通过配置文件切换模型

### 3.2 目录结构

```
backend/app/
├── main.py                          # 不变
├── config.py                        # 扩展：VLM 配置
├── routers/
│   └── pdf.py                       # 扩展：新增 native PDF 路由，自动分流
├── services/
│   ├── pdf_classifier.py            # 新增：PDF 类型分类器
│   ├── fillable/                    # v1 代码移入（重命名导入路径）
│   │   ├── __init__.py
│   │   ├── pdf_service.py           # 原 pdf_service.py
│   │   └── ai_service.py           # 原 ai_service.py
│   ├── native/                      # v2 新代码
│   │   ├── __init__.py
│   │   ├── detector.py             # 程序化字段检测（pymupdf）
│   │   ├── vlm_analyzer.py         # VLM 语义分析（调用 vlm 接口）
│   │   ├── writer.py               # FreeText Annotation 写入
│   │   └── pipeline.py             # 整合：检测 → 分析 → 写入
│   └── vlm/                         # VLM 接口抽象
│       ├── __init__.py
│       ├── base.py                 # 抽象基类
│       ├── qwen_vl.py             # 通义千问 VL 实现
│       └── openai_vl.py           # GPT-4o 实现
├── models/
│   └── schemas.py                   # 扩展：Native PDF 相关数据模型
├── utils/
│   ├── file_handler.py              # 不变
│   └── validators.py                # 不变
└── tests/
    └── fixtures/                    # 测试用 PDF 文件
        ├── native_insurance.pdf     # 有表格线的保险表单
        ├── native_application.pdf   # 申请表
        └── native_simple.pdf        # 简单表单
```

### 3.3 关键数据模型

```python
# --- 程序化检测输出 ---

class TextSpan:
    """PDF 中的一个文字片段"""
    text: str                    # 文字内容
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    font_name: str
    font_size: float

class DetectedField:
    """程序检测出的候选字段"""
    label: str                   # label 文字（如 "Name :"）
    label_bbox: tuple            # label 的精确坐标
    fill_rect: tuple             # 推断的填写区域 rect
    field_type: str              # "text" | "checkbox" | "date" | "table_cell"
    page_num: int
    confidence: float            # 检测置信度
    options: list[str] | None    # checkbox 的选项列表

class PageStructure:
    """一页 PDF 的结构化信息"""
    page_num: int
    text_spans: list[TextSpan]
    drawings: list[Drawing]
    detected_fields: list[DetectedField]
    table_structures: list[TableStructure]

# --- VLM 分析输出 ---

class AnalyzedField:
    """VLM 确认后的字段"""
    semantic_name: str           # 语义名称（如 "applicant_name"）
    label: str                   # 显示 label
    fill_rect: tuple             # 最终精确 rect
    field_type: str
    fill_value: str              # 要填入的值
    page_num: int
```

### 3.4 API 设计

v2 对外 API 保持和 v1 兼容，统一入口，内部自动分流：

| 端点 | 变化 | 说明 |
|------|------|------|
| `POST /upload` | 不变 | 上传 PDF |
| `POST /extract-fields` | 扩展 | Fillable → 原逻辑；Native → 程序检测 + VLM 分析 |
| `POST /fill` | 扩展 | Fillable → 原逻辑；Native → VLM 匹配 + FreeText 写入 |
| `POST /fill-by-fields` | 不变 | 调试用 |
| `GET /health` | 不变 | 健康检查 |

分流逻辑在 router 层：
```python
pdf_type = classifier.classify(pdf_path)  # "fillable" | "native" | "scanned" | "xfa"
if pdf_type == "fillable":
    # 走 v1 现有流程
elif pdf_type == "native":
    # 走 v2 新流程
else:
    raise HTTPException(400, "暂不支持此类型 PDF")
```

---

## 4. 开发阶段

### Phase 0: 基础设施重构

**目标**：重组代码目录结构，实现 PDF 分类器，v1 功能不受影响。

**任务**：
1. 将现有 `pdf_service.py` 和 `ai_service.py` 移入 `services/fillable/` 目录
2. 更新所有 import 路径，确保 v1 功能正常
3. 实现 `pdf_classifier.py`：基于 AcroForm 检测区分 fillable/native/scanned
4. 修改 `routers/pdf.py`：在 `/extract-fields` 和 `/fill` 中加入分类分流逻辑
5. `config.py` 扩展：VLM 相关配置项
6. `requirements.txt` 新增：`pymupdf`（用于 native PDF 处理）

**验证标准**：
- [ ] 上传 Fillable PDF → 走 v1 流程 → 结果和重构前完全一致
- [ ] 上传 Native PDF → 分类为 "native" → 返回明确的"暂不支持"提示（而非之前的"请上传可编辑PDF"）
- [ ] 上传扫描件 → 分类为 "scanned" → 返回"暂不支持"提示
- [ ] 所有现有测试通过

**测试 PDF**：TestSpace/Fillable.pdf、TestSpace/Native.pdf

---

### Phase 1: 程序化字段检测

**目标**：用 pymupdf 从 Native PDF 中提取所有结构化信息，推断出候选字段列表。这是整个 pipeline 的基础，要求**宁多勿漏**。

**任务**：
1. 实现 `native/detector.py`：
   - `extract_text_spans()`: 提取所有文字片段 + 精确坐标 + 字体信息
   - `extract_drawings()`: 提取所有绘图路径（线条、矩形、表格边框）
   - `detect_table_structure()`: 从 drawings 中推断表格的行列结构（水平线 = 行分隔，竖直线 = 列分隔）
   - `detect_text_fields()`: 基于"label 右侧/下方的空白区域在表格单元格内"推断文本输入字段
   - `detect_checkboxes()`: 检测小正方形 + `\uf071`/`\uf06f` 等特殊 checkbox 字符
   - `detect_all()`: 整合以上，输出 `PageStructure`

2. 实现关键检测规则：
   - 表格单元格识别：从 drawings 找水平线和竖直线的交点，构建网格
   - Label-Field 配对：label 在单元格左侧，填写区在 label 右端到单元格右边框之间
   - 跨行字段：某些 label 占两行（如 "Post code & city\n(in Switzerland) :"），需要合并
   - Checkbox 分组：同一行的多个 checkbox 属于同一个问题（如 Marital Status 的 5 个选项）

**验证标准**：
- [ ] 对 Native.pdf 第 1 页，检测出所有文本输入字段（Name, Given name, Street, Post code, Email, Date of birth, Nationality, School/employer, Begin/End of stay）—— **不遗漏**
- [ ] 检测出所有 checkbox 组（Sex M/F, Marital Status x5, Permit type x3, Status x4）
- [ ] 检测出"家庭成员"表格的行列结构（5 列 x N 行）
- [ ] 每个检测到的字段都有精确的 fill_rect，rect 在表格单元格边界内
- [ ] 对 3 个不同的测试 PDF 运行检测，人工检查输出的候选列表

**同行参考**：
- Instafill.ai 的 `detect_boxes_fitz()`: 从 PyMuPDF 矢量数据定位表格框、下划线、边框，准确率 95-98%
- pdfplumber: 用 `.lines` + `.rects` + `.chars` 做表格检测，需要自己写网格推断逻辑
- Adobe Acrobat: 找下划线/矩形框 → 转为 text field，相邻文字作为 field name

---

### Phase 2: VLM 接口与语义分析

**目标**：实现 VLM 抽象接口，完成"PDF 图片 + 候选列表 → 确认字段 + 填写内容"的语义分析。

**任务**：
1. 实现 `vlm/base.py`：VLM 抽象基类
   ```python
   class BaseVLMService(ABC):
       async def analyze_form(
           self,
           image: bytes,              # PDF 页面渲染图片
           detected_fields: list,     # Phase 1 的候选列表
           user_info: str,            # 用户输入的信息
       ) -> list[AnalyzedField]:
           """一次调用完成：字段确认 + 分组 + 语义命名 + 内容匹配"""
   ```

2. 实现 `vlm/qwen_vl.py`（通义千问 VL）和 `vlm/openai_vl.py`（GPT-4o）：
   - 使用 OpenAI 兼容模式调用
   - PDF 页面渲染为图片（pymupdf `page.get_pixmap()`）
   - 图片分辨率控制：宽度 1024-1536px（平衡精度和 token）

3. 实现 `native/vlm_analyzer.py`：
   - 构造 prompt：将 Phase 1 的候选列表 + PDF 图片 + 用户信息一起发给 VLM
   - 解析 VLM 返回的 JSON
   - 错误处理：VLM 超时、返回格式异常、JSON 解析失败

4. Prompt 设计（核心）：
   ```
   你是一个 PDF 表单分析助手。

   我已经用程序从 PDF 中检测出以下候选字段：
   {detected_fields_json}

   用户需要填写的信息：
   {user_info}

   请完成以下任务：
   1. 确认每个候选字段是否确实需要填写（过滤误检）
   2. 为每个字段给出语义名称
   3. 将用户信息匹配到对应字段
   4. 对于 checkbox 类型，指出应该勾选哪个选项
   5. 对于无法匹配的字段，fill_value 设为空字符串

   输出 JSON 格式：
   [
     {
       "field_index": 0,
       "semantic_name": "applicant_name",
       "confirmed": true,
       "fill_value": "Wang",
       "field_type": "text"
     },
     ...
   ]
   ```

5. 配置管理：在 `config.py` 中新增 VLM 配置项
   ```
   VLM_PROVIDER=qwen-vl          # 或 openai
   VLM_API_KEY=xxx
   VLM_MODEL=qwen-vl-max         # 或 gpt-4o
   VLM_BASE_URL=xxx
   VLM_MAX_IMAGE_WIDTH=1536      # 图片最大宽度
   ```

**验证标准**：
- [ ] VLM 接口可通过配置切换 Qwen-VL / GPT-4o，无需改代码
- [ ] 对 Native.pdf + 用户信息 "My name is Wang Youliang, born on March 15, 1995, Chinese nationality, male, single, student"，VLM 正确匹配所有对应字段
- [ ] VLM 正确判断 checkbox 选择（Sex: M, Marital Status: single, Status: student）
- [ ] VLM 正确过滤不需要填写的区域（如表头、说明文字区）
- [ ] 单次 VLM 调用延迟 < 15 秒
- [ ] 对 3 个不同测试 PDF 验证匹配准确率 ≥ 90%

**同行参考**：
- Instafill.ai: 用 GPT 做语义分组，将表单解析为逻辑区块（个人信息、家庭成员等），然后并行填写各区块
- LayoutLMv3: 用关系抽取模型预测 label→value 配对，需要 FUNSD 数据集微调
- PaddleOCR PP-Structure: SER（语义实体识别）+ RE（关系抽取）两步完成

---

### Phase 3: PDF 写入与完整 Pipeline

**目标**：将 VLM 分析结果写入 PDF，生成填好的文件。打通 "上传 → 检测 → 分析 → 写入 → 下载" 全流程。

**任务**：
1. 实现 `native/writer.py`：
   - `write_text_field()`: 用 `page.add_freetext_annot()` 在指定 rect 写入文字
   - `write_checkbox()`: 在 checkbox 位置写入 "✓" 或 "X"
   - `adjust_font_size()`: 文字溢出检测 + 字号自动缩小
   - `match_font_style()`: 从相邻 text span 读取字体/字号/颜色，保持视觉一致
   - `write_all()`: 批量写入所有字段

2. 实现 `native/pipeline.py`：
   - 整合 detector → vlm_analyzer → writer 三步
   - 多页处理：逐页检测 + 分析 + 写入
   - 错误处理与日志记录

3. 对接路由：
   - 修改 `routers/pdf.py` 中的 `/fill` 端点
   - native PDF 分流到 `native.pipeline.fill_native_pdf()`

4. 处理边界情况：
   - 文字溢出：计算文字像素宽度 vs rect 宽度，超出则逐步缩小字号（最小 6pt）
   - 空字段：VLM 返回空 fill_value 的字段，不写入
   - 多页表单：逐页独立处理

**验证标准**：
- [ ] Native.pdf + 用户信息 → 生成 filled PDF，用 PDF 阅读器打开确认：
  - 所有文本字段填写在正确位置，文字不超出单元格
  - Checkbox 正确勾选
  - 字体大小和颜色与原表单协调
- [ ] 完整流程（上传 → 下载）延迟 < 30 秒
- [ ] 对 3 个测试 PDF 运行全流程，人工检查结果：
  - 字段识别率 ≥ 95%
  - 填写准确率 ≥ 90%
  - 无明显视觉问题（文字溢出、位置偏移等）

**同行参考**：
- Instafill.ai: 写入后做 overflow detection，检测填入文字的像素宽度是否超出字段边界，超出则用 AI 重新格式化/缩短文本
- pymupdf `add_freetext_annot()`: 支持 fontname、fontsize、text_color、border_color 等参数，可精确控制外观
- 浏览器填写 PDF: 创建 `/Subtype /FreeText` + `/IT /FreeTextTypewriter` 注释对象

---

### Phase 4: 前端对接与用户体验

**目标**：前端无缝支持 Native PDF，用户体验和 v1 一致。

**任务**：
1. 前端改动（最小化）：
   - `api.ts`: 无需改动（API 接口不变）
   - `useSmartFill.ts`: 无需改动（流程不变：上传 → 输入 → 填写 → 下载）
   - `App.tsx`: 可选——上传后显示 PDF 类型提示（"检测到 Native PDF，将使用 AI 布局分析"）

2. 错误提示优化：
   - Native PDF 处理失败时，给出有意义的错误信息（如 "AI 无法识别此表单的布局"）
   - 区分 "字段检测失败" vs "VLM 调用失败" vs "写入失败"

3. 端到端测试：
   - 从前端完整走一遍 Native PDF 流程
   - 移动端验证

**验证标准**：
- [ ] 前端上传 Native.pdf → 输入信息 → 点击填写 → 成功下载填好的 PDF
- [ ] 前端上传 Fillable.pdf → 走 v1 流程 → 结果不变（回归测试）
- [ ] 错误场景：VLM 超时 → 前端显示友好提示
- [ ] 移动端流程正常

---

### Phase 5 (v2.1): 预览与手动编辑

**目标**：实现 "AI 填完 → 用户预览 → 点击修改字段 → 确认下载" 的完整交互闭环。

**任务**：
1. PDF 预览（pdf.js）：
   - 集成 pdf.js 渲染 PDF 到 Canvas
   - 在 AI 填写后，前端展示填好的 PDF 预览
   - 支持多页导航和缩放

2. 字段编辑叠加层：
   - AI 填写结果不直接写入 PDF，而是先返回字段列表 + rect + 值
   - 前端在 pdf.js 渲染的 Canvas 上叠加可编辑的文字框
   - 用户可点击任意已填写字段，修改内容
   - 用户可拖动/调整字段位置和大小（可选）

3. 确认与生成：
   - 用户确认后，前端将最终的字段值 + rect 发给后端
   - 后端写入 PDF 并返回下载

4. API 扩展：
   - `POST /analyze`: 返回检测+匹配结果（不写入 PDF），供前端预览
   - `POST /generate`: 接收最终确认的字段列表，生成 PDF

**验证标准**：
- [ ] PDF 预览清晰，和 PDF 阅读器效果一致
- [ ] 用户可点击已填写字段，弹出编辑框修改内容
- [ ] 修改后确认下载，下载的 PDF 反映修改内容
- [ ] 移动端可用（触摸操作、字段点击区域足够大）

**同行参考**：
- pdf.js: Mozilla 开源 PDF 渲染器，支持 annotation 层覆盖
- DocuSign: 预览 + 点击签名/填写的交互模式
- Instafill.ai: 返回填写结果 JSON + 预览图，用户确认后才生成最终 PDF

---

## 5. 依赖与工具

### 5.1 新增 Python 依赖

| 包 | 版本 | 用途 |
|---|------|------|
| pymupdf | ≥ 1.24.0 | Native PDF 文字/图形提取、FreeText 写入、页面渲染 |
| openai | ≥ 1.10.0 | VLM API 调用（已有，复用） |

### 5.2 新增前端依赖（v2.1）

| 包 | 用途 |
|---|------|
| pdfjs-dist | PDF 页面渲染预览 |

### 5.3 测试资源

需要收集 3-5 个英语 Native PDF 政府/保险表单用于测试：
- TestSpace/Native.pdf（已有，瑞士保险表单）
- 需补充 2-3 个不同布局的表单

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| VLM 视觉理解不够准确 | 字段分组或匹配出错 | 程序化检测做保底，VLM 只做确认；可切换更强的模型 |
| 表格结构多样性大 | 检测规则无法覆盖所有布局 | 先聚焦"有清晰表格线"的表单，逐步扩展 |
| 文字渲染坐标偏差 | 填入的文字位置不准 | 用 pymupdf 原生坐标（PDF pt 单位），不做坐标转换 |
| VLM API 延迟高 | 用户体验差 | 控制图片分辨率；考虑缓存相同表单模板的分析结果 |
| Checkbox 样式多变 | 勾选标记和原表单风格不一致 | 提供多种标记样式（✓、X、●），根据表单风格选择 |
