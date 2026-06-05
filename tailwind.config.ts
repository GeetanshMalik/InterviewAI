import type { Config } from "tailwindcss"

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
    "./layouts/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        // Framer Design System Colors
        primary: "#5e6ad2", // Changed to requested blue
        "on-primary": "#ffffff",
        "accent-blue": "#5e6ad2", // Changed to requested blue
        ink: "#ffffff",
        "ink-muted": "#999999",
        canvas: "#090909",
        "surface-1": "#141414",
        "surface-2": "#1c1c1c",
        hairline: "#262626",
        "hairline-soft": "#1a1a1a",
        "inverse-canvas": "#ffffff",
        "inverse-ink": "#000000",
        "gradient-magenta": "#5e6ad2", 
        "gradient-violet": "#5e6ad2", 
        "gradient-orange": "#5e6ad2", 
        "gradient-coral": "#5e6ad2",
        "semantic-success": "#22c55e",
      },
      fontFamily: {
        sans: ["var(--font-inter)"],
        display: ["var(--font-geist-sans)"], // Using Geist as GT Walsheim substitute
      },
      fontSize: {
        "display-xxl": ["110px", { lineHeight: "0.85", letterSpacing: "-5.5px", fontWeight: "500" }],
        "display-xl": ["85px", { lineHeight: "0.95", letterSpacing: "-4.25px", fontWeight: "500" }],
        "display-lg": ["62px", { lineHeight: "1.00", letterSpacing: "-3.1px", fontWeight: "500" }],
        "display-md": ["32px", { lineHeight: "1.13", letterSpacing: "-1.0px", fontWeight: "500" }],
        headline: ["22px", { lineHeight: "1.20", letterSpacing: "-0.8px", fontWeight: "700" }],
        subhead: ["24px", { lineHeight: "1.30", letterSpacing: "-0.01px", fontWeight: "400" }],
        "body-lg": ["18px", { lineHeight: "1.30", letterSpacing: "-0.18px", fontWeight: "400" }],
        body: ["15px", { lineHeight: "1.30", letterSpacing: "-0.15px", fontWeight: "400" }],
        "body-sm": ["14px", { lineHeight: "1.40", letterSpacing: "-0.14px", fontWeight: "500" }],
        caption: ["13px", { lineHeight: "1.20", letterSpacing: "-0.13px", fontWeight: "500" }],
        micro: ["12px", { lineHeight: "1.20", letterSpacing: "-0.12px", fontWeight: "400" }],
        button: ["14px", { lineHeight: "1.0", letterSpacing: "-0.14px", fontWeight: "500" }],
      },
      borderRadius: {
        xs: "4px",
        sm: "6px",
        md: "10px",
        lg: "15px",
        xl: "20px",
        "2xl": "30px",
        pill: "100px",
        full: "9999px",
      },
      spacing: {
        hair: "1px",
        xxs: "4px",
        xs: "8px",
        sm: "12px",
        md: "15px",
        lg: "20px",
        xl: "30px",
        "2xl": "40px",
        section: "96px",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}

export default config
