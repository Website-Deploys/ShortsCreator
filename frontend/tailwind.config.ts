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
    },
  },
  plugins: [],
};

export default config;
