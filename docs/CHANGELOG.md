# SmartFill CHANGELOG

> 本文档记录项目架构决策与开发历程

---

## [v0.1.0] - 2026-02-05 (架构基线)

### 🏗️ 架构概述

- **架构模式**: 前后端分离的单体应用
- **部署环境**: 前端 Vercel / 后端 Railway
- **预期规模**: 10-20人最大并发
- **开发资源**: 1人开发，使用 Coding Agent 辅助

### 🔧 技术栈

| 层面 | 选型 | 版本 | 理由 |
|------|------|------|------|
| 前端框架 | React | 18.x | 生态成熟，Coding Agent 友好 |
| 构建工具 | Vite | 5.x | 开发体验极佳，构建快速 |
| 类型系统 | TypeScript | 5.x | 提升代码可靠性，AI 生成代码更安全 |
| UI 组件 | shadcn/ui | latest | 可定制，无需 npm 依赖，便于手动调整 |
| 样式方案 | Tailwind CSS | 3.x | 响应式天然，移动端适配简单 |
| HTTP 客户端 | Axios | 1.x | 文件上传支持好 |
| 后端框架 | FastAPI | 0.109+ | 异步支持，自动API文档，Python生态 |
| Python 版本 | Python | 3.10+ | 类型提示支持，asyncio 成熟 |
| PDF 处理 | pypdf | 4.x | AcroForm 读写支持，活跃维护 |
| AI 服务 | 通义千问 (Qwen) | qwen-plus/turbo | 成本低，中文支持好 |
| 文件存储 | 本地临时目录 | - | 处理完即删除，无持久化 |

### 📦 核心模块

#### 后端模块（backend/app/）

1. **routers/** - API 路由层
   - 处理 HTTP 请求
   - 参数验证
   - 响应格式化

2. **services/** - 业务逻辑层
   - `pdf_service.py` - PDF 表单字段读写
   - `ai_service.py` - AI 调用抽象接口（Qwen 实现）
   - `ocr_service.py` - OCR 接口（预留）

3. **models/** - 数据模型
   - Pydantic Schemas 定义

4. **utils/** - 工具函数
   - 文件处理
   - 验证函数

5. **config.py** - 配置管理
   - 环境变量管理
   - 常量定义

#### 前端模块（frontend/src/）

1. **components/common/** - 通用组件
   - Button, Loading, Input

2. **components/features/** - 业务组件
   - FileUpload, InfoInput, DownloadButton

3. **hooks/** - 自定义 Hooks
   - useFileUpload, useApi

4. **services/** - API 调用
   - 后端接口封装

5. **types/** - TypeScript 类型定义

### 📊 数据流

```
用户上传PDF
    ↓
前端验证（大小、格式）
    ↓
POST /api/v1/upload
    ↓
后端接收文件 → 临时存储
    ↓
POST /api/v1/extract-fields
    ↓
pypdf 读取表单字段
    ↓
用户输入填写信息
    ↓
POST /api/v1/fill
    ↓
Qwen API 匹配字段
    ↓
pypdf 填写表单 → 生成新PDF
    ↓
返回文件流 → 前端下载
    ↓
删除临时文件
```

### 🔌 API 设计

**Base URL**: `/api/v1`

| 端点 | 方法 | 功能 | 请求 | 响应 |
|------|------|------|------|------|
| `/upload` | POST | 上传 PDF | multipart/form-data | `{file_id: string}` |
| `/extract-fields` | POST | 提取表单字段 | `{file_id: string}` | `{fields: string[]}` |
| `/fill` | POST | AI 填写 PDF | `{file_id: string, user_info: string}` | PDF 文件流 |
| `/health` | GET | 健康检查 | - | `{status: "ok"}` |

### 📁 项目结构

```
SmartFill/
├── frontend/                     # 前端项目
│   ├── public/
│   │   └── favicon.ico
│   ├── src/
│   │   ├── components/
│   │   │   ├── common/
│   │   │   │   ├── Button.tsx
│   │   │   │   ├── Loading.tsx
│   │   │   │   └── Input.tsx
│   │   │   └── features/
│   │   │       ├── FileUpload.tsx
│   │   │       ├── InfoInput.tsx
│   │   │       └── DownloadButton.tsx
│   │   ├── hooks/
│   │   │   ├── useFileUpload.ts
│   │   │   └── useApi.ts
│   │   ├── services/
│   │   │   └── api.ts
│   │   ├── types/
│   │   │   └── index.ts
│   │   ├── utils/
│   │   │   └── helpers.ts
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── package.json
│   ├── .env.example
│   └── .gitignore
│
├── backend/                      # 后端项目
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   └── pdf.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── pdf_service.py
│   │   │   ├── ai_service.py
│   │   │   └── ocr_service.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── schemas.py
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── file_handler.py
│   │       └── validators.py
│   ├── tests/
│   │   └── __init__.py
│   ├── requirements.txt
│   ├── .env.example
│   └── .gitignore
│
├── docs/
│   ├── PRD.md
│   └── CHANGELOG.md
│
└── README.md
```

### 🎨 前端设计与 UI

#### 审美方向：Refined Utility（精致实用主义）

**设计理念**
- **功能优先，细节出彩**: 工具的本质是解决问题，但每个交互细节都应该让人感到愉悦
- **温暖的专业感**: 避免冷冰冰的科技感，也避免过度装饰的"可爱风"
- **移动端原生体验**: 不是桌面端的缩小版，而是为触摸操作专门设计的流畅体验

---

#### 字体系统

**Display Font（标题/强调）**
- **字体**: [Clash Display](https://www.fontshare.com/fonts/clash-display) 或 [General Sans](https://www.fontshare.com/fonts/general-sans)
- **用途**: 页面标题、步骤指示、CTA 按钮
- **特点**: 几何感强，现代但不失个性，中等字重 (500-600) 可读性好
- **回退**: `'Clash Display', 'General Sans', system-ui, sans-serif`

**Body Font（正文/说明）**
- **字体**: [Satoshi](https://www.fontshare.com/fonts/satoshi) 或 [Switzer](https://www.fontshare.com/fonts/switzer)
- **用途**: 正文、提示信息、输入框内容
- **特点**: 温和、易读、略带人文气息
- **回退**: `'Satoshi', 'Switzer', -apple-system, sans-serif`

**Monospace（技术信息）**
- **字体**: [JetBrains Mono](https://www.jetbrains.com/lp/mono/) 或 [Fira Code](https://github.com/tonsky/FiraCode)
- **用途**: 文件名、错误提示、字段预览
- **回退**: `'JetBrains Mono', 'Courier New', monospace`

> **实现**: 通过 Google Fonts 或 Fontshare CDN 引入，或下载 woff2 文件本地托管

---

#### 色彩系统

**主题色调**: Warm Neutral（温暖中性）

```css
/* Tailwind 配置（tailwind.config.js） */
colors: {
  // 主背景：米白色而非纯白，降低视觉疲劳
  canvas: {
    DEFAULT: '#FAF8F5',  // 主背景
    dark: '#2C2A27',     // 深色模式背景（预留）
  },
  
  // 主色：深橄榄绿（专业、可靠、自然）
  primary: {
    50: '#F5F7F4',
    100: '#E8EDE6',
    200: '#D1DBC9',
    300: '#B3C5A8',
    400: '#8FA87A',
    500: '#6B8E5A',   // 主色调
    600: '#557246',
    700: '#435A37',
    800: '#37492E',
    900: '#2E3D27',
  },
  
  // 强调色：暖橙色（行动、上传、下载）
  accent: {
    DEFAULT: '#E87A42',
    light: '#F59D6C',
    dark: '#D66430',
  },
  
  // 中性色：暖灰色系统
  neutral: {
    50: '#F9F8F6',
    100: '#EAE8E4',
    200: '#D5D2CC',
    300: '#B8B4AC',
    400: '#8F8A80',
    500: '#6B6760',
    600: '#56524B',
    700: '#46423D',
    800: '#3A3733',
    900: '#2C2A27',
  },
  
  // 状态色
  success: '#6B8E5A',
  warning: '#E8A742',
  error: '#D64430',
}
```

**渐变使用**（仅用于特定场景，非全局）
- **上传区域激活态**: `linear-gradient(135deg, #F5F7F4 0%, #E8EDE6 100%)`
- **按钮 hover**: `linear-gradient(180deg, #6B8E5A 0%, #557246 100%)`

---

#### 空间与排版

**间距系统**（基于 8px 网格）
```javascript
// Tailwind spacing 扩展
spacing: {
  '18': '4.5rem',   // 特殊间距用于移动端大拇指区域
  '22': '5.5rem',
  '30': '7.5rem',
}
```

**圆角策略**
- 主要容器: `rounded-2xl` (16px) - 柔和但不过度
- 按钮/输入框: `rounded-xl` (12px)
- 小标签/徽章: `rounded-lg` (8px)
- 避免使用 `rounded-full`，保持几何感

**阴影层级**
```css
/* 自定义阴影（tailwind.config.js） */
boxShadow: {
  'soft': '0 2px 12px rgba(44, 42, 39, 0.06)',
  'lift': '0 4px 24px rgba(44, 42, 39, 0.12)',
  'float': '0 12px 48px rgba(44, 42, 39, 0.18)',
}
```

---

#### 组件设计规范

**FileUpload 组件**
```typescript
// 设计要点
- 拖拽区域：全屏高度（移动端），至少 400px（桌面端）
- 状态切换：idle → hover → dragover → uploading → success/error
- 视觉反馈：
  * idle: 虚线边框 (border-dashed border-2 border-neutral-300)
  * hover: 实线边框 + 背景渐变 (border-solid border-primary-500 bg-gradient)
  * dragover: 放大动画 (scale-105) + 阴影加深
  * uploading: 骨架屏 + 进度条（带数字百分比）
- 图标：使用 lucide-react 的 Upload 图标，尺寸 48px
- 文字层级：
  * 主标题: text-2xl font-display font-semibold
  * 辅助说明: text-sm text-neutral-500
```

**InfoInput 组件**
```typescript
// 设计要点
- 使用 textarea 而非多行 input
- 最小高度: 160px（移动端），200px（桌面端）
- 占位符示例要具体：
  "姓名：张三
   身份证：110101199001011234
   电话：138-0013-8000
   地址：北京市朝阳区..."
- Focus 状态: 边框颜色过渡 + 轻微放大 (scale-[1.01])
- 字符计数器：右下角显示，超过 500 字提示
```

**Button 组件**
```typescript
// 三种变体
1. Primary (主要行动)
   - 背景: bg-primary-600 hover:bg-primary-700
   - 文字: text-white font-display font-semibold
   - 高度: h-14 (移动端大拇指友好)
   - 图标: 左侧或右侧，使用 lucide-react
   - 动画: hover 时轻微上移 (translate-y-[-2px]) + shadow-lift

2. Secondary (次要操作)
   - 背景: bg-transparent border-2 border-neutral-300
   - 文字: text-neutral-700
   - Hover: border-primary-500 + text-primary-700

3. Ghost (轻量操作)
   - 背景: 透明
   - 文字: text-neutral-600 hover:text-primary-600
   - 下划线动画: hover 时从左到右展开
```

**Loading 状态**
```typescript
// 避免使用通用 spinner，设计定制动画
方案: 三个点跳跃动画 + 文字提示
- 使用 CSS @keyframes 实现
- 点的颜色: primary-500
- 动画延迟: 0s, 0.15s, 0.3s (形成波浪)
- 配合文字: "正在处理您的文件..." (每 2 秒切换提示)
```

**DownloadButton**
```typescript
// 特殊处理：成功状态的庆祝感
- 成功时: 按钮背景从 primary 变为 accent (橙色)
- 图标动画: Download 图标向下弹跳 + 缩放
- 微交互: 短促振动（移动端 navigator.vibrate(200)）
- 文字切换: "生成成功！点击下载" (带 ✓ 图标)
```

---

#### 动画与微交互

**页面加载**
```css
/* 使用 animation-delay 实现渐进式出现 */
.animate-fade-in-up {
  animation: fadeInUp 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}

/* 为不同元素设置不同延迟 */
header: delay-0
upload-zone: delay-100
info-input: delay-200
submit-btn: delay-300
```

**状态转场**
- 所有状态切换使用 `transition-all duration-300 ease-out`
- 颜色变化: `transition-colors duration-200`
- 尺寸变化: `transition-transform duration-400 cubic-bezier(0.34, 1.56, 0.64, 1)` (带弹性)

**手势反馈**（移动端）
- 按钮按下: `active:scale-95` (轻微缩小)
- 拖拽文件: 鼠标/手指位置实时显示文件名徽章

**滚动效果**
- 页面滚动时 header 添加 `backdrop-blur-md` 毛玻璃效果
- 步骤指示器吸附在顶部（移动端）

---

#### 响应式设计

**断点策略**
```javascript
// Tailwind 断点（保持默认）
sm: '640px',   // 大手机横屏
md: '768px',   // 平板竖屏
lg: '1024px',  // 桌面
xl: '1280px',  // 大屏
```

**移动优先实现清单**
- [ ] 所有触摸目标 ≥ 48x48px (Apple HIG 标准)
- [ ] 核心内容区域宽度: max-w-md (移动), max-w-2xl (桌面)
- [ ] 导航/操作区域: 固定在底部 (iOS Safari 适配 safe-area-inset-bottom)
- [ ] 横屏适配: 高度受限时压缩垂直间距
- [ ] 字体缩放: 移动端 text-base (16px), 桌面端 text-lg (18px)

**桌面端增强**
- 拖拽区域显示更多引导信息（"或点击选择文件"）
- 添加键盘快捷键提示（如 Ctrl+V 粘贴文件）
- 鼠标 hover 显示更多提示（如字段名称说明）

---

#### 视觉细节

**背景纹理**
```css
/* 主背景添加微妙噪点，避免单调 */
body {
  background-color: #FAF8F5;
  background-image: url("data:image/svg+xml,%3Csvg width='100' height='100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence baseFrequency='0.9' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.03'/%3E%3C/svg%3E");
}
```

**边框处理**
- 避免纯黑边框，使用 `border-neutral-200` (warm gray)
- 重要分隔使用 `border-t-2` 加粗
- Input focus: `ring-2 ring-primary-500 ring-offset-2`

**图标使用**
- 统一使用 [lucide-react](https://lucide.dev) 图标库
- 尺寸: 操作图标 20px, 装饰图标 24px, hero 图标 48px
- Stroke width: 2px (保持几何感)

**Empty State / Error State**
- 使用插画而非纯文字（可考虑 [unDraw](https://undraw.co) 自定义色彩）
- 插画主色使用 primary-500
- 配合幽默的文案（如 "这个 PDF 好像不太配合..."）

---

#### 暗色模式（预留）

虽然第一版不实现，但预留 CSS 变量以便快速切换：

```css
:root {
  --color-canvas: #FAF8F5;
  --color-text-primary: #2C2A27;
  --color-text-secondary: #6B6760;
}

@media (prefers-color-scheme: dark) {
  :root {
    --color-canvas: #2C2A27;
    --color-text-primary: #FAF8F5;
    --color-text-secondary: #B8B4AC;
  }
}
```


### 🔐 安全与隐私

- 文件处理完立即删除（无持久化存储）
- 不记录用户信息
- HTTPS 加密传输（Vercel/Railway 自带）
- 文件大小限制：10MB

### ⚡ 性能要求

- 文件上传: < 5秒（10MB 以内）
- AI 处理: < 30秒
- 文件下载: < 5秒

### 🧩 扩展接口设计

#### AI 服务抽象

- 定义 `AIService` 抽象基类，包含字段匹配方法
- 当前实现为 `QwenService`（通义千问）
- 未来可通过实现相同接口切换到 OpenAI 或 Claude
- 接口位置：`services/ai_service.py`

#### OCR 服务预留

- 定义 `OCRService` 抽象基类，包含文本提取方法
- 当前不实现具体服务
- 未来可接入阿里云 OCR、腾讯云 OCR 等
- 接口位置：`services/ocr_service.py`

#### 文件存储抽象

- 定义 `FileStorage` 抽象基类，包含保存和删除方法
- 当前实现为 `LocalStorage`（本地临时目录）
- 未来可切换到 AWS S3、阿里云 OSS 等云存储
- 接口位置：`utils/file_handler.py`

### ⚠️ 技术债务 & 已知限制

- [ ] **并发处理**: 当前不支持，同一时间只能处理 1 个请求
- [ ] **错误重试**: AI 调用失败无重试机制
- [ ] **日志系统**: 无结构化日志，调试依赖 print
- [ ] **监控告警**: 无性能监控和异常告警
- [ ] **测试覆盖**: 第一版无单元测试
- [ ] **PDF 兼容性**: 仅支持标准 AcroForm，复杂表单可能失败
- [ ] **文件清理**: 依赖进程退出，异常退出可能遗留临时文件

### 📝 核心技术决策

1. **选择 Vite 而非 Create React App**
   - 开发服务器启动速度快（秒级 vs 分钟级）
   - Coding Agent 生成的代码可以快速验证

2. **选择 shadcn/ui 而非 Ant Design**
   - 组件代码直接复制到项目，无 npm 依赖
   - 便于后续手动调整样式

3. **选择 FastAPI 而非 Flask**
   - 原生异步支持（虽然第一版用不到）
   - 自动生成 API 文档，便于调试

4. **选择通义千问而非 OpenAI**
   - 成本低（约为 GPT-4 的 1/10）
   - 中文表单支持更好

5. **选择本地存储而非 OSS**
   - 降低复杂度
   - 符合"处理完即删除"的需求
   - 抽象接口便于未来切换

6. **不做用户系统**
   - 降低开发成本
   - 避免隐私合规问题
   - 符合 MVP 验证目标

7. **依赖方向控制**
   - routers/ → services/ → utils/
   - 业务逻辑（services）不依赖 HTTP 框架
   - 便于未来重构到多模块架构

### 🚀 环境变量

**前端配置**
- `VITE_API_BASE_URL` - 后端 API 地址（开发环境：http://localhost:8000/api/v1）

**后端配置**
- `QWEN_API_KEY` - 通义千问 API 密钥
- `QWEN_MODEL` - 模型选择（qwen-plus 或 qwen-turbo）
- `MAX_FILE_SIZE_MB` - 文件大小限制（默认 10MB）
- `TEMP_DIR` - 临时文件存储目录（默认 /tmp/smartfill）

---

## [v0.1.0-dev.1] - 2026-02-05 (基础框架)

### 🎯 版本目标

完成前后端基础框架搭建，验证文件上传完整链路。

### ✅ 实现内容

**前端**
- 初始化 Vite + React 18 + TypeScript 项目
- 配置 Tailwind CSS 和 PostCSS
- 实现文件上传 UI 组件
- 实现文件拖拽上传和点击上传功能
- 添加文件格式和大小验证（客户端侧）
- 配置 Axios 调用后端 API

**后端**
- 初始化 FastAPI 项目结构
- 实现 `/api/v1/upload` 文件接收接口
- 添加文件格式验证（仅接受 PDF）
- 添加文件大小验证（最大 10MB）
- 实现临时文件存储逻辑
- 配置 CORS 支持前端调用

**测试验证**
- 前端能够成功选择和上传 PDF 文件
- 后端能够接收文件并返回文件 ID
- 文件存储到临时目录
- 错误处理正常（格式错误、超大文件等）

### 📂 涉及文件

**前端新增**
- `frontend/package.json` - 项目依赖配置
- `frontend/vite.config.ts` - Vite 配置
- `frontend/tailwind.config.js` - Tailwind 配置
- `frontend/tsconfig.json` - TypeScript 配置
- `frontend/src/App.tsx` - 主应用组件
- `frontend/src/components/features/FileUpload.tsx` - 文件上传组件
- `frontend/src/services/api.ts` - API 调用封装

**后端新增**
- `backend/requirements.txt` - Python 依赖
- `backend/app/main.py` - FastAPI 入口
- `backend/app/config.py` - 配置管理
- `backend/app/routers/pdf.py` - PDF 相关路由
- `backend/app/utils/file_handler.py` - 文件处理工具
- `backend/app/utils/validators.py` - 验证函数
- `backend/.env.example` - 环境变量模板

### 🔄 后续计划

下一版本（v0.1.0-dev.2）将实现 PDF 字段提取功能。

---

## [v0.1.0-dev.2] - 2026-02-07 (PDF 字段读写)

### 🎯 版本目标

实现 PDF 表单字段的完整读写能力，打通"上传 → 提取字段 → 填写 → 下载"的后端核心链路。本版本聚焦**后端 PDF 处理逻辑**，前端仅做最小必要的接口对接。

### 📋 任务拆解

#### 1. 完善 `POST /extract-fields` 接口

- 接收 `file_id`，从临时目录读取已上传的 PDF
- 调用 `pdf_service.extract_form_fields()` 提取 AcroForm 字段
- 返回字段名称列表 `{file_id, fields: string[], field_count: int, message}`
- 错误处理：
  - `file_id` 不存在 → 404 "文件不存在或已过期"
  - PDF 无表单字段 → 400 "暂不支持扫描版PDF，请上传可编辑的PDF文件"（与 PRD 3.3 错误处理一致）
  - PDF 解析异常 → 500 "无法识别表单字段，请确认这是一个标准表单"

#### 2. 增强 `PDFService` 字段提取逻辑

- 完善 `extract_form_fields()` 方法：
  - 除字段名称外，同时提取字段类型（文本框、复选框、下拉框等）和已有默认值
  - 返回结构化字段信息 `List[FieldInfo]`，包含 `name`, `type`, `default_value`
  - 遍历所有页面的表单字段（当前实现仅用 `get_form_text_fields()`，可能遗漏非文本字段）
- 新增 `has_form_fields()` 方法：快速判断 PDF 是否为可编辑表单
- 新增 `get_field_details()` 方法：获取字段详细信息（用于调试和后续 AI 匹配）

#### 3. 完善 `PDFService` 表单填写逻辑

- 增强 `fill_form()` 方法：
  - 支持多页表单字段填写（当前实现仅写入第一页）
  - 填写后保留原有 PDF 格式和样式
  - 返回更详细的结果（填写了哪些字段、跳过了哪些字段）
- 输出文件命名规则：`原文件名_filled.pdf`（与 PRD F4 一致）

#### 4. 实现 `POST /fill` 接口（简化版，不含 AI）

- 本版本先实现**手动字段映射**的填写接口，不接入 AI
- 请求体：`{file_id: string, field_values: Dict[str, str]}`（直接传入字段名→值的映射）
- 流程：读取 PDF → 填写字段 → 生成新 PDF → 返回文件流
- 响应：直接返回填好的 PDF 文件流（`application/pdf`），前端触发下载
- 错误处理：
  - `file_id` 不存在 → 404
  - 填写失败 → 500 "填写失败，请检查输入信息或稍后重试"

#### 5. 添加 Pydantic 模型

- 新增 `FieldInfo` 模型：字段详细信息（名称、类型、默认值）
- 扩展 `ExtractFieldsResponse`：增加 `field_count` 和结构化字段信息
- 新增 `FillByFieldsRequest`：手动字段填写请求（区别于未来的 AI 填写）
- 新增 `FillResponse`：填写结果响应（成功/失败、填写字段数等）

#### 6. 错误处理与边界情况

- PDF 文件损坏或无法解析
- PDF 有密码保护（加密 PDF）
- 表单字段为空（非可编辑 PDF）
- 填写值类型不匹配（如给复选框传入长文本）
- 输出文件写入失败（磁盘空间不足等）

#### 7. 测试验证

- 准备 2-3 个测试用 PDF 文件（放在 `backend/tests/fixtures/` 下）：
  - 标准可编辑 PDF（带多种字段类型）
  - 无表单字段的 PDF（纯文本/扫描版）
  - 多页表单 PDF
- 手动测试完整流程：上传 → 提取字段 → 填写 → 下载
- 通过 FastAPI `/docs` 交互式文档逐个接口验证

### ✅ 预期实现内容

**后端**
- 实现 `POST /api/v1/extract-fields` 字段提取接口
- 实现 `POST /api/v1/fill` 表单填写接口（手动映射版）
- 完善 `PDFService` 的字段提取和填写方法
- 增加结构化字段信息模型 `FieldInfo`
- 完善错误处理（文件不存在、非可编辑 PDF、加密 PDF 等）
- 填写完成后清理临时文件

**前端（最小改动）**
- 在 `api.ts` 中新增 `extractFields()` 和 `fillPdf()` 接口封装
- 前端类型定义补充 `FieldInfo` 等类型
- 暂不做前端 UI 变更（字段展示和填写 UI 留到后续版本）

### 📂 涉及文件

**后端修改**
- `backend/app/routers/pdf.py` - 新增 extract-fields 和 fill 路由
- `backend/app/services/pdf_service.py` - 完善字段提取和填写逻辑
- `backend/app/models/schemas.py` - 新增 FieldInfo 等数据模型
- `backend/app/utils/validators.py` - 新增 file_id 存在性验证

**后端新增**
- `backend/tests/fixtures/` - 测试用 PDF 文件目录

**前端修改**
- `frontend/src/services/api.ts` - 新增接口调用函数
- `frontend/src/types/index.ts` - 补充类型定义

### ⚠️ 注意事项

1. **本版本不接入 AI**：`/fill` 接口接收的是前端直接传入的 `{字段名: 值}` 映射，AI 语义匹配在 v0.1.0-dev.3 实现
2. **pypdf 版本**：使用 `pypdf>=4.0.0`（非 PyPDF2），API 有差异，注意参考正确的文档
3. **文件生命周期**：填写完成并返回文件流后，应清理原始临时文件和生成的临时文件
4. **并发安全**：当前不考虑并发，同一文件不会被同时读写

---

## [v0.1.0-dev.3] - 2026-02-09 (AI 智能填写)

### 🎯 版本目标

接入通义千问（Qwen）大模型，实现 **用户自然语言输入 → AI 语义匹配表单字段 → 自动填写 PDF** 的核心智能链路。本版本完成后，产品的 MVP 核心流程将全部打通。

### 🔑 API 配置（临时，上线前删除）

通义千问使用 OpenAI 兼容模式调用：

```
API_KEY: sk-dcff60c19e3245e387fdfa95958dfd2e
BASE_URL: https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL: qwen-turbo
```

**环境变量配置**（写入 `backend/.env`）：
```
QWEN_API_KEY=sk-dcff60c19e3245e387fdfa95958dfd2e
QWEN_MODEL=qwen-turbo
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 📋 任务拆解

#### 1. 新增依赖

- `requirements.txt` 中启用 `openai>=1.10.0`（使用 OpenAI 兼容模式调用通义千问）
- `config.py` 新增 `QWEN_BASE_URL` 环境变量

#### 2. 实现 `QwenService`

完善 `ai_service.py` 中已预留的 `QwenService` 类：

- 使用 `openai` SDK 的 `client.chat.completions.create()` 调用
- 核心方法 `match_fields(fields, user_info) → Dict[str, str]`：
  - 输入：PDF 表单字段名列表 + 用户的自然语言信息
  - 输出：`{字段名: 填写值}` 的映射
  - AI 返回 JSON 格式，代码解析后直接传给 `pdf_service.fill_form()`
- Prompt 设计要点：
  - 明确告知 AI 可用的字段名列表
  - 要求 AI 严格输出 JSON，key 必须是字段列表中的名称
  - 对于无法匹配的字段，值留空字符串
  - 支持中英文混合的字段名和用户输入
- 错误处理：API 调用超时、返回格式异常、JSON 解析失败

#### 3. 实现 `POST /api/v1/fill`（AI 版）

修改现有 `/fill` 路由，使用 `FillRequest`（`{file_id, user_info}`）：

- 流程：提取字段 → AI 匹配 → 填写 PDF → 返回文件流
- 保留 `/fill-by-fields` 手动映射接口（重命名现有 `/fill`），用于调试
- 错误处理：
  - AI 调用失败 → 500 "AI 服务暂时不可用，请稍后重试"
  - AI 返回格式异常 → 500 "填写失败，请检查输入信息或稍后重试"
  - 超时（>30秒）→ 500 "处理超时，请稍后重试"

#### 4. Prompt 工程

```
你是一个 PDF 表单填写助手。

任务：将用户提供的信息匹配到 PDF 表单的字段中。

PDF 表单字段列表：
{fields_json}

用户提供的信息：
{user_info}

要求：
1. 将用户信息准确匹配到对应的字段
2. 只使用上面列出的字段名作为 key
3. 无法匹配的字段，值设为空字符串 ""
4. 直接输出 JSON，不要包含其他文字
5. 所有值都是字符串类型

输出格式示例：
{"姓名": "张三", "电话": "13800138000", "地址": ""}
```

#### 5. 前端对接

- `api.ts` 新增 `fillPdfWithAI(file_id, user_info)` 接口
- 前端类型无需大改，`FillRequest` 已预留

### ✅ 预期实现内容

**后端**
- 实现 `QwenService.match_fields()` AI 字段匹配
- 实现 `POST /api/v1/fill` AI 智能填写接口
- 现有手动填写接口改为 `POST /api/v1/fill-by-fields`
- `config.py` 新增 `QWEN_BASE_URL` 配置
- `requirements.txt` 启用 `openai` 依赖

**前端**
- `api.ts` 新增 AI 填写接口调用

### 📂 涉及文件

**后端修改**
- `backend/app/services/ai_service.py` - 实现 QwenService
- `backend/app/routers/pdf.py` - 新增 AI fill 路由，重命名旧路由
- `backend/app/config.py` - 新增 QWEN_BASE_URL，修复已知格式问题
- `backend/requirements.txt` - 启用 openai 依赖
- `backend/.env.example` - 补充 AI 相关环境变量说明

**前端修改**
- `frontend/src/services/api.ts` - 新增 AI 填写接口

### ⚠️ 注意事项

1. **使用 OpenAI 兼容模式**：不用 `dashscope` SDK，统一用 `openai` SDK + 自定义 `base_url`，未来切换 OpenAI/Claude 更方便
2. **Prompt 需要迭代**：第一版 Prompt 先跑通，后续根据测试结果调优

---

## [v0.1.0-dev.4] - 2026-02-10 (前端完整流程 & MVP 定版)

### 🎯 版本目标

将前端 3 步流程（上传 → 输入信息 → AI 填写 & 下载）完整串联，实现 PRD 3.2 定义的完整用户闭环。本版本完成后，SmartFill MVP 核心功能全部就绪，产品可交付种子用户试用。

**核心产出**：用户可以在一个页面内，完成 "上传 PDF → 自然语言输入信息 → AI 自动填写 → 下载填好的 PDF" 全流程。

### 📋 任务拆解

#### 1. 新增 `useSmartFill` Hook — 全流程状态管理

新增 `frontend/src/hooks/useSmartFill.ts`，作为 3 步流程的核心状态机：

```typescript
// 全流程步骤
type FlowStep = 'upload' | 'input' | 'filling' | 'download';

interface UseSmartFillReturn {
  // 当前步骤
  currentStep: FlowStep;

  // Step 1: 上传相关（复用 useFileUpload）
  fileUpload: ReturnType<typeof useFileUpload>;

  // Step 2: 信息输入
  userInfo: string;
  setUserInfo: (value: string) => void;

  // Step 3: AI 填写 & 下载
  filledPdfBlob: Blob | null;
  filledFileName: string;
  fillError: string | null;
  isFilling: boolean;

  // 操作
  handleStartFill: () => Promise<void>;  // 触发 AI 填写
  handleDownload: () => void;            // 触发下载
  handleReset: () => void;               // 重置全部，回到第 1 步
}
```

**状态流转逻辑**：

```
upload(idle) → upload(uploading) → upload(success) → input → filling → download
                    ↓                                           ↓
               upload(error)                              fillError → input
                                                                     (允许修改信息重试)

任意状态 → handleReset() → upload(idle)
```

**关键设计决策**：
- `currentStep` 根据子状态自动推导：
  - `upload`: 当 `fileUpload.status` 为 `idle | uploading | error` 时
  - `input`: 当上传成功且用户未点击"开始填写"时
  - `filling`: 当 AI 正在处理时（显示 LoadingOverlay）
  - `download`: 当 `filledPdfBlob` 非空时
- 不需要手动切换步骤，状态完全由数据驱动
- `handleStartFill()` 内部调用 `fillPdfWithAI(fileId, userInfo)`，拿到 Blob 后存入 state
- `handleDownload()` 用 `URL.createObjectURL` 创建下载链接，文件名使用 `原文件名_filled.pdf`
- `handleReset()` 清空所有 state，调用 `fileUpload.reset()`

#### 2. 重构 `App.tsx` — 3 步流程 UI

**整体结构**：

```
Header (不变)
  ↓
Hero Section (随步骤变化 subtitle)
  ↓
Steps Indicator (步骤指示器，高亮当前步骤，已完成步骤打勾)
  ↓
Main Content Area (根据 currentStep 渲染不同组件)
  ├── upload  → <FileUpload />
  ├── input   → 上传成功摘要 + <InfoInput /> + "开始填写"按钮
  ├── filling → <LoadingOverlay /> (覆盖全屏)
  └── download → 成功提示 + <DownloadButton /> + "重新开始"按钮
  ↓
Footer (不变)
```

**各步骤 UI 细节**：

**Step 1 - 上传文件** (`currentStep === 'upload'`)：
- 渲染 `<FileUpload />` 组件（与当前行为一致）
- 上传成功后，`currentStep` 自动切换到 `input`

**Step 2 - 输入信息** (`currentStep === 'input'`)：
- 顶部显示上传成功摘要卡片（文件名、文件大小、勾选图标）
- 渲染 `<InfoInput />` 组件
- 底部渲染"开始填写"按钮（`<Button>` primary，disabled 当 `userInfo` 为空）
- 底部二级按钮："重新选择文件"（触发 `handleReset()`）
- 输入验证：`userInfo.trim().length > 0` 才允许提交

**Step 3a - AI 填写中** (`currentStep === 'filling'`)：
- 渲染 `<LoadingOverlay isVisible={true} text="AI 正在填写表单..." />`
- 覆盖全屏，用户无法操作
- 填写失败 → 回到 `input` 步骤，显示错误提示，用户可修改信息后重试

**Step 3b - 下载结果** (`currentStep === 'download'`)：
- 顶部成功提示区域（绿色背景，勾选图标 + "填写完成！"）
- 渲染 `<DownloadButton isReady={true} fileName={filledFileName} />`
- 底部"重新开始"按钮（触发 `handleReset()`）

**Hero subtitle 随步骤变化**：
- `upload`: "上传表单，输入信息，AI 自动完成填写"
- `input`: "请输入需要填写的信息"
- `filling`: "AI 正在处理您的表单..."
- `download`: "表单填写完成，请下载查看"

#### 3. 改进 Steps Indicator — 动态步骤指示器

将 `App.tsx` 中静态的步骤指示器改为动态组件：

- 当前步骤：高亮（primary 色）
- 已完成步骤：绿色勾选 ✓
- 未到达步骤：灰色
- 步骤映射：
  - Step 1 "上传文件": active 当 `currentStep === 'upload'`，completed 当 `currentStep !== 'upload'`
  - Step 2 "输入信息": active 当 `currentStep === 'input' | 'filling'`，completed 当 `currentStep === 'download'`
  - Step 3 "下载结果": active 当 `currentStep === 'download'`

步骤指示器放在 Hero Section 下方、Main Content Area 上方，始终可见。

#### 4. 文件下载实现

在 `useSmartFill` 的 `handleDownload()` 中：

```typescript
const handleDownload = () => {
  if (!filledPdfBlob) return;
  const url = URL.createObjectURL(filledPdfBlob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filledFileName; // e.g. "合同_filled.pdf"
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};
```

文件名生成规则：`generateFileName(originalFileName)` 已在 `helpers.ts` 中实现，格式为 `原文件名_filled.pdf`。

#### 5. 错误处理 (对应 PRD 3.3)

| 场景 | 处理方式 | 用户感知 |
|------|---------|---------|
| 上传阶段 - 非 PDF | `FileUpload` 组件已处理 | "仅支持 PDF 格式" |
| 上传阶段 - 超 10MB | `FileUpload` 组件已处理 | "文件大小不能超过 10MB" |
| 上传阶段 - 非可编辑 PDF | 后端 400 返回 | "暂不支持扫描版 PDF，请上传可编辑的 PDF 文件" |
| 填写阶段 - AI 调用失败 | 回到 input 步骤 + 显示 error | "AI 服务暂时不可用，请稍后重试" |
| 填写阶段 - 超时 (>60s) | 回到 input 步骤 + 显示 error | "处理超时，请稍后重试" |
| 填写阶段 - 格式异常 | 回到 input 步骤 + 显示 error | "填写失败，请检查输入信息或稍后重试" |
| 下载阶段 - Blob 创建失败 | try-catch + alert | "下载失败，请重试" |

错误消息统一从后端响应的 `detail` 字段提取（已在 `api.ts` 拦截器中处理）。

#### 6. 移动端适配

- 所有组件已使用 Tailwind 响应式类，本版本无需新增断点逻辑
- 关键确认项：
  - `InfoInput` 的 `<Textarea>` 在移动端有足够高度（最少 4 行）
  - "开始填写"按钮为 `w-full`
  - `LoadingOverlay` 在移动端正确居中
  - 步骤指示器在小屏下不换行（已用 `grid-cols-3` 保证）

### ✅ 预期实现内容

**前端新增**
- `frontend/src/hooks/useSmartFill.ts` - 全流程状态机 Hook
- 步骤指示器改为动态高亮 + 已完成勾选

**前端修改**
- `frontend/src/App.tsx` - 重构为 3 步流程（主要改动文件）
- `frontend/src/components/features/DownloadButton.tsx` - 微调（如需）
- `frontend/src/App.tsx` 版本号更新为 `v0.1.0-dev.4`

**后端修改**
- `backend/app/config.py` - 版本号更新为 `0.1.0-dev.4`

**无需新增后端 API** — 所有接口（`/upload`、`/extract-fields`、`/fill`）已在 v1-v3 完成。

### 📂 涉及文件

**新增文件**
- `frontend/src/hooks/useSmartFill.ts` - 全流程状态管理 Hook

**前端修改**
- `frontend/src/App.tsx` - 重构为完整 3 步流程（核心改动）
- `frontend/src/components/features/DownloadButton.tsx` - 接入实际下载逻辑（如需微调 props）

**后端修改**
- `backend/app/config.py` - 版本号

### ⚠️ 注意事项

1. **不新增组件**：`InfoInput`、`DownloadButton`、`LoadingOverlay` 已在前序版本创建完毕，本版本只需导入和组装
2. **不新增 API**：`fillPdfWithAI()` 已在 v3 的 `api.ts` 中实现，本版本只需在 Hook 中调用
3. **状态由数据驱动**：`currentStep` 不需要 `setState` 手动切换，而是由 `fileUpload.status`、`filledPdfBlob`、`isFilling` 等底层状态推导
4. **`/extract-fields` 不直接调用**：AI 填写接口 `/fill` 内部已包含字段提取逻辑，前端无需单独调用 `extractFields()`
5. **PRD 3.2 步骤 7 偏差**：PRD 写"自动下载"，但与用户确认后改为"用户点击下载"，符合更好的 UX 实践
