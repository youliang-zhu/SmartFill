"""
文件处理工具
"""
import os
import uuid
from pathlib import Path
from typing import Optional
import shutil

from app.config import get_settings


class FileStorage:
    """文件存储抽象基类"""
    
    def save(self, content: bytes, filename: str) -> str:
        """保存文件，返回文件ID"""
        raise NotImplementedError
    
    def get_path(self, file_id: str) -> Optional[Path]:
        """获取文件路径"""
        raise NotImplementedError
    
    def delete(self, file_id: str) -> bool:
        """删除文件"""
        raise NotImplementedError
    
    def exists(self, file_id: str) -> bool:
        """检查文件是否存在"""
        raise NotImplementedError


class LocalStorage(FileStorage):
    """本地文件存储"""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_path = Path(self.settings.TEMP_DIR)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_file_dir(self, file_id: str) -> Path:
        """获取文件目录"""
        return self.base_path / file_id
    
    def save(self, content: bytes, filename: str) -> str:
        """
        保存文件到本地临时目录
        
        Args:
            content: 文件内容
            filename: 原始文件名
        
        Returns:
            文件ID
        """
        # 生成唯一文件ID
        file_id = str(uuid.uuid4())
        
        # 创建文件目录
        file_dir = self._get_file_dir(file_id)
        file_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存文件
        file_path = file_dir / filename
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 保存元数据
        meta_path = file_dir / "meta.txt"
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(filename)
        
        return file_id
    
    def get_path(self, file_id: str) -> Optional[Path]:
        """获取文件路径"""
        file_dir = self._get_file_dir(file_id)
        
        if not file_dir.exists():
            return None
        
        # 读取原始文件名
        meta_path = file_dir / "meta.txt"
        if not meta_path.exists():
            return None
        
        with open(meta_path, "r", encoding="utf-8") as f:
            filename = f.read().strip()
        
        file_path = file_dir / filename
        if not file_path.exists():
            return None
        
        return file_path
    
    def get_filename(self, file_id: str) -> Optional[str]:
        """获取原始文件名"""
        file_dir = self._get_file_dir(file_id)
        meta_path = file_dir / "meta.txt"
        
        if not meta_path.exists():
            return None
        
        with open(meta_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    
    def delete(self, file_id: str) -> bool:
        """删除文件及其目录"""
        file_dir = self._get_file_dir(file_id)
        
        if not file_dir.exists():
            return False
        
        try:
            shutil.rmtree(file_dir)
            return True
        except Exception:
            return False
    
    def exists(self, file_id: str) -> bool:
        """检查文件是否存在"""
        return self.get_path(file_id) is not None


# 创建全局存储实例
storage = LocalStorage()


def get_storage() -> LocalStorage:
    """获取存储实例"""
    return storage
