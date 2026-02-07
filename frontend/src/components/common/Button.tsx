import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  children: React.ReactNode;
}

export function Button({
  variant = 'primary',
  size = 'md',
  isLoading = false,
  leftIcon,
  rightIcon,
  children,
  className = '',
  disabled,
  ...props
}: ButtonProps) {
  // 基础样式
  const baseStyles = `
    inline-flex items-center justify-center gap-2
    font-display font-semibold
    rounded-xl
    transition-all duration-300 ease-out
    focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500
    disabled:opacity-50 disabled:cursor-not-allowed
    active:scale-95
  `;

  // 变体样式
  const variantStyles = {
    primary: `
      bg-primary-600 text-white
      hover:bg-primary-700 hover:-translate-y-0.5 hover:shadow-lift
    `,
    secondary: `
      bg-transparent border-2 border-neutral-300 text-neutral-700
      hover:border-primary-500 hover:text-primary-700
    `,
    ghost: `
      bg-transparent text-neutral-600
      hover:text-primary-600
      relative after:absolute after:bottom-0 after:left-0 after:h-0.5 
      after:w-0 after:bg-primary-500 after:transition-all hover:after:w-full
    `,
  };

  // 尺寸样式
  const sizeStyles = {
    sm: 'px-4 py-2 text-sm h-10',
    md: 'px-6 py-3 text-base h-12',
    lg: 'px-8 py-4 text-lg h-14',
  };

  return (
    <button
      className={`
        ${baseStyles}
        ${variantStyles[variant]}
        ${sizeStyles[size]}
        ${className}
      `}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <>
          <LoadingDots />
          <span>处理中...</span>
        </>
      ) : (
        <>
          {leftIcon && <span className="flex-shrink-0">{leftIcon}</span>}
          <span>{children}</span>
          {rightIcon && <span className="flex-shrink-0">{rightIcon}</span>}
        </>
      )}
    </button>
  );
}

// Loading 动画组件
function LoadingDots() {
  return (
    <span className="flex gap-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-2 h-2 bg-current rounded-full animate-bounce-dot"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}
