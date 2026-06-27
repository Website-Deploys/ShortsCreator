import type { Config } from "tailwindcss";

/**
 * Tailwind configuration.
 *
 * Defines the Olympus design tokens (a small, calm, premium palette) and scans
 * the app/components for class usage. Kept intentionally minimal for the MVP -
 * the design system grows here as the UI matures.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Olympus brand palette (calm, premium, high-contrast).
        ink: "#0b0b0f",
        surface: "#14141b",
        elevated: "#1d1d27",
        accent: "#6366f1",
        "accent-strong": "#4f46e5",
        muted: "#9ca3af",
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      keyframes: {
        "toast-in": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
      },
      animation: {
        "fade-in": "fade-in 240ms ease-out both",
        "pulse-soft": "pulse-soft 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
