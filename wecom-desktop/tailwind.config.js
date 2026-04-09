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

