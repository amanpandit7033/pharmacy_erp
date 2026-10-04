/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
    './*/templates/**/*.html',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#edf0fc',
          100: '#dce1f9',
          200: '#c1ccf5',
          300: '#99acee',
          400: '#5a72df',
          500: '#283891', // Azmobia signature deep navy / cobalt blue
          600: '#1f2d7a',
          700: '#182260',
          800: '#121a48',
          900: '#0e1438',
        },
        azgreen: {
          50: '#effaf1',
          100: '#d7f4dc',
          200: '#b2e8bb',
          300: '#83d793',
          400: '#55c46b',
          500: '#39b54a', // Azmobia signal leaf green
          600: '#2fa03e',
          700: '#248232',
          800: '#1c6628',
          900: '#154e1e',
        },
        blue: {
          50: '#edf0fc',
          100: '#dce1f9',
          200: '#c1ccf5',
          300: '#99acee',
          400: '#5a72df',
          500: '#283891', // Azmobia signature blue
          600: '#1f2d7a',
          700: '#182260',
          800: '#121a48',
          900: '#0e1438',
        },
        surface: {
          DEFAULT: '#ffffff',
          muted: '#f4f7fb',
          subtle: '#f8fafc',
        }
      },
      boxShadow: {
        'card': '0 2px 14px 0 rgba(15, 23, 42, 0.04)',
        'card-hover': '0 8px 24px -4px rgba(15, 23, 42, 0.08)',
        'dropdown': '0 10px 30px -5px rgba(15, 23, 42, 0.08)',
      }
    }
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
}
