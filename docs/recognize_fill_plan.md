# Recognize + Fill 实现计划

> 文档定位：Recognize（VLM 识别分组）+ Fill（LLM 填写）+ Writer（PDF 写入）三个模块的详细实现计划。
> 前置依赖：Preprocess 模块已完成（`backend/app/services/native/preprocess/`）。
> 创建时间：2026-03-22
> 状态：待实现

---

## 1. 整体架构

### 1.1 数据流

```
Preprocess (已完成)         Recognize (VLM)              Match                Fill (LLM)            Writer
─────────────────      ──────────────────      ──────────────────      ──────────────────      ──────────
detect_all()       →   per-page VLM call   →   VLM output ∩           per-page LLM call  →   pymupdf
{pages: [{             输入: 页面截图            preprocess fields      输入: matched         add_freetext
  detected_fields,     输出: 分组 + labels       ↓                      groups + user         _annot()
  text_spans,          + types + options        matched_fields          memory
  table_structures                              (有精确 fill_rect)      输出: field values
}]}
```

### 1.2 核心设计原则

- **Preprocess 负责坐标精度**：fill_rect 全部来自 preprocess，不依赖 VLM
- **VLM 负责语义理解**：纯看截图，输出分组后的 label 列表（含 checkbox options）
- **取交集**：VLM 输出 ∩ preprocess 输出，只填写两者都认可的字段
- **LLM 负责内容匹配**：纯文本任务，根据 user memory 生成填写值
- **每页独立处理**：不跨页分组，每页一次 VLM + 一次 LLM

### 1.3 代码组织

```
backend/app/services/native/
├── preprocess/          # 已完成 — 程序化字段检测
│   ├── detector.py
│   ├── label_first.py
│   ├── extraction.py
│   ├── legacy.py
│   ├── utils.py
│   └── types.py
├── recognize.py         # 新增 — VLM 识别 + 匹配
├── fill.py              # 新增 — LLM 填写
├── writer.py            # 新增 — PDF 写入
└── pipeline.py          # 已有 — 扩展为完整流程

TestSpace/
├── recognize_fill_test/ # 新增 — Recognize + Fill 测试
│   ├── common.py        # 共享常量、工具函数
│   ├── test_recognize.py    # VLM 识别测试
│   ├── test_match.py        # 匹配逻辑测试（不需要 API）
│   ├── test_fill.py         # LLM 填写测试
│   ├── test_writer.py       # PDF 写入测试
│   ├── test_e2e.py          # 端到端测试
│   └── user_memory.md       # 测试用 user memory
```

---

## 2. Recognize 模块 (`recognize.py`)

### 2.1 职责

1. 将 PDF 页面渲染为截图
2. 调用 VLM（每页一次），纯看截图，输出分好组的字段列表
3. 将 VLM 输出与 preprocess 的 detected_fields 做文本匹配（取交集）
4. 输出 matched_fields：每个字段有 VLM 提供的语义信息 + preprocess 提供的精确 fill_rect

### 2.2 VLM 输入

**只有页面截图**，不传 preprocess 的字段列表。

截图生成方式：
```python
import fitz

def render_page_image(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """渲染 PDF 页面为 PNG 图片"""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]  # 0-indexed
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes
```

DPI 选择：150 DPI 平衡清晰度与 token 成本（一页约 1200x1600px）。

### 2.3 VLM 输出格式

```json
{
  "groups": [
    {
      "group_name": "applicant_info",
      "group_description": "Applicant personal information",
      "fields": [
        {"label": "Name of Applicant", "type": "text"},
        {"label": "Street Address", "type": "text"},
        {"label": "Date of Birth", "type": "text"},
        {"label": "Gender", "type": "checkbox", "options": ["Male", "Female", "Other"]}
      ]
    },
    {
      "group_name": "eligibility",
      "group_description": "Eligibility questions",
      "fields": [
        {"label": "Are you a U.S. citizen?", "type": "checkbox", "options": ["Yes", "No"]},
        {"label": "Have you been convicted of a felony?", "type": "checkbox", "options": ["Yes", "No"]}
      ]
    },
    {
      "group_name": "signature",
      "group_description": "Signature and date",
      "fields": [
        {"label": "Signature", "type": "text"},
        {"label": "Date", "type": "text"}
      ]
    }
  ]
}
```

字段类型规则：
- `"text"` — 需要填写文本的字段（包括姓名、地址、日期等）
- `"checkbox"` — 勾选框，必须带 `options` 列表

### 2.4 VLM Prompt

```
You are a form field analyzer. You are given a screenshot of one page from a PDF form.

Your task:
1. Identify ALL fields on this page that need to be filled in by a user
2. Group related fields together (e.g., all personal info fields in one group, all address fields in one group)
3. For each field, provide:
   - "label": the complete label text as shown on the form (e.g., "Name of Applicant (Last, First, Middle)")
   - "type": either "text" (for text input fields) or "checkbox" (for checkbox/radio button selections)
   - "options": (only for checkbox type) list all available options exactly as shown on the form

Rules:
- Only include fields that a user needs to fill in. Do NOT include:
  - Section headers, titles, or instructions
  - Pre-printed text that is not a field label
  - Page numbers, form numbers, or reference codes
- For checkbox fields, the "label" should be the question or prompt, and "options" should list all choices
- Use the EXACT text as printed on the form for labels and options — do not paraphrase
- Each field should appear in exactly one group
- Group name should be a short snake_case identifier

Output ONLY valid JSON in this exact format:
{
  "groups": [
    {
      "group_name": "string",
      "group_description": "string",
      "fields": [
        {"label": "string", "type": "text"},
        {"label": "string", "type": "checkbox", "options": ["string", ...]}
      ]
    }
  ]
}
```

### 2.5 VLM 调用实现

```python
import base64
from openai import OpenAI

def call_vlm(img_bytes: bytes, prompt: str, settings) -> dict:
    """调用 VLM API（OpenAI 兼容模式）"""
    client = OpenAI(
        api_key=settings.resolved_vlm_api_key,
        base_url=settings.resolved_vlm_base_url,
    )
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model=settings.resolved_vlm_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}"
                        },
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)
```

VLM 模型配置：需要在 `.env` 中配置支持视觉的模型：
```
VLM_API_KEY=sk-xxx
VLM_MODEL=qwen-vl-max
VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 2.6 匹配算法

VLM 输出的 label 文本需要与 preprocess 的 detected_fields 做匹配，获取精确的 fill_rect。

**匹配策略（按优先级）**：

1. **精确匹配**：VLM label == preprocess label（忽略大小写、首尾空格）
2. **包含匹配**：VLM label 包含 preprocess label，或反过来
3. **模糊匹配**：编辑距离 / token 重叠率超过阈值

```python
from difflib import SequenceMatcher

def match_fields(
    vlm_groups: list[dict],
    preprocess_fields: list[dict],
) -> list[dict]:
    """
    将 VLM 输出的字段与 preprocess 的 detected_fields 匹配。
    返回 matched_groups：每个 group 中的 field 带有 fill_rect。
    """
    matched_groups = []

    # 分离 preprocess 的 text 字段和 checkbox 字段
    pp_text_fields = [f for f in preprocess_fields if f.get("field_type") != "checkbox"]
    pp_checkbox_fields = [f for f in preprocess_fields if f.get("field_type") == "checkbox"]

    # 记录已使用的 preprocess 字段（避免重复匹配）
    used_pp_ids = set()

    for group in vlm_groups:
        matched_fields = []
        for vlm_field in group["fields"]:
            if vlm_field["type"] == "checkbox":
                match = _match_checkbox(vlm_field, pp_checkbox_fields, used_pp_ids)
            else:
                match = _match_text_field(vlm_field, pp_text_fields, used_pp_ids)

            if match is not None:
                matched_fields.append(match)

        if matched_fields:
            matched_groups.append({
                "group_name": group["group_name"],
                "group_description": group["group_description"],
                "fields": matched_fields,
            })

    return matched_groups
```

**Text 字段匹配**：

```python
def _match_text_field(vlm_field, pp_fields, used_ids) -> dict | None:
    vlm_label = vlm_field["label"].strip().lower()
    best_match = None
    best_score = 0.0

    for pp in pp_fields:
        pp_id = pp["field_id"]
        if pp_id in used_ids:
            continue
        pp_label = pp.get("label", "").strip().lower()

        # 精确匹配
        if vlm_label == pp_label:
            score = 1.0
        # 包含匹配
        elif vlm_label in pp_label or pp_label in vlm_label:
            score = 0.9
        # 模糊匹配
        else:
            score = SequenceMatcher(None, vlm_label, pp_label).ratio()

        if score > best_score and score >= 0.5:
            best_score = score
            best_match = pp

    if best_match:
        used_ids.add(best_match["field_id"])
        return {
            "vlm_label": vlm_field["label"],
            "type": "text",
            "field_id": best_match["field_id"],
            "fill_rect": best_match["fill_rect"],
            "label_bbox": best_match.get("label_bbox"),
            "confidence": best_match.get("confidence", 0.0),
            "match_score": best_score,
            "font_size": best_match.get("font_size"),
        }
    return None
```

**Checkbox 字段匹配**：

```python
def _match_checkbox(vlm_field, pp_checkboxes, used_ids) -> dict | None:
    """
    Checkbox 匹配：用 VLM 的 options 文本匹配 preprocess 的 checkbox options。
    一个 VLM checkbox 可能对应 preprocess 中的多个 checkbox field（每个 option 一个 rect）。
    """
    vlm_options = [opt.strip().lower() for opt in vlm_field.get("options", [])]
    matched_options = []

    for pp in pp_checkboxes:
        pp_id = pp["field_id"]
        if pp_id in used_ids:
            continue
        pp_label = pp.get("label", "").strip().lower()

        # checkbox 的 preprocess label 通常是选项文本（如 "Yes", "No"）
        if pp_label in vlm_options:
            used_ids.add(pp_id)
            matched_options.append({
                "option_text": pp.get("label", ""),
                "field_id": pp_id,
                "fill_rect": pp["fill_rect"],
            })

    if matched_options:
        return {
            "vlm_label": vlm_field["label"],
            "type": "checkbox",
            "options": matched_options,  # 每个 option 有独立的 fill_rect
        }
    return None
```

### 2.7 匹配输出格式（传给 Fill 模块）

```json
{
  "page_num": 1,
  "matched_groups": [
    {
      "group_name": "applicant_info",
      "group_description": "Applicant personal information",
      "fields": [
        {
          "vlm_label": "Name of Applicant",
          "type": "text",
          "field_id": "p1_f001",
          "fill_rect": [267.6, 134.2, 555.4, 164.8],
          "font_size": 10.0
        },
        {
          "vlm_label": "Gender",
          "type": "checkbox",
          "options": [
            {"option_text": "Male", "field_id": "p1_f005", "fill_rect": [100, 200, 112, 212]},
            {"option_text": "Female", "field_id": "p1_f006", "fill_rect": [150, 200, 162, 212]},
            {"option_text": "Other", "field_id": "p1_f007", "fill_rect": [200, 200, 212, 212]}
          ]
        }
      ]
    }
  ],
  "unmatched_vlm_count": 2,
  "unmatched_pp_count": 5
}
```

### 2.8 Recognize 模块公开接口

```python
class PageRecognizeResult:
    page_num: int
    matched_groups: list[dict]
    unmatched_vlm_count: int
    unmatched_pp_count: int

def recognize_page(
    pdf_path: str,
    page_num: int,
    preprocess_fields: list[dict],
    settings: Settings,
) -> PageRecognizeResult:
    """
    对单页执行 VLM 识别 + 匹配。
    1. 渲染页面截图
    2. 调用 VLM 获取分组字段
    3. 与 preprocess_fields 做文本匹配
    4. 返回 matched_groups
    """
```

---

## 3. Fill 模块 (`fill.py`)

### 3.1 职责

1. 接收 matched_groups（来自 Recognize）+ user memory
2. 每页一次 LLM call，输出所有字段的填写值
3. 输出结构化 JSON：每个 field_id 对应填写值

### 3.2 LLM 输入

**输入组成**：
- matched_groups 的精简版（只保留 VLM label + type + options，去掉坐标信息）
- user memory（md 文档内容）

### 3.3 LLM 输出格式

```json
{
  "filled_fields": [
    {"field_id": "p1_f001", "value": "Smith, John A."},
    {"field_id": "p1_f002", "value": "123 Main Street"},
    {"field_id": "p1_f005", "value": "checked"},
    {"field_id": "p1_f006", "value": ""},
    {"field_id": "p1_f010", "value": "03/22/2026"}
  ]
}
```

对于 checkbox 字段：
- `"checked"` 表示勾选
- `""` （空字符串）表示不勾选

### 3.4 LLM Prompt

```
You are a form filling assistant. You are given a list of form field groups and user information. Your task is to fill in each field with the appropriate value from the user's information.

## User Information
{user_memory_content}

## Form Fields
{fields_json}

## Instructions
1. For each "text" field, provide the appropriate value based on the user's information and the field label
2. For each "checkbox" field, set the correct option to "checked" and leave others as "" (empty string)
3. If the user's information does not contain a value for a field, set value to "" (empty string) — do NOT guess or make up information
4. Use the exact format requested by the field label:
   - Dates: use MM/DD/YYYY unless the form specifies otherwise
   - Phone: use the format shown on the form, or default to (XXX) XXX-XXXX
   - Names: follow the order specified by the label (e.g., "Last, First, Middle")
5. For checkbox fields, each option has a field_id. Set value to "checked" for the correct option(s), "" for the rest

Output ONLY valid JSON:
{
  "filled_fields": [
    {"field_id": "string", "value": "string"},
    ...
  ]
}
```

**传给 LLM 的 fields_json 格式**（精简版，不含坐标）：

```json
{
  "groups": [
    {
      "group_name": "applicant_info",
      "group_description": "Applicant personal information",
      "fields": [
        {"field_id": "p1_f001", "label": "Name of Applicant (Last, First, Middle)", "type": "text"},
        {"field_id": "p1_f005", "label": "Gender — Male", "type": "checkbox"},
        {"field_id": "p1_f006", "label": "Gender — Female", "type": "checkbox"},
        {"field_id": "p1_f007", "label": "Gender — Other", "type": "checkbox"}
      ]
    }
  ]
}
```

注意：checkbox 在传给 LLM 时，每个 option 展开为独立的 field，label 格式为 `"问题 — 选项"`。这样 LLM 可以对每个 option 独立输出 `"checked"` 或 `""`。

### 3.5 matched_groups → LLM 输入的转换

```python
def build_llm_input(matched_groups: list[dict]) -> dict:
    """
    将 matched_groups 转换为 LLM 输入格式。
    - text 字段直接保留
    - checkbox 字段展开每个 option 为独立 field
    """
    llm_groups = []
    for group in matched_groups:
        llm_fields = []
        for field in group["fields"]:
            if field["type"] == "text":
                llm_fields.append({
                    "field_id": field["field_id"],
                    "label": field["vlm_label"],
                    "type": "text",
                })
            elif field["type"] == "checkbox":
                for opt in field["options"]:
                    llm_fields.append({
                        "field_id": opt["field_id"],
                        "label": f"{field['vlm_label']} — {opt['option_text']}",
                        "type": "checkbox",
                    })
        llm_groups.append({
            "group_name": group["group_name"],
            "group_description": group["group_description"],
            "fields": llm_fields,
        })
    return {"groups": llm_groups}
```

### 3.6 LLM 调用实现

```python
def call_llm(fields_json: dict, user_memory: str, settings) -> dict:
    """调用 LLM API 填写字段值"""
    client = OpenAI(
        api_key=settings.QWEN_API_KEY,
        base_url=settings.QWEN_BASE_URL,
    )
    prompt = FILL_PROMPT_TEMPLATE.format(
        user_memory_content=user_memory,
        fields_json=json.dumps(fields_json, ensure_ascii=False, indent=2),
    )
    response = client.chat.completions.create(
        model=settings.QWEN_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)
```

### 3.7 User Memory

开发阶段使用一个 md 文件作为 user memory，路径可配置：

```
TestSpace/recognize_fill_test/user_memory.md
```

内容示例：

```markdown
# User Information

- Full Name: John Adam Smith
- Date of Birth: 01/15/1990
- Gender: Male
- SSN: 123-45-6789
- Phone: (555) 123-4567
- Email: john.smith@email.com
- Address: 123 Main Street, Apt 4B, Springfield, IL 62701
- Citizenship: U.S. Citizen
- Employer: ABC Corporation
- Occupation: Software Engineer
- Annual Income: $85,000
```

### 3.8 Fill 模块公开接口

```python
class PageFillResult:
    page_num: int
    filled_fields: list[dict]   # [{"field_id": str, "value": str, "fill_rect": tuple, "font_size": float}]
    unfilled_count: int

def fill_page(
    page_num: int,
    matched_groups: list[dict],
    user_memory: str,
    settings: Settings,
) -> PageFillResult:
    """
    对单页执行 LLM 填写。
    1. 将 matched_groups 转换为 LLM 输入格式
    2. 调用 LLM 获取填写值
    3. 将填写值与 fill_rect 关联
    4. 返回 filled_fields（含 field_id, value, fill_rect, font_size）
    """
```

LLM 输出后，需要将 field_id 映射回 fill_rect（从 matched_groups 中查找），构造最终写入指令。

---

## 4. Writer 模块 (`writer.py`)

### 4.1 职责

1. 接收所有页的 filled_fields（含 fill_rect + value）
2. 使用 pymupdf 将文本写入 PDF 对应位置
3. 处理字体大小、文字溢出、checkbox 勾选

### 4.2 字体策略

- **字体**：统一使用 Helvetica（pymupdf 内置 `"helv"`）
- **字号**：从匹配到的 preprocess 字段的 label 字体大小推断，保持一致
  - 如果 preprocess 提供了 `font_size`，直接使用
  - 否则使用默认值 10pt
- **颜色**：黑色（`(0, 0, 0)`）

### 4.3 溢出处理

```python
def _fit_text(text: str, rect: tuple, font_size: float) -> tuple[str, float]:
    """
    调整文本和字号使其适合 fill_rect。
    返回 (adjusted_text, adjusted_font_size)
    """
    rect_width = rect[2] - rect[0]
    min_font_size = 6.0

    while font_size >= min_font_size:
        text_width = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
        if text_width <= rect_width:
            return text, font_size
        font_size -= 0.5

    # 字号已最小，截断文本
    while len(text) > 1:
        text = text[:-1]
        text_width = fitz.get_text_length(text + "...", fontname="helv", fontsize=font_size)
        if text_width <= rect_width:
            return text + "...", font_size

    return text, font_size
```

### 4.4 文本写入

```python
def write_text_field(page: fitz.Page, rect: tuple, text: str, font_size: float):
    """写入文本字段"""
    text, font_size = _fit_text(text, rect, font_size)
    fitz_rect = fitz.Rect(rect)
    page.add_freetext_annot(
        fitz_rect,
        text,
        fontsize=font_size,
        fontname="helv",
        text_color=(0, 0, 0),
        border_color=None,
        fill_color=None,
    )
```

### 4.5 Checkbox 勾选

```python
def write_checkbox(page: fitz.Page, rect: tuple):
    """在 checkbox 方框内写入勾选标记"""
    fitz_rect = fitz.Rect(rect)
    cx = (rect[0] + rect[2]) / 2
    cy = (rect[1] + rect[3]) / 2
    size = min(rect[2] - rect[0], rect[3] - rect[1])
    font_size = size * 0.7

    # 在中心位置插入 ✓
    page.insert_text(
        (cx - font_size * 0.3, cy + font_size * 0.3),
        "\u2713",  # ✓
        fontsize=font_size,
        color=(0, 0, 0),
    )
```

### 4.6 Writer 公开接口

```python
def write_filled_pdf(
    pdf_path: str,
    output_path: str,
    all_page_fills: list[PageFillResult],
) -> dict:
    """
    将所有页的填写结果写入 PDF。
    返回写入统计：{"total_written": int, "total_skipped": int}
    """
    doc = fitz.open(pdf_path)
    total_written = 0
    total_skipped = 0

    for page_fill in all_page_fills:
        page = doc[page_fill.page_num - 1]
        for field in page_fill.filled_fields:
            if not field["value"]:
                total_skipped += 1
                continue
            if field.get("type") == "checkbox":
                if field["value"] == "checked":
                    write_checkbox(page, field["fill_rect"])
                    total_written += 1
            else:
                write_text_field(page, field["fill_rect"], field["value"], field.get("font_size", 10.0))
                total_written += 1

    doc.save(output_path)
    doc.close()
    return {"total_written": total_written, "total_skipped": total_skipped}
```

---

## 5. Pipeline 整合 (`pipeline.py`)

### 5.1 完整流程

```python
async def fill_with_ai(
    self,
    pdf_path: Path,
    user_info: str,     # 暂时不用，用 memory 文件代替
    output_path: Path,
) -> FillResult:
    # 1. Preprocess
    preprocess_result = self.detector.detect_all(pdf_path)

    # 2. 读取 user memory
    user_memory = read_user_memory()

    all_page_fills = []
    for page_data in preprocess_result["pages"]:
        page_num = page_data["page_num"]
        preprocess_fields = page_data.get("detected_fields", [])

        if not preprocess_fields:
            continue

        # 3. Recognize (VLM)
        recognize_result = recognize_page(
            pdf_path=str(pdf_path),
            page_num=page_num,
            preprocess_fields=preprocess_fields,
            settings=self.settings,
        )

        if not recognize_result.matched_groups:
            continue

        # 4. Fill (LLM)
        fill_result = fill_page(
            page_num=page_num,
            matched_groups=recognize_result.matched_groups,
            user_memory=user_memory,
            settings=self.settings,
        )
        all_page_fills.append(fill_result)

    # 5. Write
    write_stats = write_filled_pdf(
        pdf_path=str(pdf_path),
        output_path=str(output_path),
        all_page_fills=all_page_fills,
    )

    return FillResult(
        filled_fields=[...],
        skipped_fields=[...],
        total_filled=write_stats["total_written"],
        total_skipped=write_stats["total_skipped"],
    )
```

### 5.2 User Memory 读取

开发阶段从固定路径读取 md 文件：

```python
_DEFAULT_MEMORY_PATH = Path("TestSpace/recognize_fill_test/user_memory.md")

def read_user_memory(memory_path: Path | None = None) -> str:
    path = memory_path or _DEFAULT_MEMORY_PATH
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
```

---

## 6. VLM 配置

需要在 `backend/.env` 中添加 VLM 配置：

```
# VLM 配置（需要支持视觉的模型）
VLM_API_KEY=sk-xxx
VLM_MODEL=qwen-vl-max
VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

`config.py` 已有 VLM 相关配置项和 `resolved_vlm_*` 属性，无需修改。

LLM 填写使用已有的 `QWEN_*` 配置（纯文本模型即可）。

---

## 7. 测试计划

### 7.1 测试目录结构

```
TestSpace/recognize_fill_test/
├── common.py              # 共享：TEST_PDFS、路径工具、user_memory 读取
├── user_memory.md         # 测试用 user memory（固定虚构身份）
├── test_recognize.py      # VLM 识别测试（需要 API key）
├── test_match.py          # 匹配逻辑测试（纯本地，不需要 API）
├── test_fill.py           # LLM 填写测试（需要 API key）
├── test_writer.py         # PDF 写入测试（纯本地）
├── test_e2e.py            # 端到端测试：preprocess → recognize → fill → write
└── results/               # 测试输出目录
    ├── recognize/         # VLM 输出 JSON
    ├── fill/              # LLM 输出 JSON
    └── written/           # 最终写入的 PDF
```

### 7.2 test_recognize.py

测试内容：
- 对 6 份测试 PDF 的每页执行 VLM 识别
- 验证输出 JSON 格式正确（有 groups, 每个 field 有 label + type）
- 保存 VLM 原始输出到 `results/recognize/`
- 统计：每页识别的 group 数、field 数、checkbox 数

```python
def test_recognize_page(pdf_path, page_num):
    """单页 VLM 识别测试"""
    # 1. 运行 preprocess
    # 2. 调用 recognize_page
    # 3. 验证输出格式
    # 4. 打印统计
    # 5. 保存 JSON
```

### 7.3 test_match.py

测试内容（**不需要 API 调用**，用 mock VLM 输出测试匹配逻辑）：
- 精确匹配场景
- 包含匹配场景（VLM label 长于 preprocess label）
- 模糊匹配场景（细微文本差异）
- 无匹配场景（VLM 提到但 preprocess 没有的字段）
- Checkbox 匹配场景

```python
def test_exact_match():
    vlm_output = {"groups": [{"fields": [{"label": "Name", "type": "text"}]}]}
    pp_fields = [{"field_id": "p1_f001", "label": "Name", "fill_rect": (100, 100, 300, 120)}]
    result = match_fields(vlm_output["groups"], pp_fields)
    assert len(result[0]["fields"]) == 1
    assert result[0]["fields"][0]["fill_rect"] == (100, 100, 300, 120)
```

### 7.4 test_fill.py

测试内容：
- 读取 `results/recognize/` 中已保存的 VLM 输出（或实时调用）
- 调用 LLM 填写
- 验证输出格式：每个 field_id 都有 value
- 验证 checkbox 字段只有 "checked" 或 ""
- 保存 LLM 输出到 `results/fill/`

### 7.5 test_writer.py

测试内容（**不需要 API 调用**，用 mock 填写数据）：
- 构造 mock filled_fields，写入真实 PDF
- 验证输出 PDF 可以正常打开
- 验证文本溢出处理（长文本自动缩小字号）
- 验证 checkbox 勾选标记

### 7.6 test_e2e.py

端到端测试：
- 从原始 PDF 开始，执行完整流程
- 输入：PDF + user_memory.md
- 输出：填好的 PDF
- 支持 `--batch` 批量测试 6 份 PDF
- 支持 `--input` 单个 PDF 测试
- 打印每页统计：VLM 识别数、匹配数、填写数、写入数

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--memory", default="TestSpace/recognize_fill_test/user_memory.md")
    args = parser.parse_args()
    ...
```

### 7.7 测试用 user_memory.md 内容

```markdown
# User Information

- Full Name: John Adam Smith
- Date of Birth: January 15, 1990
- Social Security Number: 123-45-6789
- Gender: Male
- Marital Status: Single
- Phone Number: (555) 123-4567
- Email: john.smith@email.com

## Address
- Street: 123 Main Street, Apt 4B
- City: Springfield
- State: Illinois
- ZIP Code: 62701
- Country: United States

## Employment
- Employer: ABC Corporation
- Job Title: Software Engineer
- Work Phone: (555) 987-6543
- Annual Income: $85,000
- Employment Start Date: 03/01/2020

## Emergency Contact
- Name: Jane Smith
- Relationship: Sister
- Phone: (555) 456-7890
```

---

## 8. 实现顺序

| 步骤 | 模块 | 说明 |
|------|------|------|
| 1 | `recognize.py` — 渲染 + VLM 调用 | 先确保 VLM 能正常输出 JSON |
| 2 | `test_recognize.py` | 验证 VLM 输出质量，调整 prompt |
| 3 | `recognize.py` — 匹配逻辑 | 实现 text + checkbox 匹配 |
| 4 | `test_match.py` | 用 mock 数据验证匹配逻辑 |
| 5 | `fill.py` | LLM 填写实现 |
| 6 | `test_fill.py` | 验证 LLM 输出质量 |
| 7 | `writer.py` | PDF 写入实现 |
| 8 | `test_writer.py` | 验证写入效果 |
| 9 | `pipeline.py` | 整合完整流程 |
| 10 | `test_e2e.py` | 端到端验证 |

---

## 9. 已知限制与未来改进

| 限制 | 说明 | 计划 |
|------|------|------|
| VLM 可能遗漏字段 | 纯截图识别，遗漏率高于候选确认模式 | v2.1 考虑加入 preprocess 候选列表作为参考 |
| 匹配可能失败 | 文本差异导致匹配不上 | 逐步优化 fuzzy matching 阈值 |
| 不跨页分组 | 同一表单跨页字段独立处理 | v2.1 按需加入跨页合并 |
| User memory 仅支持 md 文件 | 硬编码路径 | v2.1 改为 API 参数传入 |
| 字体固定 Helvetica | 不适配所有表单风格 | v2.1 从 text_spans 推断字体 |
| 不支持多行文本 | fill_rect 只写一行 | v2.1 用 insert_htmlbox 支持多行 |
