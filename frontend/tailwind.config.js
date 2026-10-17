/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // REFERENCE Official Brand Colors
        'REFERENCE-navy': '#003087',        // Primary - Navy Blue
        'REFERENCE-blue': '#0066CC',        // Secondary - Light Blue
        'REFERENCE-orange': '#E87722',      // Accent - Orange
        'REFERENCE-gray': '#4A5568',        // Text - Dark Gray
        'REFERENCE-light-gray': '#F7FAFC',  // Background - Light Gray
        'REFERENCE-border': '#E2E8F0',      // Border - Medium Gray
      },
      fontFamily: {
        'sans': ['Arial', 'Helvetica Neue', 'Helvetica', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
