/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['Clash Display', 'General Sans', 'system-ui', 'sans-serif'],
        body: ['Satoshi', 'Switzer', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Courier New', 'monospace'],
      },
      colors: {
        // 主背景：米白色
        canvas: {
          DEFAULT: '#FAF8F5',
          dark: '#2C2A27',
        },
        // 主色：深橄榄绿
        primary: {
          50: '#F5F7F4',
          100: '#E8EDE6',
          200: '#D1DBC9',
          300: '#B3C5A8',
          400: '#8FA87A',
          500: '#6B8E5A',
          600: '#557246',
          700: '#435A37',
          800: '#37492E',
          900: '#2E3D27',
        },
        // 强调色：暖橙色
        accent: {
          DEFAULT: '#E87A42',
          light: '#F59D6C',
          dark: '#D66430',
        },
        // 中性色：暖灰色系统
        neutral: {
          50: '#F9F8F6',
          100: '#EAE8E4',
          200: '#D5D2CC',
          300: '#B8B4AC',
          400: '#8F8A80',
          500: '#6B6760',
          600: '#56524B',
          700: '#46423D',
          800: '#3A3733',
          900: '#2C2A27',
        },
        // 状态色
        success: '#6B8E5A',
        warning: '#E8A742',
        error: '#D64430',
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
        '30': '7.5rem',
      },
      boxShadow: {
        'soft': '0 2px 12px rgba(44, 42, 39, 0.06)',
        'lift': '0 4px 24px rgba(44, 42, 39, 0.12)',
        'float': '0 12px 48px rgba(44, 42, 39, 0.18)',
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.6s cubic-bezier(0.22, 1, 0.36, 1)',
        'bounce-dot': 'bounceDot 1.4s infinite ease-in-out both',
      },
      keyframes: {
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        bounceDot: {
          '0%, 80%, 100%': { transform: 'scale(0)' },
          '40%': { transform: 'scale(1)' },
        },
      },
    },
  },
  plugins: [],
}
