"""
SmartFill 后端配置管理
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

# 项目根目录（backend 的上一级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用信息
    APP_NAME: str = "SmartFill"
    APP_VERSION: str = "0.1.0-dev.1"
    DEBUG: bool = False
    
    # API 配置
    API_V1_PREFIX: str = "/api/v1"
    
    # 文件配置
    MAX_FILE_SIZE_MB: int = 10
    TEMP_DIR: str = str(_PROJECT_ROOT / ".tempdocs")  # 默认: 项目根目录下的 .tempdocs
    ALLOWED_EXTENSIONS: set = {".pdf"}
    
    # AI 配置（预留）
    QWEN_API_KEY: str = ""
    QWEN_MODEL: str = "qwen-plus"
    
    # CORS 配置
    CORS_ORIGINS: str = ""  # 必须在 .env 中配置，多个地址用逗号分隔
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
    
    @property
    def max_file_size_bytes(self) -> int:
        """获取最大文件大小（字节）"""
        return self.MAX_FILE_SIZE_MB * 1024 * 1024
    
    @property
    def cors_origins_list(self) -> list:
        """获取 CORS 源列表"""
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


# 模块级 Settings 实例
settings = Settings()


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return settings


# 确保临时目录存在
def ensure_temp_dir():
    """确保临时目录存在"""
    s = get_settings()
    temp_path = Path(s.TEMP_DIR)
    
    # 如果是相对路径，转换为绝对路径
    if not temp_path.is_absolute():
        temp_path = temp_path.resolve()
    
    temp_path.mkdir(parents=True, exist_ok=True)
    return temp_path
