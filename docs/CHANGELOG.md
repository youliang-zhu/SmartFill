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

## [Unreleased]
