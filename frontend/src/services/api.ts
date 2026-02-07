import axios, { AxiosError } from 'axios';
import type { UploadResponse, ApiError } from '../types';

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

export default apiClient;
