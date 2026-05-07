/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        wecom: {
          primary: '#1AAD19',
          secondary: '#07C160',
          dark: '#0D1117',
          darker: '#010409',
          surface: '#161B22',
          border: '#30363D',
          text: '#C9D1D9',
          muted: '#8B949E',
          accent: '#58A6FF',
        },
        // BOSS Zhipin recruitment palette
        // Designed for a sober, trustworthy feel suitable for HR / hiring
        // contexts. Keep contrast ratios AA-compliant against both light
        // and dark surfaces.
        boss: {
          primary: '#1F4E8C',     // deep indigo - primary actions
          'primary-soft': '#3169B0',
          secondary: '#0F2D52',   // headers and deep panels
          accent: '#C97E2B',      // amber - alerts, quotas
          'accent-soft': '#E0A961',
          success: '#2F8F5C',
          warning: '#D6A12C',
          danger: '#B8423C',
          dark: '#0F1521',
          darker: '#080C14',
          surface: '#161E2D',
          'surface-soft': '#1F2837',
          border: '#2A3346',
          text: '#E5E9F0',
          'text-muted': '#9AA5BA',
          highlight: '#FFD58A',
        },
        chart: {
          emerald: '#10B981',
          blue: '#3B82F6',
          violet: '#8B5CF6',
          amber: '#F59E0B',
          rose: '#F43F5E',
          cyan: '#06B6D4',
          pink: '#EC4899',
          lime: '#84CC16',
        }
      },
      fontFamily: {
        sans: ['JetBrains Mono', 'SF Mono', 'Menlo', 'monospace'],
        display: ['Space Grotesk', 'system-ui', 'sans-serif'],
        // Recruitment views use Inter for high-density text panels.
        body: ['Inter', 'PingFang SC', 'Noto Sans CJK SC', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'SF Mono', 'Menlo', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-up': 'slideUp 0.3s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
        'scale-in': 'scaleIn 0.3s ease-out',
        'spin-slow': 'spin 3s linear infinite',
        'bounce-soft': 'bounceSoft 2s ease-in-out infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        scaleIn: {
          '0%': { transform: 'scale(0.95)', opacity: '0' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        bounceSoft: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-5px)' },
        },
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(26, 173, 25, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(26, 173, 25, 0.4)' },
        },
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
        'mesh-gradient': 'linear-gradient(135deg, #0D1117 0%, #161B22 50%, #0D1117 100%)',
      },
      boxShadow: {
        'glow-green': '0 0 20px rgba(26, 173, 25, 0.3)',
        'glow-blue': '0 0 20px rgba(59, 130, 246, 0.3)',
        'glow-purple': '0 0 20px rgba(139, 92, 246, 0.3)',
        'inner-glow': 'inset 0 1px 0 0 rgba(255, 255, 255, 0.05)',
      },
    },
  },
  plugins: [],
}

