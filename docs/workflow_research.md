# Native PDF 智能填写 — 技术调研报告

> 调研时间：2026-03-16
> 调研目标：梳理业内同行在 Native PDF 表单填写上的技术方案，为 SmartFill v2 提供参考
> 关联文档：[devplan_v2.md](devplan_v2.md)

---

## 目录

1. [核心问题定义](#1-核心问题定义)
2. [业内产品与开源项目全景](#2-业内产品与开源项目全景)
3. [Instafill.ai 深度分析](#3-instafillai-深度分析)
4. [CommonForms / FFDNet 深度分析](#4-commonforms--ffdnet-深度分析)
5. [其他开源项目](#5-其他开源项目)
6. [技术难点逐项分析](#6-技术难点逐项分析)
7. [推荐 Workflow 设计](#7-推荐-workflow-设计)
8. [参考资料](#8-参考资料)

---

## 1. 核心问题定义

Native PDF 表单填写可以分解为以下子问题：

```
输入: 一个 Native PDF（无 AcroForm 字段，只有静态文字和矢量线条）
      + 用户提供的个人信息

输出: 一个填好的 PDF（在正确位置写入正确内容）

子问题:
  P1: 字段检测 — 哪些位置需要被填写？（位置 + 类型）
  P2: 语义理解 — 每个字段的含义是什么？属于哪个分组？
  P3: 内容匹配 — 用户信息映射到哪个字段？
  P4: 坐标精度 — 填写区域的 bbox 大小和位置如何精确确定？
  P5: 视觉一致 — 填入文字的字体/字号/颜色如何与原表单协调？
  P6: 写入执行 — 如何将文字写入 PDF 的指定位置？
```

**核心认知：P1（字段检测）和 P4（坐标精度）是程序化问题，不应依赖 AI；P2（语义理解）和 P3（内容匹配）是 AI 擅长的问题。**

---

## 2. 业内产品与开源项目全景

| 项目 | 类型 | 字段检测方案 | 语义理解方案 | 坐标精度 | 是否开源 |
|------|------|-------------|-------------|---------|---------|
| **Instafill.ai** | 商业产品 | PyMuPDF 矢量检测 + pdfplumber 空白检测 | GPT 语义匹配 | 高（PDF 原生） | 否 |
| **CommonForms/FFDNet** | 学术+开源 | YOLO11 目标检测 | 无（仅检测） | 中（像素级） | **是** |
| **FormFill** | 开源工具 | Claude Vision 直接识别 | Claude Vision | 低（VLM 估算） | 是 |
| **Adobe Acrobat** | 商业产品 | 矢量分析 + 启发式规则 | 无 | 高 | 否 |
| **Apryse IDP** | 商业 SDK | AI 目标检测（本地模型） | Key-Value 关系抽取 | 高 | 否 |
| **LayoutLMv3** | 学术模型 | OCR + Transformer | 关系抽取（需微调） | 中 | 是（模型） |
| **PaddleOCR PP-Structure** | 开源框架 | OCR + SER | RE（关系抽取） | 中 | 是 |
| **Datalab/Marker** | 开源工具 | PDF 解析 | 语义字段匹配 | 高 | 是 |
| **ai-pdf-autofiller** | 开源工具 | 确定性规则 + LLM 回退 | LLM 回退 | 依赖原始字段 | 是 |

---

## 3. Instafill.ai 深度分析

Instafill.ai 是目前市场上最完整的 AI PDF 表单填写商业产品。虽然核心代码不开源，但通过其技术博客可以还原出完整的技术架构。

### 3.1 技术栈

| 组件 | 技术选型 |
|------|---------|
| 后端语言 | Python + C#(.NET) |
| AI 框架 | LangChain + OpenAI |
| AI 模型 | GPT-5 系列（2026.02 升级） |
| 数据库 | MongoDB（schema-less 存储表单数据） |
| 缓存 | Redis（提升响应速度） |
| 部署 | Microsoft Azure + Google App Engine |
| 日志 | Logstash |

### 3.2 字段检测：三引擎串行方案

Instafill 使用**多引擎串行检测**，不依赖 AI 做字段定位：

#### 引擎 1：`detect_boxes_fitz()` — 主引擎

- **底层库**：PyMuPDF (fitz)
- **原理**：解析 PDF 的矢量流（vector stream），不是像素/图像数据
- **检测对象**：
  - 表格单元格边框（矩形路径）
  - 水平下划线（线段路径）
  - 彩色边框框（如红色/蓝色边框的输入框）
- **适用场景**：数字化创建的 PDF（Word/InDesign 导出），矢量几何信息完整
- **准确率**：95-98%

#### 引擎 2：`detect_blanks()` — 回退引擎

- **底层库**：pdfplumber
- **触发条件**：当主引擎返回的字段数少于预期时启用
- **原理**：分析文本层，定位**连续空白区间**（两段文字之间的空白带）
- **适用场景**：扫描件或纯图像 PDF，无矢量几何
- **准确率**：90-95%（300 DPI）

#### 引擎 3：`_find_checkboxes()` — Checkbox 专用

- **底层库**：pdfplumber
- **检测规则**：
  - 查找小正方形区域（标准政府表单通常 8-14pt）
  - 检查相邻文本确定分组
  - 共享题干 + 互斥选项 → RadioButton 组
  - 独立方框 → CheckBox 控件

#### 引擎 4：`synthesize_fields_from_table_cells()`

- 识别表格的行列网格
- 每个单元格生成一个字段矩形

### 3.3 8 步几何修正流水线

Instafill 在字段检测后，会经过一个 **8 步几何修正流水线**（8-step normalization pipeline），对原始检测到的矩形进行精细调整。官方描述为：

> "synthesizes, carves, adjusts, nudges, truncates, and offsets raw field rectangles before writing AcroForm widgets"

具体操作包括：
1. **synthesize** — 合成：将相邻的小矩形合并为完整字段
2. **carve** — 切割：将跨列的大矩形拆分为独立字段
3. **adjust** — 调整：对齐到网格线，消除微小偏移
4. **nudge** — 微调：确保文字不贴边，内边距合理
5. **truncate** — 截断：去除超出页面边界的部分
6. **offset** — 偏移：补偿 PDF 坐标系原点差异
7. 去重 — 移除重叠字段
8. 排序 — 按阅读顺序排列

### 3.4 LLM 误检过滤：`get_nonsense_fields_from_page()`

- 将页面渲染为图片，发送给 LLM
- LLM 识别并标记错误放置在以下区域的字段：
  - Logo / 装饰性边框
  - 页眉/页脚/说明文字区域
  - 已有内容的区域
- 通常每个复杂多页表单移除 **2-8 个**误检字段
- 处理后通常剩余 **<5 个**需要手动调整的字段

### 3.5 表单填写流水线（6 阶段）

```
1. 初始化会话
2. 获取表单字段清单
3. 填写字段 — autofill_db_fields()
   ├── 按独立分组拆分
   ├── 并行调度（最多 40 个并行填写任务）
   └── 每组独立调用 LLM
4. 生成填好的 PDF
5. 计算用量成本
6. 保存并发送事件
```

**关键设计：并行填写。** 40 个并行任务意味着 LLM 只需处理每个字段组（而不是整个表单），极大降低延迟。

### 3.6 文字适配（Text Fitting）

```
for each filled_field:
    rendered_width = measure_text_width(text, font, font_size)
    if rendered_width > field_width:
        # 方案 1: 缩小字号
        while rendered_width > field_width and font_size > min_size:
            font_size -= 0.5
            rendered_width = measure_text_width(text, font, font_size)

        # 方案 2: 如果字号已经最小，让 AI 重新格式化/缩短文本
        if rendered_width > field_width:
            text = ai_reformat(text, max_chars=estimate_max_chars(field_width, font_size))
```

### 3.7 性能基准

| 表单类型 | 页数 | 处理时间 |
|---------|------|---------|
| CMS-1500（医疗） | 2 页 | 15-30 秒 |
| I-485（移民） | 10 页 | 1-3 分钟 |
| 1003/SF-86（安全审查） | 30 页 | 4-8 分钟 |

### 3.8 Instafill 对 SmartFill 的启示

| Instafill 做法 | SmartFill 的对应策略 |
|---------------|-------------------|
| PyMuPDF 矢量检测做主引擎 | 我们的 `detector.py` 对应，方向一致 |
| pdfplumber 做回退引擎 | 可选：暂不实现，先用 VLM 补充 |
| 8 步几何修正 | **需要实现**：至少做 nudge（内边距）、truncate（边界裁剪）、去重 |
| LLM 过滤误检 | 我们的 VLM 阶段 C 对应 |
| 40 并行填写 | 阶段 D 可并行，但初期先串行 |
| AI 重新格式化溢出文本 | 先做字号缩小，AI 格式化作为 v2.1 功能 |

---

## 4. CommonForms / FFDNet 深度分析

CommonForms 是一个专门针对 PDF 表单字段检测的学术项目，提供了目前最大的公开数据集和预训练模型。

### 4.1 基本信息

| 项目 | 信息 |
|------|------|
| 论文 | arXiv:2509.16506 |
| GitHub | [github.com/jbarrow/commonforms](https://github.com/jbarrow/commonforms) |
| HuggingFace 模型 | `jbarrow/FFDNet-L`, `jbarrow/FFDNet-S`, `jbarrow/FFDNet-L-cpu` |
| HuggingFace 数据集 | `jbarrow/CommonForms` |
| pip 安装 | `pip install commonforms` |
| 浏览器 Demo | [commonforms.simplepdf.com](https://commonforms.simplepdf.com/) |

### 4.2 技术方案

- **模型架构**：YOLO11 目标检测
- **输入**：PDF 页面渲染图片（1216px 高分辨率）
- **输出**：字段 bounding box + 类型 + 置信度
- **3 种字段类型**：
  - TextBox（文本输入框）
  - ChoiceButton（checkbox / radio button）
  - Signature（签名区域）

### 4.3 数据集

- **规模**：55,000 文档，450,000+ 页
- **来源**：从 800 万 Common Crawl PDF 中筛选
- **多语言**：1/3 非英语文档
- **标注**：自动标注 + 人工验证

### 4.4 性能指标

| 模型 | 参数量 | 推理速度（3090Ti） | 训练时间 | 训练成本 | mAP |
|------|--------|-------------------|---------|---------|-----|
| FFDNet-L | 25M | ~16ms/页 | ~5 天 | ~$500 | >80 |
| FFDNet-S | — | ~5ms/页 | ~2 天 | — | 略低 |

**关键发现**：高分辨率输入至关重要——不同分辨率之间 mAP 差距可达 20 个点。

### 4.5 与我们方案的关系

CommonForms/FFDNet 可以作为 SmartFill 的**可选加速阶段**：

```
优势：
- 极快（16ms/页 vs VLM 的 5-15 秒/页）
- 0 token 成本
- 专门训练过各种表单布局，泛化能力强
- 支持浏览器端推理（ONNX Runtime）

劣势：
- 输出是像素级 bbox，需要映射回 PDF 坐标系（有精度损失）
- 只检测字段位置和类型，不做语义理解
- 25M 参数模型需要部署/加载

适用场景：
- 作为规则检测器的补充，交叉验证检测结果
- 快速预检：先用 FFDNet 粗检，再用 pymupdf 精确定位
- 处理规则覆盖不到的非标准布局
```

### 4.6 坐标映射问题

FFDNet 输出的是**像素坐标**（基于 1216px 高的渲染图），需要转换为 PDF 坐标（72dpi, pt 单位）：

```python
# 像素坐标 → PDF 坐标
scale = page.rect.height / image_height  # e.g., 792 / 1216 ≈ 0.651
pdf_x0 = pixel_x0 * scale
pdf_y0 = pixel_y0 * scale
pdf_x1 = pixel_x1 * scale
pdf_y1 = pixel_y1 * scale
```

这个映射会引入约 1-3pt 的误差（约 0.3-1mm），对于有表格线的表单可能导致文字轻微偏移。**因此，FFDNet 检测结果需要与 pymupdf 的矢量数据做 snap-to-grid 校正。**

---

## 5. 其他开源项目

### 5.1 FormFill — VLM 直接填写方案

- **GitHub**：[github.com/wdhorton/formfill](https://github.com/wdhorton/formfill)
- **原理**：将 PDF 页面当作"屏幕"，用 Claude Vision API 分析截图，输出 `move_mouse` / `click` / `type` 操作序列
- **写入**：用 Pillow 在图片上画文字（不是写入 PDF）
- **CLI**：`formfill path/to/form.pdf -s "Name: John Smith, Age: 30"`

**评价**：概念最简单，但精度最差。VLM 给出的像素坐标不够精确，且输出是图片而非 PDF。不适合生产用途，但验证了 VLM 理解表单布局的可行性。

### 5.2 Digital-Form-with-GPT4-Vision-API

- **GitHub**：[github.com/nathanfhh/Digital-Form-with-GPT4-Vision-API](https://github.com/nathanfhh/Digital-Form-with-GPT4-Vision-API)
- **原理**：PDF 页面 → JPG → GPT-4 Vision → 生成 YAML 格式的表单 UI 描述
- **用途**：生成可交互的前端表单 UI，而非直接填写 PDF
- **通信**：Socket.IO 流式传输

**评价**：思路不同——不填 PDF，而是从 PDF 生成 Web 表单。可以参考其 prompt 设计。

### 5.3 ai-pdf-autofiller

- **GitHub**：[github.com/lindseystead/ai-pdf-autofiller](https://github.com/lindseystead/ai-pdf-autofiller)
- **架构**：FastAPI + `doc_engine` 核心
- **原理**：确定性优先的字段映射（key normalization、别名匹配、类型强制转换），LLM 仅作为高价值未匹配字段的回退
- **评价**：面向 AcroForm PDF，不处理 Native PDF。但其"确定性优先 + LLM 回退"的设计哲学值得借鉴。

### 5.4 Datalab / Marker

- **GitHub**：[github.com/datalab-to/marker](https://github.com/datalab-to/marker)
- **原理**：PDF → Markdown + JSON 转换，表单填写功能使用语义字段匹配
- **底层**：Marker + Surya（OCR）+ Chandra
- **评价**：主要做 PDF 内容提取，表单填写是附加功能。

### 5.5 Apryse Smart Data Extraction（商业，但有详细文档）

- **类型**：商业 SDK，本地部署（非云端）
- **输出格式**：`{type, confidence, rect: [x1, y1, x2, y2]}` per field
- **两个引擎**：
  - Form Field Detection：检测字段位置和类型
  - Form Field Key-Value Extraction：匹配每个字段与对应的 label 和值
- **评价**：效果好但闭源付费。其输出格式可以参考。

### 5.6 LayoutLM 系列

- **模型**：LayoutLM → LayoutLMv2 → LayoutLMv3 → LayoutXLM
- **原理**：Transformer 模型，融合**文本内容 + 布局坐标 + 图像像素**三模态
- **流程**：OCR 提取文字片段 + 坐标 → LayoutLM 分类/关系抽取
- **数据集**：FUNSD（表单理解）、CORD（收据）、SROIE（发票）
- **评价**：需要微调，训练成本较高。适合大规模生产环境，不适合我们当前阶段。

### 5.7 PaddleOCR PP-Structure

- **原理**：两步方案
  - SER（Semantic Entity Recognition）：识别每个文字区域的语义角色（header/question/answer）
  - RE（Relation Extraction）：预测 label → value 的配对关系
- **评价**：面向 OCR 场景（扫描件），不适合 Native PDF（已有精确文字坐标）。

---

## 6. 技术难点逐项分析

### 6.1 如何精确确定填写区域的 bbox？

这是整个项目最核心的技术问题。根据调研，不同场景需要不同策略：

#### 场景 A：表格单元格内的字段（占 60-70%）

```
┌──────────────┬─────────────────────┐
│ NAME:        │  ← 填写区域         │
├──────────────┼─────────────────────┤
│ ADDRESS:     │  ← 填写区域         │
└──────────────┴─────────────────────┘
```

**bbox 来源**：pymupdf `get_drawings()` 提取的表格线 → 构建网格 → 单元格边界即 bbox

**计算方式**：
```python
# label 在单元格内
fill_rect = (
    label.x1 + padding,      # 从 label 右端开始
    cell.y0 + padding,        # 单元格上边界 + 内边距
    cell.x1 - padding,        # 单元格右边界 - 内边距
    cell.y1 - padding,        # 单元格下边界 - 内边距
)

# label 在左侧单元格，填写区在右侧单元格
fill_rect = (
    right_cell.x0 + padding,
    right_cell.y0 + padding,
    right_cell.x1 - padding,
    right_cell.y1 - padding,
)
```

**精度**：高（PDF 原生坐标，误差 < 0.5pt）

**同行做法**：
- Instafill `detect_boxes_fitz()`：直接从矢量路径获取矩形坐标
- Adobe Acrobat：找矩形框 → 转为 AcroForm text field

#### 场景 B：下划线字段（占 20-30%）

```
Name: ___________________     Date: ____________
```

**bbox 来源**：pymupdf 提取的水平线段（`"l"` 操作或扁矩形 `"re"` 操作）

**计算方式**：
```python
# 下划线给出水平范围和底边位置
line_height = nearby_font_size * 1.2  # 从相邻文字推算行高
fill_rect = (
    max(label.x1 + 2, line.x0),   # 从 label 右端或线段起点
    line.y - line_height,           # 下划线上方一个行高
    line.x1,                        # 线段终点
    line.y,                         # 下划线位置
)
```

**精度**：高（水平范围精确，垂直范围需要推算但误差可控）

**同行做法**：
- Instafill：将下划线转为带底边框的 AcroForm 字段
- pdfplumber：通过 `.lines` 获取线段坐标

#### 场景 C：空白矩形区域（占 ~10%）

```
Comments:
┌─────────────────────────────┐
│                             │
│                             │
└─────────────────────────────┘
```

**bbox 来源**：pymupdf 提取的大矩形绘图路径

**计算方式**：`fill_rect = (rect.x0 + padding, rect.y0 + padding, rect.x1 - padding, rect.y1 - padding)`

**精度**：高

#### 场景 D：无可见边界的字段（最难，占 ~5%）

```
Name                          Date of Birth
John Smith                    01/15/1990
```

没有表格线，没有下划线，只有文字和空白。

**解决方案**：
1. 需要 pdfplumber 的字符级分析，找出文本之间的空白间隔
2. 或者交给 VLM/FFDNet 识别
3. Instafill 的 `detect_blanks()` 就是处理这类场景

**精度**：中（需要启发式规则推算）

**目前策略**：v2.0 暂不处理，聚焦有清晰表格线的表单。

### 6.2 如何让 VLM 高效读取信息？

**问题**：原始 JSON 太大（2.4 万行），不能直接喂给模型。

**解决方案：精简中间表示**

```
原始 JSON（24,550 行）
  ↓ 精简
候选字段摘要（每页 10-30 行）
  ↓ 传给 VLM
VLM 只需确认/过滤/命名
```

传给 VLM 的精简格式：

```json
{
  "page": 9,
  "page_size": [612, 792],
  "fields": [
    {
      "id": 0,
      "label": "NAME OF LESSOR (Please print or type)",
      "type": "text",
      "rect": [267.6, 134.2, 555.4, 164.8],
      "confidence": 0.45
    },
    {
      "id": 1,
      "label": "STREET ADDRESS",
      "type": "text",
      "rect": [74.2, 164.8, 267.6, 195.8],
      "confidence": 0.45
    }
  ]
}
```

**Instafill 的做法**：类似。检测阶段输出 `{page, x0, y0, x1, y1, field_id}` 的精简列表，LLM 只处理这个列表 + 页面截图。

### 6.3 字体大小如何匹配？

**基本策略**：从相邻文字推断

```python
def match_font_style(fill_rect, text_spans):
    """从填写区域附近的文字推断字体参数"""
    nearby = [s for s in text_spans
              if bbox_distance(s["bbox"], fill_rect) < 20]

    if nearby:
        # 取最近的文字的字体信息
        nearest = min(nearby, key=lambda s: bbox_distance(s["bbox"], fill_rect))
        return {
            "font_size": nearest["font_size"],
            "font_name": nearest["font_name"],  # 通常 Helvetica
        }
    else:
        return {"font_size": 10, "font_name": "helv"}  # 安全默认值
```

**Instafill 的做法**：
- 默认 Auto 字号（shrink-to-fit）
- 默认字体 Helvetica
- 写入后检查像素宽度是否超出字段边界
- 超出则缩小字号或让 AI 重新格式化/缩短文本

**PyMuPDF 的支持**：
- `page.add_freetext_annot(rect, text, fontsize=..., fontname=..., text_color=...)` 支持完整的字体参数控制
- `page.insert_htmlbox(rect, html)` 支持 HTML 格式化文本，自动布局

### 6.4 文字溢出如何处理？

```python
def write_with_overflow_check(page, rect, text, font_size, font_name):
    """写入文字，自动处理溢出"""
    min_font_size = 6.0

    while font_size >= min_font_size:
        # 估算文字宽度（近似）
        avg_char_width = font_size * 0.5  # Helvetica 大约是字号的 0.5 倍
        text_width = len(text) * avg_char_width
        rect_width = rect[2] - rect[0]

        if text_width <= rect_width:
            break
        font_size -= 0.5

    # 如果还是溢出，截断并加 "..."
    if text_width > rect_width:
        max_chars = int(rect_width / avg_char_width)
        text = text[:max_chars - 3] + "..."

    page.add_freetext_annot(fitz.Rect(rect), text, fontsize=font_size, fontname=font_name)
```

**更精确的宽度计算**：PyMuPDF 提供 `fitz.get_text_length(text, fontname, fontsize)` 可以精确计算文字渲染宽度。

### 6.5 Checkbox 如何处理？

**检测**：
- 小正方形（6-20pt 边长，宽高差 ≤ 2pt）
- 特殊 Unicode 字符：`☐`(U+2610)、`☑`(U+2611)、`☒`(U+2612)、`□`(U+25A1)
- Wingdings/Symbol 私有区字符：U+F000 ~ U+F0FF

**勾选方式**：
```python
def write_checkbox(page, checkbox_rect, checked):
    if not checked:
        return
    # 在 checkbox 中心写入 ✓ 或 X
    cx = (checkbox_rect[0] + checkbox_rect[2]) / 2
    cy = (checkbox_rect[1] + checkbox_rect[3]) / 2
    size = min(checkbox_rect[2] - checkbox_rect[0], checkbox_rect[3] - checkbox_rect[1])
    font_size = size * 0.8

    # 方案 1: 写入 ✓ 字符
    page.insert_text((cx - font_size * 0.3, cy + font_size * 0.3),
                      "✓", fontsize=font_size)

    # 方案 2: 画 X（两条对角线）
    # page.draw_line(...)
```

**Instafill 的做法**：识别 checkbox 的正方形 → 相邻文本作为选项标签 → LLM 判断应该勾选哪个 → 写入勾选标记。

---

## 7. 推荐 Workflow 设计

基于以上调研，推荐以下 5 阶段 workflow：

```
阶段 A: 程序化检测（< 1 秒，0 token）
├── pymupdf: 提取 text_spans + drawings + 表格结构
├── 规则推断: 表格单元格字段 + 下划线字段 + checkbox
├── 几何修正: 内边距/边界裁剪/去重/排序
└── 输出: candidate_fields（含精确 bbox + 相邻文字的字体信息）

阶段 B（可选）: FFDNet 辅助检测（< 0.5 秒，0 token）
├── 渲染每页为图片 → YOLO 推理
├── 输出: 字段 bbox + 类型
├── 与阶段 A 结果交叉验证
└── 补充阶段 A 遗漏的非标准布局字段

阶段 C: VLM 语义精炼（1 次调用/页，~5 秒）
├── 输入: PDF 页面截图 + 阶段 A 的精简字段列表
│   （只传 id + label + type + rect + confidence，不传原始 JSON）
├── 任务:
│   1. 确认每个候选字段是否真的需要填写（过滤误检）
│   2. 给出语义名称（如 "applicant_name"）
│   3. 对 checkbox 组标注正确的题干文本
│   4. 补充阶段 A 遗漏的字段（如果有）
└── 输出: confirmed_fields（含语义名称 + 是否需要填写）

阶段 D: LLM 内容填写（可并行，~3 秒）
├── 输入: confirmed_fields + 用户信息 + memory
├── 按独立分组并行调用 LLM
│   （个人信息组、地址组、家庭成员组…各组独立）
├── 不需要 VLM（纯文本匹配任务）
└── 输出: field_values

阶段 E: 写入 PDF（< 1 秒）
├── pymupdf add_freetext_annot / insert_text
├── 字体匹配: 从阶段 A 获取的相邻 span 字体信息
├── 溢出检测: 文字宽度 > rect 宽度 → 缩小字号（最小 6pt）
└── Checkbox: 写入 ✓ 或 X
```

### 为什么 bbox 不该依赖 VLM？

| 对比维度 | 程序检测（pymupdf） | VLM 估算 |
|---------|-------------------|---------|
| 坐标精度 | ±0.01pt（PDF 原生精度） | ±3-10pt（像素估算） |
| 速度 | < 1 秒/文档 | 5-15 秒/页 |
| Token 成本 | 0 | 1000-3000 tokens/页 |
| 可靠性 | 确定性（同一 PDF 永远同一结果） | 概率性（可能每次不同） |

**结论**：bbox 必须来自程序化检测，VLM 只做语义理解。这也是 Instafill 验证过的方案。

### 与 Instafill 方案的对比

| 维度 | Instafill | SmartFill v2 |
|------|-----------|-------------|
| 字段检测 | pymupdf + pdfplumber（双引擎） | pymupdf 规则检测 + VLM 补充 |
| 几何修正 | 8 步修正流水线 | 需实现核心步骤（nudge/truncate/dedup） |
| 误检过滤 | LLM 看截图删误检 | VLM 阶段 C 统一处理 |
| 语义理解 | LLM 分组 | VLM 看截图 + 候选列表 |
| 填写执行 | 40 并行 LLM 调用 | 可并行（初期先串行） |
| 文字适配 | 缩字号 + AI 重格式化 | 缩字号（v2.0），AI 格式化（v2.1） |
| 用户体验 | 预览 + 确认 | v2.0 直接下载，v2.1 加预览编辑 |

---

## 8. 参考资料

### 技术博客

1. [How to Automate Filling PDF Forms Using AI](https://dev.to/instafill/how-to-automate-filling-pdf-forms-using-ai-1md9) — Instafill, DEV Community
2. [Instafill.ai PDF Filler Tech Stack](https://dev.to/instafill/instafillai-pdf-filler-tech-stack-20hc) — DEV Community
3. [Instafill.ai Core Technology Update (Feb 2026)](https://blog.instafill.ai/2026/02/25/instafill-ai-core-technology-update-what-changed-since-august-2025/)
4. [Accuracy Improvements (Mar 2026)](https://blog.instafill.ai/2026/03/06/ai-pdf-form-filling-accuracy-improvements/)
5. [How Instafill.ai Works (Jun 2025)](https://blog.instafill.ai/2025/06/25/how-instafill-ai-works/)
6. [Flat-to-Fillable PDF Conversion](https://instafill.ai/features/flat-to-fillable-conversion) — Feature Page
7. [Technical Challenges in AI Form Filling](https://resources.instafill.ai/blog/technical-challenges-in-ai-form-filling)

### 论文与学术资源

8. [CommonForms: Filling Form Fields Automatically (arXiv:2509.16506)](https://arxiv.org/abs/2509.16506)
9. [LayoutLMv3: Pre-training for Document AI with Unified Text and Image Masking](https://arxiv.org/abs/2204.08387)
10. [PP-StructureV2: A Stronger Document Analysis System](https://arxiv.org/abs/2210.05391)

### 开源项目

11. [CommonForms GitHub](https://github.com/jbarrow/commonforms) — YOLO11 字段检测
12. [FormFill GitHub](https://github.com/wdhorton/formfill) — Claude Vision 填写
13. [Digital-Form-with-GPT4-Vision-API](https://github.com/nathanfhh/Digital-Form-with-GPT4-Vision-API)
14. [ai-pdf-autofiller](https://github.com/lindseystead/ai-pdf-autofiller)
15. [Datalab Marker](https://github.com/datalab-to/marker)
16. [GSA/pdf-filler](https://github.com/GSA/pdf-filler)

### PyMuPDF 技术资料

17. [Extracting and Creating Vector Graphics in PDF](https://medium.com/@pymupdf/extracting-and-creating-vector-graphics-in-a-pdf-using-python-4c38820e2da8)
18. [Mastering PDF Text with insert_htmlbox](https://artifex.com/blog/mastering-pdf-text-with-pymupdfs-insert-htmlbox-what-you-need-to-know)
19. [PyMuPDF page.get_drawings() 文档](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_drawings)

### 社区讨论

20. [Show HN: CommonForms](https://news.ycombinator.com/item?id=45450135)
21. [HuggingFace: Model for PDF fillable fields + coordinates](https://discuss.huggingface.co/t/any-model-that-takes-in-a-clean-pdf-and-outputs-a-json-of-all-the-fillable-fields-that-should-be-added-to-it-coordinates/147198)
22. [OpenAI Community: Using GPT-4-Turbo to fill out complex PDF forms](https://community.openai.com/t/using-gpt-4-turbo-to-fill-out-complex-pdf-forms/722020)
23. [Automating PDF Form Filling with AI — Medium](https://medium.com/@jensenloke/automating-pdf-form-filling-with-ai-a-technical-journey-a916642162c2)

### 商业产品文档

24. [Apryse: Auto-detect PDF Form Fields with IDP](https://apryse.com/blog/auto-detect-pdf-form-fields-with-idp)
25. [Apryse: Smart Data Extraction](https://apryse.com/blog/auto-detect-pdf-form-fields-with-smart-data-extraction)
26. [Automatically Fill PDF Forms with AI — Datalab](https://www.datalab.to/blog/automatically-fill-pdf-forms-with-ai)
