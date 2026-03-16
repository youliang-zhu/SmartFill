"""
日志配置模块

将 AI 服务的输入输出记录到日志文件，便于调试和问题追踪。
日志文件按天轮转，保留最近 7 天。
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.config import get_settings 

# 日志目录：项目根目录/logs/
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logging():
    """
    配置日志系统
    
    - AI 服务日志 → logs/ai_service.log（按天轮转）
    - 同时输出到终端（仅 WARNING 以上）
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # AI 服务专用 logger
    ai_logger = logging.getLogger("app.services.fillable.ai_service")
    ai_logger.setLevel(logging.DEBUG)
    
    # 避免重复添加 handler（热重载场景）
    if ai_logger.handlers:
        return
    
    # 文件 Handler：记录所有级别，按天轮转，保留 7 天
    file_handler = TimedRotatingFileHandler(
        filename=str(_LOG_DIR / "ai_service.log"),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    ai_logger.addHandler(file_handler)
    
    # 终端 Handler：仅输出 WARNING 以上（避免终端刷屏）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    ai_logger.addHandler(console_handler)
