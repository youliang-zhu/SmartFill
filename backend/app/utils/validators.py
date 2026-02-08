"""
验证工具函数
"""
from pathlib import Path
from fastapi import UploadFile, HTTPException, status

from app.config import get_settings


def validate_pdf_file(file: UploadFile) -> None:
    """
    验证上传的文件是否为有效的 PDF
    
    Args:
        file: 上传的文件对象
    
    Raises:
        HTTPException: 如果文件无效
    """
    settings = get_settings()
    
    # 检查文件名
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名不能为空"
        )
    
    # 检查文件扩展名
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅支持以下格式: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )
    
    # 检查 MIME 类型
    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 PDF 格式文件"
        )


def validate_file_size(content: bytes) -> None:
    """
    验证文件大小
    
    Args:
        content: 文件内容
    
    Raises:
        HTTPException: 如果文件过大
    """
    settings = get_settings()
    
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小不能超过 {settings.MAX_FILE_SIZE_MB}MB"
        )


def validate_pdf_header(content: bytes) -> None:
    """
    验证 PDF 文件头
    
    Args:
        content: 文件内容
    
    Raises:
        HTTPException: 如果不是有效的 PDF 文件
    """
    # PDF 文件应该以 %PDF- 开头
    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的 PDF 文件"
        )


def validate_file_exists(file_id: str) -> Path:
    """
    验证 file_id 对应的文件是否存在，存在则返回文件路径
    
    Args:
        file_id: 文件唯一标识
    
    Returns:
        文件的绝对路径
    
    Raises:
        HTTPException: 如果文件不存在或已过期
    """
    from app.utils.file_handler import get_storage
    
    storage = get_storage()
    
    if not storage.exists(file_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在或已过期"
        )
    
    file_path = storage.get_path(file_id)
    if file_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在或已过期"
        )
    
    return file_path
