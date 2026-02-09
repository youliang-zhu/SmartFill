import axios, { AxiosError } from 'axios';
import type { UploadResponse, ExtractFieldsResponse, ApiError } from '../types';

// API 基础 URL
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// 创建 axios 实例
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000, // 60秒超时
});

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    // 统一错误处理
    const message = error.response?.data?.detail || error.message || '请求失败，请稍后重试';
    return Promise.reject(new Error(message));
  }
);

/**
 * 上传 PDF 文件
 * @param file PDF 文件
 * @param onUploadProgress 上传进度回调
 * @returns 上传响应
 */
export async function uploadPdf(
  file: File,
  onUploadProgress?: (progress: number) => void
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post<UploadResponse>('/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      if (progressEvent.total && onUploadProgress) {
        const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onUploadProgress(progress);
      }
    },
  });

  return response.data;
}

/**
 * 健康检查
 * @returns 健康状态
 */
export async function healthCheck(): Promise<{ status: string }> {
  const response = await apiClient.get('/health');
  return response.data;
}

/**
 * 提取 PDF 表单字段
 * @param fileId 文件 ID（上传后返回）
 * @returns 字段提取结果
 */
export async function extractFields(fileId: string): Promise<ExtractFieldsResponse> {
  const response = await apiClient.post<ExtractFieldsResponse>('/extract-fields', {
    file_id: fileId,
  });
  return response.data;
}

/**
 * 填写 PDF 表单（手动字段映射版，用于调试）
 * @param fileId 文件 ID
 * @param fieldValues 字段名到值的映射
 * @returns 填好的 PDF 文件 Blob
 */
export async function fillPdfByFields(
  fileId: string,
  fieldValues: Record<string, string>
): Promise<Blob> {
  const response = await apiClient.post('/fill-by-fields', {
    file_id: fileId,
    field_values: fieldValues,
  }, {
    responseType: 'blob',
  });
  return response.data;
}

/**
 * AI 智能填写 PDF 表单
 * @param fileId 文件 ID
 * @param userInfo 用户自然语言输入的信息
 * @returns 填好的 PDF 文件 Blob
 */
export async function fillPdfWithAI(
  fileId: string,
  userInfo: string
): Promise<Blob> {
  const response = await apiClient.post('/fill', {
    file_id: fileId,
    user_info: userInfo,
  }, {
    responseType: 'blob',
  });
  return response.data;
}

export default apiClient;
