import { useState, useCallback, useMemo } from 'react';
import { useFileUpload } from './useFileUpload';
import { fillPdfWithAI } from '../services/api';
import { generateFileName } from '../utils/helpers';

/**
 * 全流程步骤类型
 * - upload: 上传文件阶段
 * - input: 输入信息阶段
 * - filling: AI 正在填写
 * - download: 下载结果阶段
 */
export type FlowStep = 'upload' | 'input' | 'filling' | 'download';

export interface UseSmartFillReturn {
  // 当前步骤（由底层状态自动推导）
  currentStep: FlowStep;

  // Step 1: 上传相关（复用 useFileUpload）
  fileUpload: ReturnType<typeof useFileUpload>;

  // Step 2: 信息输入
  userInfo: string;
  setUserInfo: (value: string) => void;

  // Step 3: AI 填写 & 下载
  filledPdfBlob: Blob | null;
  filledFileName: string;
  fillError: string | null;
  isFilling: boolean;

  // 操作
  handleStartFill: () => Promise<void>;
  handleDownload: () => void;
  handleReset: () => void;
}

/**
 * SmartFill 全流程状态管理 Hook
 * 
 * 状态流转逻辑：
 * upload(idle) → upload(uploading) → upload(success) → input → filling → download
 *                    ↓                                           ↓
 *               upload(error)                              fillError → input (允许修改信息重试)
 * 
 * 任意状态 → handleReset() → upload(idle)
 */
export function useSmartFill(): UseSmartFillReturn {
  // Step 1: 复用 useFileUpload
  const fileUpload = useFileUpload({
    maxSizeMB: 10,
  });

  // Step 2: 用户信息输入
  const [userInfo, setUserInfo] = useState<string>('');

  // Step 3: AI 填写状态
  const [filledPdfBlob, setFilledPdfBlob] = useState<Blob | null>(null);
  const [filledFileName, setFilledFileName] = useState<string>('');
  const [fillError, setFillError] = useState<string | null>(null);
  const [isFilling, setIsFilling] = useState<boolean>(false);

  /**
   * 当前步骤根据底层状态自动推导，无需手动 setState
   * - upload: fileUpload.status 为 idle / uploading / error
   * - input: 上传成功且未开始 AI 填写
   * - filling: AI 正在处理
   * - download: filledPdfBlob 非空
   */
  const currentStep = useMemo<FlowStep>(() => {
    // 如果已有填写结果，进入下载阶段
    if (filledPdfBlob) {
      return 'download';
    }

    // 如果 AI 正在填写
    if (isFilling) {
      return 'filling';
    }

    // 如果上传成功，进入输入信息阶段
    if (fileUpload.status === 'success' && fileUpload.fileId) {
      return 'input';
    }

    // 默认为上传阶段
    return 'upload';
  }, [filledPdfBlob, isFilling, fileUpload.status, fileUpload.fileId]);

  /**
   * 触发 AI 智能填写
   * 调用后端 /fill 接口，内部已包含字段提取逻辑
   */
  const handleStartFill = useCallback(async () => {
    if (!fileUpload.fileId || !userInfo.trim()) {
      return;
    }

    try {
      setIsFilling(true);
      setFillError(null);

      // 调用 AI 填写接口，返回填好的 PDF Blob
      const blob = await fillPdfWithAI(fileUpload.fileId, userInfo.trim());

      // 生成文件名：原文件名_filled.pdf
      const originalName = fileUpload.file?.name || 'document.pdf';
      const newFileName = generateFileName(originalName, '_filled');

      setFilledPdfBlob(blob);
      setFilledFileName(newFileName);
    } catch (err) {
      // 填写失败，回到 input 步骤，用户可修改信息重试
      const errorMessage = err instanceof Error ? err.message : '填写失败，请检查输入信息或稍后重试';
      setFillError(errorMessage);
    } finally {
      setIsFilling(false);
    }
  }, [fileUpload.fileId, fileUpload.file, userInfo]);

  /**
   * 触发文件下载
   * 使用 URL.createObjectURL 创建下载链接
   */
  const handleDownload = useCallback(() => {
    if (!filledPdfBlob) return;

    try {
      const url = URL.createObjectURL(filledPdfBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filledFileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      alert('下载失败，请重试');
    }
  }, [filledPdfBlob, filledFileName]);

  /**
   * 重置全部状态，回到第 1 步
   */
  const handleReset = useCallback(() => {
    // 重置上传状态
    fileUpload.reset();

    // 重置用户输入
    setUserInfo('');

    // 重置填写状态
    setFilledPdfBlob(null);
    setFilledFileName('');
    setFillError(null);
    setIsFilling(false);
  }, [fileUpload]);

  return {
    currentStep,
    fileUpload,
    userInfo,
    setUserInfo,
    filledPdfBlob,
    filledFileName,
    fillError,
    isFilling,
    handleStartFill,
    handleDownload,
    handleReset,
  };
}
