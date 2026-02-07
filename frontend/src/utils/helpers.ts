/**
 * 格式化文件大小
 * @param bytes 文件大小（字节）
 * @returns 格式化后的字符串
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * 验证文件是否为 PDF
 * @param file 文件对象
 * @returns 是否为 PDF
 */
export function isPdfFile(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
}

/**
 * 验证文件大小是否在限制内
 * @param file 文件对象
 * @param maxSizeMB 最大大小（MB）
 * @returns 是否在限制内
 */
export function isFileSizeValid(file: File, maxSizeMB: number = 10): boolean {
  const maxBytes = maxSizeMB * 1024 * 1024;
  return file.size <= maxBytes;
}

/**
 * 生成带时间戳的文件名
 * @param originalName 原始文件名
 * @param suffix 后缀（如 _filled）
 * @returns 新文件名
 */
export function generateFileName(originalName: string, suffix: string = '_filled'): string {
  const lastDot = originalName.lastIndexOf('.');
  if (lastDot === -1) {
    return `${originalName}${suffix}`;
  }
  const name = originalName.substring(0, lastDot);
  const ext = originalName.substring(lastDot);
  return `${name}${suffix}${ext}`;
}

/**
 * 延迟函数
 * @param ms 毫秒数
 */
export function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
