"""
Pydantic 数据模型定义
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class UploadResponse(BaseModel):
    """文件上传响应"""
    file_id: str = Field(..., description="文件唯一标识")
    filename: str = Field(..., description="原始文件名")
    message: str = Field(default="文件上传成功", description="响应消息")


class ExtractFieldsRequest(BaseModel):
    """提取字段请求"""
    file_id: str = Field(..., description="文件唯一标识")


class FieldInfo(BaseModel):
    """表单字段详细信息"""
    name: str = Field(..., description="字段名称")
    field_type: str = Field(default="text", description="字段类型: text, checkbox, dropdown, radio, signature 等")
    default_value: Optional[str] = Field(default=None, description="字段默认值/已有值")


class ExtractFieldsResponse(BaseModel):
    """提取字段响应"""
    file_id: str = Field(..., description="文件唯一标识")
    fields: List[str] = Field(default=[], description="表单字段名称列表")
    field_details: List[FieldInfo] = Field(default=[], description="字段详细信息列表")
    field_count: int = Field(default=0, description="字段总数")
    message: str = Field(default="字段提取成功", description="响应消息")


class FillRequest(BaseModel):
    """AI 填写请求（预留，v0.1.0-dev.3 实现）"""
    file_id: str = Field(..., description="文件唯一标识")
    user_info: str = Field(..., description="用户输入的自然语言信息")


class FillByFieldsRequest(BaseModel):
    """手动字段映射填写请求"""
    file_id: str = Field(..., description="文件唯一标识")
    field_values: Dict[str, str] = Field(..., description="字段名称到值的映射")


class FillResult(BaseModel):
    """填写结果详情（用于日志和调试，不直接返回给前端）"""
    filled_fields: List[str] = Field(default=[], description="成功填写的字段")
    skipped_fields: List[str] = Field(default=[], description="跳过的字段（PDF 中不存在）")
    total_filled: int = Field(default=0, description="成功填写字段数")
    total_skipped: int = Field(default=0, description="跳过字段数")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(default="ok", description="服务状态")


class ErrorResponse(BaseModel):
    """错误响应"""
    detail: str = Field(..., description="错误详情")
