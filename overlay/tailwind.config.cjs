/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{ts,tsx,html}'],
  theme: {
    extend: {
      colors: {
        overlay: {
          bg: 'rgba(0, 0, 0, 0.85)',
          border: 'rgba(255, 255, 255, 0.1)',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'SF Mono', 'Menlo', 'monospace'],
      }
    },
  },
  plugins: [],
}
