import React, { useCallback, useState, useRef } from 'react';
import { Upload, FileText, X, CheckCircle, AlertCircle } from 'lucide-react';
import { Button } from '../common/Button';
import { formatFileSize } from '../../utils/helpers';
import type { UploadStatus } from '../../types';

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  onUpload: () => void;
  file: File | null;
  status: UploadStatus;
  progress: number;
  error: string | null;
  onReset: () => void;
}

export function FileUpload({
  onFileSelect,
  onUpload,
  file,
  status,
  progress,
  error,
  onReset,
}: FileUploadProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 处理文件选择
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = e.target.files?.[0];
      if (selectedFile) {
        onFileSelect(selectedFile);
      }
    },
    [onFileSelect]
  );

  // 处理拖拽进入
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  // 处理拖拽离开
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  // 处理拖拽悬停
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  // 处理文件放下
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile) {
        onFileSelect(droppedFile);
      }
    },
    [onFileSelect]
  );

  // 点击上传区域
  const handleClick = useCallback(() => {
    if (status !== 'uploading') {
      fileInputRef.current?.click();
    }
  }, [status]);

  // 渲染上传区域内容
  const renderContent = () => {
    // 上传中状态
    if (status === 'uploading') {
      return (
        <div className="flex flex-col items-center gap-4">
          <div className="w-full max-w-xs">
            <div className="flex justify-between text-sm text-neutral-600 mb-2">
              <span>上传中...</span>
              <span>{progress}%</span>
            </div>
            <div className="h-2 bg-neutral-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-primary-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
          <p className="text-neutral-500 text-sm">{file?.name}</p>
        </div>
      );
    }

    // 上传成功状态
    if (status === 'success') {
      return (
        <div className="flex flex-col items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-success/10 flex items-center justify-center">
            <CheckCircle className="w-8 h-8 text-success" />
          </div>
          <div className="text-center">
            <p className="font-display font-semibold text-lg text-neutral-900">
              上传成功
            </p>
            <p className="text-neutral-500 text-sm mt-1">{file?.name}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onReset}>
            重新选择
          </Button>
        </div>
      );
    }

    // 错误状态
    if (status === 'error') {
      return (
        <div className="flex flex-col items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-error/10 flex items-center justify-center">
            <AlertCircle className="w-8 h-8 text-error" />
          </div>
          <div className="text-center">
            <p className="font-display font-semibold text-lg text-error">
              上传失败
            </p>
            <p className="text-neutral-500 text-sm mt-1">{error}</p>
          </div>
          <Button variant="secondary" size="sm" onClick={onReset}>
            重新选择
          </Button>
        </div>
      );
    }

    // 已选择文件状态
    if (file) {
      return (
        <div className="flex flex-col items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-primary-100 flex items-center justify-center">
            <FileText className="w-8 h-8 text-primary-600" />
          </div>
          <div className="text-center">
            <p className="font-display font-semibold text-lg text-neutral-900">
              {file.name}
            </p>
            <p className="text-neutral-500 text-sm mt-1">
              {formatFileSize(file.size)}
            </p>
          </div>
          <div className="flex gap-3">
            <Button variant="secondary" size="sm" onClick={onReset}>
              重新选择
            </Button>
            <Button size="sm" onClick={onUpload}>
              开始上传
            </Button>
          </div>
        </div>
      );
    }

    // 默认状态（等待上传）
    return (
      <div className="flex flex-col items-center gap-4">
        <div
          className={`w-16 h-16 rounded-full flex items-center justify-center transition-colors duration-200 ${
            isDragOver ? 'bg-primary-500 scale-110' : 'bg-neutral-200'
          }`}
        >
          <Upload
            className={`w-8 h-8 transition-colors duration-200 ${
              isDragOver ? 'text-white' : 'text-neutral-500'
            }`}
          />
        </div>
        <div className="text-center">
          <p className="font-display font-semibold text-xl text-neutral-900">
            {isDragOver ? '松开鼠标上传' : '上传 PDF 文件'}
          </p>
          <p className="text-neutral-500 text-sm mt-2">
            拖拽文件到这里，或点击选择文件
          </p>
          <p className="text-neutral-400 text-xs mt-1">
            支持 PDF 格式，最大 10MB
          </p>
        </div>
      </div>
    );
  };

  return (
    <div className="w-full">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,application/pdf"
        onChange={handleFileChange}
        className="hidden"
      />
      <div
        onClick={handleClick}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className={`
          relative w-full min-h-[300px] md:min-h-[400px]
          flex items-center justify-center
          border-2 border-dashed
          rounded-2xl
          transition-all duration-300 ease-out
          cursor-pointer
          ${
            isDragOver
              ? 'border-primary-500 bg-gradient-to-br from-primary-50 to-primary-100 scale-[1.02] shadow-lift'
              : status === 'error'
              ? 'border-error/50 bg-error/5'
              : status === 'success'
              ? 'border-success/50 bg-success/5'
              : file
              ? 'border-primary-300 bg-primary-50'
              : 'border-neutral-300 bg-white hover:border-primary-400 hover:bg-neutral-50'
          }
          ${status === 'uploading' ? 'pointer-events-none' : ''}
        `}
      >
        {renderContent()}
      </div>
    </div>
  );
}
