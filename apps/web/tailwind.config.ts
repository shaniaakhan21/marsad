import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Old token names, repointed at the new flat-console palette — this is
        // what re-skins any component that isn't individually restyled.
        ink: "#0A0C0E",
        panel: "#14181C",
        panel2: "#1F252B",
        line: "#232A31",
        muted: "#6B7883",
        brand: { purple: "#D7FF3E", cyan: "#D7FF3E", pink: "#FF4B1F" },
        band: { low: "#12A97A", mid: "#F5A524", high: "#E5484D", critical: "#FF4B1F" },

        // New tokens the redesign needs directly.
        rail: "#0C0F12",
        sunken: "#1F252B",
        text: {
          primary: "#F7F5F1",
          secondary: "#9AA5AE",
          muted: "#6B7883",
          faint: "#4A555F",
        },
        volt: { DEFAULT: "#D7FF3E", hover: "#BEE81C" },
        ember: { DEFAULT: "#FF4B1F", tint: "#FF7A55" },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "Menlo", "monospace"],
        display: ["Archivo", "ui-sans-serif", "sans-serif"],
        sans: ["Instrument Sans", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        signature: "3px 3px 0 rgba(215,255,62,.28)",
        "signature-sm": "2px 2px 0 rgba(215,255,62,.28)",
        "signature-press": "1px 1px 0 rgba(215,255,62,.28)",
      },
      transitionTimingFunction: {
        console: "cubic-bezier(.22,1,.36,1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
