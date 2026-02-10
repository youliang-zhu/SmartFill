import { FileUpload } from './components/features/FileUpload';
import { InfoInput } from './components/features/InfoInput';
import { DownloadButton } from './components/features/DownloadButton';
import { LoadingOverlay } from './components/common/Loading';
import { Button } from './components/common/Button';
import { useSmartFill } from './hooks/useSmartFill';
import type { FlowStep } from './hooks/useSmartFill';
import { formatFileSize } from './utils/helpers';
import { FileText, CheckCircle, RotateCcw, Send, AlertCircle } from 'lucide-react';

/** Hero 副标题随步骤变化 */
const HERO_SUBTITLES: Record<FlowStep, string> = {
  upload: '上传表单，输入信息，AI 自动完成填写',
  input: '请输入需要填写的信息',
  filling: 'AI 正在处理您的表单...',
  download: '表单填写完成，请下载查看',
};

/** 步骤定义 */
const STEPS = [
  { step: 1, title: '上传文件', desc: 'PDF 表单' },
  { step: 2, title: '输入信息', desc: '自然语言' },
  { step: 3, title: '下载结果', desc: '填好的 PDF' },
] as const;

/** 获取步骤状态 */
function getStepStatus(stepNumber: number, currentStep: FlowStep): 'completed' | 'active' | 'pending' {
  const stepMap: Record<FlowStep, number> = {
    upload: 1,
    input: 2,
    filling: 2,
    download: 3,
  };
  const currentNum = stepMap[currentStep];

  if (stepNumber < currentNum) return 'completed';
  if (stepNumber === currentNum) return 'active';
  return 'pending';
}

function App() {
  const {
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
  } = useSmartFill();

  return (
    <div className="min-h-screen bg-canvas flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-canvas/80 backdrop-blur-md border-b border-neutral-200">
        <div className="max-w-2xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary-500 flex items-center justify-center">
              <FileText className="w-5 h-5 text-white" />
            </div>
            <h1 className="font-display font-bold text-xl text-neutral-900">
              SmartFill
            </h1>
          </div>
          <span className="text-xs text-neutral-400 font-mono">v0.1.0-dev.4</span>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-2xl mx-auto px-4 py-8 safe-area-bottom flex-1 w-full">
        {/* Hero Section */}
        <section className="text-center mb-6 animate-fade-in-up">
          <h2 className="font-display font-bold text-3xl md:text-4xl text-neutral-900 mb-3">
            PDF 智能填写
          </h2>
          <p className="text-neutral-500 text-lg transition-all duration-300">
            {HERO_SUBTITLES[currentStep]}
          </p>
        </section>

        {/* Steps Indicator - 动态步骤指示器 */}
        <section className="mb-8 animate-fade-in-up animate-delay-100">
          <div className="grid grid-cols-3 gap-4">
            {STEPS.map((item) => {
              const status = getStepStatus(item.step, currentStep);
              return (
                <div
                  key={item.step}
                  className={`text-center p-4 rounded-xl transition-all duration-300 ${
                    status === 'active'
                      ? 'bg-primary-50 border-2 border-primary-200'
                      : status === 'completed'
                      ? 'bg-success/5 border-2 border-success/30'
                      : 'bg-neutral-50 border-2 border-transparent'
                  }`}
                >
                  <div
                    className={`w-8 h-8 rounded-full mx-auto mb-2 flex items-center justify-center text-sm font-bold transition-all duration-300 ${
                      status === 'active'
                        ? 'bg-primary-500 text-white'
                        : status === 'completed'
                        ? 'bg-success text-white'
                        : 'bg-neutral-200 text-neutral-500'
                    }`}
                  >
                    {status === 'completed' ? (
                      <CheckCircle className="w-5 h-5" />
                    ) : (
                      item.step
                    )}
                  </div>
                  <p
                    className={`font-semibold text-sm ${
                      status === 'active'
                        ? 'text-primary-700'
                        : status === 'completed'
                        ? 'text-success'
                        : 'text-neutral-500'
                    }`}
                  >
                    {item.title}
                  </p>
                  <p className="text-xs text-neutral-400 mt-1">{item.desc}</p>
                </div>
              );
            })}
          </div>
        </section>

        {/* Main Content Area - 根据 currentStep 渲染不同内容 */}

        {/* Step 1: 上传文件 */}
        {currentStep === 'upload' && (
          <section className="mb-8 animate-fade-in-up animate-delay-200">
            <FileUpload
              onFileSelect={fileUpload.selectFile}
              onUpload={fileUpload.upload}
              file={fileUpload.file}
              status={fileUpload.status}
              progress={fileUpload.progress}
              error={fileUpload.error}
              onReset={fileUpload.reset}
            />
          </section>
        )}

        {/* Step 2: 输入信息 */}
        {currentStep === 'input' && (
          <section className="space-y-6 animate-fade-in-up animate-delay-200">
            {/* 上传成功摘要卡片 */}
            <div className="flex items-center gap-4 p-4 bg-success/5 border border-success/20 rounded-2xl">
              <div className="w-12 h-12 rounded-xl bg-success/10 flex items-center justify-center flex-shrink-0">
                <CheckCircle className="w-6 h-6 text-success" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-display font-semibold text-neutral-900 truncate">
                  {fileUpload.file?.name}
                </p>
                <p className="text-sm text-neutral-500">
                  {fileUpload.file ? formatFileSize(fileUpload.file.size) : ''} · 上传成功
                </p>
              </div>
            </div>

            {/* 填写错误提示 */}
            {fillError && (
              <div className="flex items-start gap-3 p-4 bg-error/5 border border-error/20 rounded-2xl animate-fade-in-up">
                <AlertCircle className="w-5 h-5 text-error flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-error font-semibold text-sm">填写失败</p>
                  <p className="text-neutral-600 text-sm mt-1">{fillError}</p>
                </div>
              </div>
            )}

            {/* 信息输入区 */}
            <InfoInput
              value={userInfo}
              onChange={setUserInfo}
              disabled={isFilling}
            />

            {/* 操作按钮 */}
            <div className="flex flex-col gap-3">
              <Button
                size="lg"
                onClick={handleStartFill}
                disabled={!userInfo.trim()}
                rightIcon={<Send className="w-5 h-5" />}
                className="w-full"
              >
                开始填写
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleReset}
                leftIcon={<RotateCcw className="w-4 h-4" />}
                className="mx-auto"
              >
                重新选择文件
              </Button>
            </div>
          </section>
        )}

        {/* Step 3b: 下载结果 */}
        {currentStep === 'download' && filledPdfBlob && (
          <section className="space-y-6 animate-fade-in-up animate-delay-200">
            {/* 成功提示区域 */}
            <div className="text-center p-8 bg-success/5 border border-success/20 rounded-2xl">
              <div className="w-16 h-16 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-4">
                <CheckCircle className="w-8 h-8 text-success" />
              </div>
              <h3 className="font-display font-bold text-2xl text-neutral-900 mb-2">
                填写完成！
              </h3>
              <p className="text-neutral-500">
                AI 已自动将您的信息填入表单，请下载查看
              </p>
            </div>

            {/* 下载按钮 */}
            <DownloadButton
              onClick={handleDownload}
              isReady={true}
              fileName={filledFileName}
            />

            {/* 重新开始按钮 */}
            <div className="text-center">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleReset}
                leftIcon={<RotateCcw className="w-4 h-4" />}
              >
                重新开始
              </Button>
            </div>
          </section>
        )}
      </main>

      {/* Loading Overlay - AI 填写中 */}
      <LoadingOverlay isVisible={isFilling} text="AI 正在填写表单..." />

      {/* Footer */}
      <footer className="border-t border-neutral-200">
        <div className="max-w-2xl mx-auto px-4 py-6 text-center text-sm text-neutral-400">
          <p>SmartFill - AI 驱动的 PDF 自动填写工具</p>
          <p className="mt-1">文件处理完成后自动删除，不存储任何用户数据</p>
        </div>
      </footer>
    </div>
  );
}

export default App;
