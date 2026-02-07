"""
SmartFill 后端入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, ensure_temp_dir
from app.routers import pdf

# 获取配置
settings = get_settings()

# 创建应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI驱动的PDF自动填写工具",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(pdf.router, prefix=settings.API_V1_PREFIX)


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    # 确保临时目录存在
    ensure_temp_dir()
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} started")
    print(f"📁 Temp directory: {settings.TEMP_DIR}")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    print(f"👋 {settings.APP_NAME} shutting down")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
