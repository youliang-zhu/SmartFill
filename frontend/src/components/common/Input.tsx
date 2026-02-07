import React from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

export function Input({
  label,
  error,
  helperText,
  className = '',
  id,
  ...props
}: InputProps) {
  const inputId = id || label?.toLowerCase().replace(/\s/g, '-');

  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="block text-sm font-medium text-neutral-700 mb-2"
        >
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={`
          w-full px-4 py-3
          bg-white
          border-2 border-neutral-200
          rounded-xl
          font-body text-neutral-900
          placeholder:text-neutral-400
          transition-all duration-200
          focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20
          hover:border-neutral-300
          disabled:bg-neutral-100 disabled:cursor-not-allowed
          ${error ? 'border-error focus:border-error focus:ring-error/20' : ''}
          ${className}
        `}
        {...props}
      />
      {(error || helperText) && (
        <p
          className={`mt-2 text-sm ${
            error ? 'text-error' : 'text-neutral-500'
          }`}
        >
          {error || helperText}
        </p>
      )}
    </div>
  );
}

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  helperText?: string;
  maxLength?: number;
  showCount?: boolean;
}

export function Textarea({
  label,
  error,
  helperText,
  maxLength,
  showCount = false,
  className = '',
  id,
  value,
  ...props
}: TextareaProps) {
  const inputId = id || label?.toLowerCase().replace(/\s/g, '-');
  const currentLength = typeof value === 'string' ? value.length : 0;
  const isOverLimit = maxLength && currentLength > maxLength;

  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="block text-sm font-medium text-neutral-700 mb-2"
        >
          {label}
        </label>
      )}
      <div className="relative">
        <textarea
          id={inputId}
          value={value}
          className={`
            w-full px-4 py-3
            min-h-[160px] md:min-h-[200px]
            bg-white
            border-2 border-neutral-200
            rounded-xl
            font-body text-neutral-900
            placeholder:text-neutral-400
            transition-all duration-200
            focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 focus:scale-[1.01]
            hover:border-neutral-300
            disabled:bg-neutral-100 disabled:cursor-not-allowed
            resize-y
            ${error || isOverLimit ? 'border-error focus:border-error focus:ring-error/20' : ''}
            ${className}
          `}
          {...props}
        />
        {showCount && maxLength && (
          <span
            className={`absolute bottom-3 right-3 text-xs ${
              isOverLimit ? 'text-error' : 'text-neutral-400'
            }`}
          >
            {currentLength}/{maxLength}
          </span>
        )}
      </div>
      {(error || helperText) && (
        <p
          className={`mt-2 text-sm ${
            error ? 'text-error' : 'text-neutral-500'
          }`}
        >
          {error || helperText}
        </p>
      )}
    </div>
  );
}
