"""
SmartFill 后端配置管理
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


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
    TEMP_DIR: str = str(Path.home() / ".smartfill" / "temp")
    ALLOWED_EXTENSIONS: set = {".pdf"}
    
    # AI 配置（预留）
    QWEN_API_KEY: str = ""
    QWEN_MODEL: str = "qwen-plus"
    
    # CORS 配置
    CORS_ORIGINS: list = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
    
    @property
    def max_file_size_bytes(self) -> int:
        """获取最大文件大小（字节）"""
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 确保临时目录存在
def ensure_temp_dir():
    """确保临时目录存在"""
    settings = get_settings()
    temp_path = Path(settings.TEMP_DIR)
    temp_path.mkdir(parents=True, exist_ok=True)
    return temp_path
