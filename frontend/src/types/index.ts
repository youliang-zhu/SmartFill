// API 响应类型
export interface UploadResponse {
  file_id: string;
  filename: string;
  message: string;
}

export interface ExtractFieldsResponse {
  fields: string[];
  file_id: string;
}

export interface FillResponse {
  // 返回 PDF 文件流，前端处理为 Blob
  success: boolean;
  message?: string;
}

export interface HealthResponse {
  status: string;
}

// API 错误响应
export interface ApiError {
  detail: string;
}

// 文件上传状态
export type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';

// 文件信息
export interface FileInfo {
  file: File;
  name: string;
  size: number;
  type: string;
}
