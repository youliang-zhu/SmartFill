// API 响应类型
export interface UploadResponse {
  file_id: string;
  filename: string;
  message: string;
}

// 表单字段详细信息
export interface FieldInfo {
  name: string;
  field_type: string; // text, checkbox, dropdown, radio, signature
  default_value: string | null;
}

export interface ExtractFieldsResponse {
  file_id: string;
  fields: string[];
  field_details: FieldInfo[];
  field_count: number;
  message: string;
}

// 手动字段映射填写请求
export interface FillByFieldsRequest {
  file_id: string;
  field_values: Record<string, string>;
}

// AI 智能填写请求
export interface FillRequest {
  file_id: string;
  user_info: string;
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
export interface PdfFileInfo {
  file: File;
  name: string;
  size: number;
  type: string;
}
