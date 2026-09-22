import type { Config } from "tailwindcss";

/**
 * MARSAD console palette.
 *
 * A light, high-contrast ground so every label reads at a glance — on a laptop in a
 * meeting room and on a screen recording alike. Two hues carry meaning and nothing
 * else gets one: petrol for the institution's own side of the boundary (and the
 * primary action), ochre for what crossed it. Red, amber and green are reserved for
 * status.
 *
 * Token NAMES are kept from the previous theme so every page re-skins through them;
 * only the values changed. `ink` is the page ground, which is also why `text-ink` on a
 * petrol button reads as light text on a dark fill.
 */
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#F2F5F4",
        panel: "#FFFFFF",
        panel2: "#F7FAF9",
        sunken: "#EAF0EE",
        line: { DEFAULT: "#D3DCDA", strong: "#B4C2BF" },
        muted: "#4C5C58",
        brand: { purple: "#0B5D60", cyan: "#0B5D60", pink: "#B42318" },
        band: { low: "#127046", mid: "#8F4F00", high: "#C2410C", critical: "#B42318" },

        // The navigation rail stays dark so the workspace reads as one surface.
        rail: {
          DEFAULT: "#0F2224",
          line: "#223B3D",
          text: "#E4EEEC",
          muted: "#A7BDBB",
          faint: "#7F9795",
          accent: "#8FD9D6",
        },

        // Every text tier clears WCAG AA (4.5:1) on white and on the tinted cards.
        text: {
          primary: "#0D1715",
          secondary: "#2E3D3A",
          muted: "#4C5C58",
          faint: "#5F6E6A",
        },

        volt: { DEFAULT: "#0B5D60", hover: "#084A4D" },
        edge: "#0B5D60",
        core: "#8C6110",
        ember: { DEFAULT: "#B42318", tint: "#D9432F" },
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "IBM Plex Sans Arabic", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["IBM Plex Sans", "IBM Plex Sans Arabic", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "IBM Plex Sans Arabic", "ui-monospace", "Menlo", "monospace"],
        arabic: ["IBM Plex Sans Arabic", "IBM Plex Sans", "ui-sans-serif", "sans-serif"],
      },
      boxShadow: {
        signature: "0 1px 0 rgba(8,74,77,.9), 0 3px 8px -2px rgba(11,93,96,.35)",
        "signature-sm": "0 1px 0 rgba(8,74,77,.9), 0 2px 5px -2px rgba(11,93,96,.3)",
        "signature-press": "0 0 0 rgba(0,0,0,0)",
        card: "0 1px 2px rgba(13,23,21,.05)",
      },
      transitionTimingFunction: {
        console: "cubic-bezier(.22,1,.36,1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
