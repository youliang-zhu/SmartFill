"""
PDF 相关 API 路由
"""
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import FileResponse

from app.models.schemas import (
    UploadResponse,
    HealthResponse,
    ExtractFieldsRequest,
    ExtractFieldsResponse,
    FillRequest,
    FillByFieldsRequest,
)
from app.utils.file_handler import get_storage
from app.utils.validators import (
    validate_pdf_file,
    validate_file_size,
    validate_pdf_header,
    validate_file_exists,
)
from app.services.pdf_classifier import get_pdf_classifier
from app.services.pdf_pipeline_dispatcher import get_pdf_pipeline_dispatcher

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

    # 上传阶段类型校验：当前仅允许 fillable(AcroForm)
    pdf_path = storage.get_path(file_id)
    if pdf_path is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存文件后无法读取，请稍后重试"
        )

    classifier = get_pdf_classifier()
    try:
        pdf_type = classifier.classify(pdf_path)
    except PermissionError:
        storage.delete(file_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF 文件被密码保护，无法读取"
        )
    except ValueError:
        storage.delete(file_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="无法识别 PDF 类型，请确认这是一个标准 PDF"
        )

    if pdf_type != "fillable":
        storage.delete(file_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"暂不支持 {pdf_type} 类型 PDF，请上传 AcroForm 可编辑 PDF"
        )
    
    return UploadResponse(
        file_id=file_id,
        filename=file.filename,
        message="文件上传成功"
    )


@router.post("/extract-fields", response_model=ExtractFieldsResponse)
async def extract_fields(request: ExtractFieldsRequest):
    """
    提取 PDF 表单字段
    
    根据文件 ID 读取已上传的 PDF，提取所有表单字段信息。
    
    - **file_id**: 之前上传返回的文件唯一标识
    
    返回:
    - **fields**: 字段名称列表
    - **field_details**: 字段详细信息（名称、类型、默认值）
    - **field_count**: 字段总数
    """
    # 验证文件是否存在
    pdf_path = validate_file_exists(request.file_id)
    dispatcher = get_pdf_pipeline_dispatcher()
    
    # 提取字段名称列表
    try:
        field_names, field_details = dispatcher.extract_fields(pdf_path)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF 文件被密码保护，无法读取"
        )
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="无法识别表单字段，请确认这是一个标准 PDF"
        )
    
    return ExtractFieldsResponse(
        file_id=request.file_id,
        fields=field_names,
        field_details=field_details,
        field_count=len(field_names),
        message="字段提取成功"
    )


@router.post("/fill")
async def fill_pdf_with_ai(request: FillRequest):
    """
    AI 智能填写 PDF 表单
    
    接收用户自然语言输入，通过 AI 语义匹配表单字段并自动填写。
    
    - **file_id**: 之前上传返回的文件唯一标识
    - **user_info**: 用户自然语言输入的信息（如"我叫张三，电话13800138000"）
    
    返回:
    - 填好的 PDF 文件流（application/pdf）
    """
    # 验证文件是否存在
    pdf_path = validate_file_exists(request.file_id)
    
    storage = get_storage()
    dispatcher = get_pdf_pipeline_dispatcher()

    # 1. 分发到对应类型 pipeline（fillable/native）
    # 2. pipeline 内部完成字段提取 + AI 匹配 + 填写
    original_filename = storage.get_filename(request.file_id) or "document.pdf"
    stem = Path(original_filename).stem
    output_filename = f"{stem}_filled.pdf"
    output_path = pdf_path.parent / output_filename

    try:
        result = await dispatcher.fill_with_ai(
            pdf_path=pdf_path,
            user_info=request.user_info,
            output_path=output_path,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF 文件被密码保护，无法填写"
        )
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="处理超时，请稍后重试"
        )
    except ConnectionError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 服务暂时不可用，请稍后重试"
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="填写失败，请检查输入信息或稍后重试"
        )
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except (ValueError, IOError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="填写失败，请检查输入信息或稍后重试"
        )
    
    # 检查输出文件是否生成
    if not output_path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="填写失败，请检查输入信息或稍后重试"
        )
    
    return FileResponse(
        path=str(output_path),
        media_type="application/pdf",
        filename=output_filename,
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"'
        }
    )


@router.post("/fill-by-fields")
async def fill_pdf_by_fields(request: FillByFieldsRequest):
    """
    填写 PDF 表单（手动字段映射版，用于调试）
    
    直接传入字段名→值映射，填写 PDF 表单并返回填好的文件。
    此接口不经过 AI，主要用于调试和精确控制填写内容。
    
    - **file_id**: 之前上传返回的文件唯一标识
    - **field_values**: 字段名称到值的映射，如 {"姓名": "张三", "电话": "13800138000"}
    
    返回:
    - 填好的 PDF 文件流（application/pdf）
    """
    # 验证文件是否存在
    pdf_path = validate_file_exists(request.file_id)
    
    storage = get_storage()
    dispatcher = get_pdf_pipeline_dispatcher()
    
    # 生成输出文件名：原文件名_filled.pdf
    original_filename = storage.get_filename(request.file_id) or "document.pdf"
    stem = Path(original_filename).stem
    output_filename = f"{stem}_filled.pdf"
    
    # 输出路径放在同一个 file_id 目录下
    output_path = pdf_path.parent / output_filename
    
    # 填写表单
    try:
        result = dispatcher.fill_by_fields(
            pdf_path=pdf_path,
            field_values=request.field_values,
            output_path=output_path,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF 文件被密码保护，无法填写"
        )
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"填写失败，请检查输入信息或稍后重试: {str(e)}"
        )
    except IOError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"填写失败，请检查输入信息或稍后重试: {str(e)}"
        )
    
    # 检查输出文件是否生成
    if not output_path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="填写失败，请检查输入信息或稍后重试"
        )
    
    # 返回填好的 PDF 文件流
    return FileResponse(
        path=str(output_path),
        media_type="application/pdf",
        filename=output_filename,
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"'
        }
    )
