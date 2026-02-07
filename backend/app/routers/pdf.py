"""
PDF 相关 API 路由
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, status

from app.models.schemas import UploadResponse, HealthResponse
from app.utils.file_handler import get_storage
from app.utils.validators import (
    validate_pdf_file,
    validate_file_size,
    validate_pdf_header,
)

router = APIRouter(tags=["PDF"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查接口
    
    用于检查服务是否正常运行
    """
    return HealthResponse(status="ok")


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """
    上传 PDF 文件
    
    接收 PDF 文件并存储到临时目录，返回文件 ID
    
    - **file**: PDF 文件（multipart/form-data）
    
    返回:
    - **file_id**: 文件唯一标识
    - **filename**: 原始文件名
    - **message**: 响应消息
    """
    # 验证文件格式
    validate_pdf_file(file)
    
    # 读取文件内容
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取文件失败: {str(e)}"
        )
    
    # 验证文件大小
    validate_file_size(content)
    
    # 验证 PDF 文件头
    validate_pdf_header(content)
    
    # 保存文件
    try:
        storage = get_storage()
        file_id = storage.save(content, file.filename)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存文件失败: {str(e)}"
        )
    
    return UploadResponse(
        file_id=file_id,
        filename=file.filename,
        message="文件上传成功"
    )
