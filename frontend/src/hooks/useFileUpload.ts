import { useState, useCallback } from 'react';
import { uploadPdf } from '../services/api';
import { isPdfFile, isFileSizeValid } from '../utils/helpers';
import type { UploadStatus, UploadResponse } from '../types';

interface UseFileUploadOptions {
  maxSizeMB?: number;
  onSuccess?: (response: UploadResponse) => void;
  onError?: (error: string) => void;
}

interface UseFileUploadReturn {
  file: File | null;
  status: UploadStatus;
  progress: number;
  error: string | null;
  fileId: string | null;
  selectFile: (file: File) => void;
  upload: () => Promise<void>;
  reset: () => void;
}

export function useFileUpload(options: UseFileUploadOptions = {}): UseFileUploadReturn {
  const { maxSizeMB = 10, onSuccess, onError } = options;

  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [fileId, setFileId] = useState<string | null>(null);

  const selectFile = useCallback((selectedFile: File) => {
    // 重置状态
    setError(null);
    setProgress(0);
    setFileId(null);

    // 验证文件格式
    if (!isPdfFile(selectedFile)) {
      setError('仅支持 PDF 格式文件');
      setStatus('error');
      return;
    }

    // 验证文件大小
    if (!isFileSizeValid(selectedFile, maxSizeMB)) {
      setError(`文件大小不能超过 ${maxSizeMB}MB`);
      setStatus('error');
      return;
    }

    setFile(selectedFile);
    setStatus('idle');
  }, [maxSizeMB]);

  const upload = useCallback(async () => {
    if (!file) {
      setError('请先选择文件');
      return;
    }

    try {
      setStatus('uploading');
      setError(null);
      setProgress(0);

      const response = await uploadPdf(file, (prog) => {
        setProgress(prog);
      });

      setFileId(response.file_id);
      setStatus('success');
      onSuccess?.(response);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '上传失败，请稍后重试';
      setError(errorMessage);
      setStatus('error');
      onError?.(errorMessage);
    }
  }, [file, onSuccess, onError]);

  const reset = useCallback(() => {
    setFile(null);
    setStatus('idle');
    setProgress(0);
    setError(null);
    setFileId(null);
  }, []);

  return {
    file,
    status,
    progress,
    error,
    fileId,
    selectFile,
    upload,
    reset,
  };
}
