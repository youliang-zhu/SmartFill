import React from 'react';
import { Textarea } from '../common/Input';

interface InfoInputProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string;
}

export function InfoInput({ value, onChange, disabled, error }: InfoInputProps) {
  const placeholder = `请输入您的个人信息，例如：

姓名：张三
身份证：110101199001011234
电话：138-0013-8000
地址：北京市朝阳区...
邮箱：zhangsan@example.com

您可以用任何格式输入，AI 会自动识别并匹配表单字段。`;

  return (
    <div className="w-full animate-fade-in-up animate-delay-200">
      <Textarea
        label="填写信息"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        error={error}
        maxLength={2000}
        showCount
        className="font-body"
      />
      <p className="mt-2 text-xs text-neutral-400">
        提示：无需按特定格式，用自然语言描述即可
      </p>
    </div>
  );
}
