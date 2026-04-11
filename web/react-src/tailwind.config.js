/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        'oxford-blue': '#002147',
        'glacier-blue': '#4A90D9',
        'sandstone': '#C9B99A',
        'overlap-highlight': 'rgba(74, 144, 217, 0.08)',
      },
      fontFamily: {
        sans: ['Arial', 'Helvetica', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
