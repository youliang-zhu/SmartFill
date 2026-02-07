import React from 'react';
import { Download, CheckCircle } from 'lucide-react';
import { Button } from '../common/Button';

interface DownloadButtonProps {
  onClick: () => void;
  isReady: boolean;
  isLoading?: boolean;
  fileName?: string;
}

export function DownloadButton({
  onClick,
  isReady,
  isLoading = false,
  fileName,
}: DownloadButtonProps) {
  if (!isReady) {
    return null;
  }

  return (
    <div className="w-full animate-fade-in-up animate-delay-300">
      <Button
        size="lg"
        onClick={onClick}
        isLoading={isLoading}
        leftIcon={isLoading ? undefined : <CheckCircle className="w-5 h-5" />}
        rightIcon={isLoading ? undefined : <Download className="w-5 h-5" />}
        className="w-full bg-accent hover:bg-accent-dark"
      >
        {isLoading ? '生成中...' : '生成成功！点击下载'}
      </Button>
      {fileName && (
        <p className="text-center text-sm text-neutral-500 mt-2 font-mono">
          {fileName}
        </p>
      )}
    </div>
  );
}
