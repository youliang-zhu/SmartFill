import { FileUpload } from './components/features/FileUpload';
import { useFileUpload } from './hooks/useFileUpload';
import { FileText } from 'lucide-react';

function App() {
  const {
    file,
    status,
    progress,
    error,
    fileId,
    selectFile,
    upload,
    reset,
  } = useFileUpload({
    maxSizeMB: 10,
    onSuccess: (response) => {
      console.log('Upload success:', response);
    },
    onError: (err) => {
      console.error('Upload error:', err);
    },
  });

  return (
    <div className="min-h-screen bg-canvas">
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
          <span className="text-xs text-neutral-400 font-mono">v0.1.0-dev</span>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-2xl mx-auto px-4 py-8 safe-area-bottom">
        {/* Hero Section */}
        <section className="text-center mb-8 animate-fade-in-up">
          <h2 className="font-display font-bold text-3xl md:text-4xl text-neutral-900 mb-3">
            PDF 智能填写
          </h2>
          <p className="text-neutral-500 text-lg">
            上传表单，输入信息，AI 自动完成填写
          </p>
        </section>

        {/* Upload Section */}
        <section className="mb-8 animate-fade-in-up animate-delay-100">
          <FileUpload
            onFileSelect={selectFile}
            onUpload={upload}
            file={file}
            status={status}
            progress={progress}
            error={error}
            onReset={reset}
          />
        </section>

        {/* Success Message */}
        {status === 'success' && fileId && (
          <section className="text-center p-6 bg-success/10 rounded-2xl animate-fade-in-up">
            <p className="text-success font-semibold">
              ✓ 文件上传成功
            </p>
            <p className="text-neutral-500 text-sm mt-2">
              文件 ID: <code className="font-mono bg-neutral-100 px-2 py-1 rounded">{fileId}</code>
            </p>
            <p className="text-neutral-400 text-xs mt-4">
              下一步功能（字段提取和 AI 填写）将在后续版本实现
            </p>
          </section>
        )}

        {/* Steps Indicator */}
        <section className="mt-12 pt-8 border-t border-neutral-200">
          <h3 className="font-display font-semibold text-sm text-neutral-400 uppercase tracking-wider mb-4">
            使用步骤
          </h3>
          <div className="grid grid-cols-3 gap-4">
            {[
              { step: 1, title: '上传文件', desc: 'PDF 表单', active: true },
              { step: 2, title: '输入信息', desc: '自然语言', active: false },
              { step: 3, title: '下载结果', desc: '填好的 PDF', active: false },
            ].map((item) => (
              <div
                key={item.step}
                className={`text-center p-4 rounded-xl transition-colors ${
                  item.active
                    ? 'bg-primary-50 border-2 border-primary-200'
                    : 'bg-neutral-50 border-2 border-transparent'
                }`}
              >
                <div
                  className={`w-8 h-8 rounded-full mx-auto mb-2 flex items-center justify-center text-sm font-bold ${
                    item.active
                      ? 'bg-primary-500 text-white'
                      : 'bg-neutral-200 text-neutral-500'
                  }`}
                >
                  {item.step}
                </div>
                <p
                  className={`font-semibold text-sm ${
                    item.active ? 'text-primary-700' : 'text-neutral-500'
                  }`}
                >
                  {item.title}
                </p>
                <p className="text-xs text-neutral-400 mt-1">{item.desc}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-neutral-200 mt-12">
        <div className="max-w-2xl mx-auto px-4 py-6 text-center text-sm text-neutral-400">
          <p>SmartFill - AI 驱动的 PDF 自动填写工具</p>
          <p className="mt-1">文件处理完成后自动删除，不存储任何用户数据</p>
        </div>
      </footer>
    </div>
  );
}

export default App;
