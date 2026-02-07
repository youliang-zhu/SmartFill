"""
Pydantic 数据模型定义
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class UploadResponse(BaseModel):
    """文件上传响应"""
    file_id: str = Field(..., description="文件唯一标识")
    filename: str = Field(..., description="原始文件名")
    message: str = Field(default="文件上传成功", description="响应消息")


class ExtractFieldsRequest(BaseModel):
    """提取字段请求"""
    file_id: str = Field(..., description="文件唯一标识")


class ExtractFieldsResponse(BaseModel):
    """提取字段响应"""
    file_id: str = Field(..., description="文件唯一标识")
    fields: List[str] = Field(default=[], description="表单字段列表")


class FillRequest(BaseModel):
    """填写请求"""
    file_id: str = Field(..., description="文件唯一标识")
    user_info: str = Field(..., description="用户输入的信息")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(default="ok", description="服务状态")


class ErrorResponse(BaseModel):
    """错误响应"""
    detail: str = Field(..., description="错误详情")
