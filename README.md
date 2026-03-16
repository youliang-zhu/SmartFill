# SmartFill

> AI 驱动的 PDF 自动填写工具

SmartFill 是一个帮助用户快速填写 PDF 表单的智能工具。只需上传 PDF 文件，输入个人信息，AI 就会自动识别表单字段并完成填写。

## ✨ 特性

- 📄 **智能识别** - 自动识别 PDF 表单中的字段
- 🤖 **AI 填写** - 利用 AI 将用户信息匹配到对应字段
- 📱 **响应式设计** - 完美支持移动端和桌面端
- 🔒 **隐私安全** - 文件处理完即删除，不存储用户数据

## 🚀 快速开始

### 环境要求

- Node.js 18+
- Python 3.10+
- pnpm / npm / yarn

### 后端启动

```bash
# 进入后端目录
cd backend

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 复制环境变量文件
cp .env.example .env

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

后端 API 文档: http://localhost:8000/docs

### 前端启动

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 复制环境变量文件
cp .env.example .env

# 启动开发服务器
npm run dev
```

前端页面: http://localhost:3000

开发端口约定（推荐）：
- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`
- 前端通过 Vite 代理访问后端：`/api/* -> http://localhost:8000`

## 📁 项目结构

```
SmartFill/
├── frontend/                 # 前端项目 (React + Vite)
│   ├── src/
│   │   ├── components/      # UI 组件
│   │   ├── hooks/           # 自定义 Hooks
│   │   ├── services/        # API 调用
│   │   ├── types/           # TypeScript 类型
│   │   └── utils/           # 工具函数
│   └── ...
│
├── backend/                  # 后端项目 (FastAPI)
│   ├── app/
│   │   ├── routers/         # API 路由
│   │   ├── services/        # 业务逻辑
│   │   ├── models/          # 数据模型
│   │   └── utils/           # 工具函数
│   └── ...
│
└── docs/                     # 文档
    ├── PRD.md               # 产品需求文档
    └── CHANGELOG.md         # 技术实现文档
```

## 📖 API 接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v1/health` | GET | 健康检查 |
| `/api/v1/upload` | POST | 上传 PDF 文件 |
| `/api/v1/extract-fields` | POST | 提取表单字段 (待实现) |
| `/api/v1/fill` | POST | AI 填写 PDF (待实现) |

## 🛠️ 技术栈

**前端**
- React 18
- TypeScript
- Vite
- Tailwind CSS
- Axios

**后端**
- FastAPI
- Python 3.10+
- pypdf
- 通义千问 (Qwen)

## 📝 版本历史

### v0.1.0-dev.1 (当前版本)
- ✅ 前后端基础框架搭建
- ✅ 文件上传功能
- ✅ 文件格式和大小验证
- ⏳ PDF 字段提取 (下一版本)
- ⏳ AI 智能填写 (下一版本)

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
