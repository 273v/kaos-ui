/**
 * Tailwind 4 preset for @273v/kaos-ui-react.
 *
 * Maps the package's CSS variables (defined in styles.css) to Tailwind
 * theme colors so consumers can write `bg-card` / `text-muted-foreground`
 * etc. in their own JSX and have it pick up the kaos theme.
 *
 * Wire it in your consumer:
 *
 *   // tailwind.config.ts
 *   import kaosPreset from "@273v/kaos-ui-react/tailwind.preset";
 *   export default {
 *     presets: [kaosPreset],
 *     content: [
 *       "./src/**\/*.{ts,tsx}",
 *       "./node_modules/@273v/kaos-ui-react/dist/**\/*.{js,mjs,cjs}",
 *     ],
 *   };
 *
 * Tailwind 4 also supports inline @theme blocks via CSS; consumers
 * using that style can skip this preset and just `@import` styles.css.
 */
const preset = {
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--kaos-background))",
        foreground: "hsl(var(--kaos-foreground))",
        card: {
          DEFAULT: "hsl(var(--kaos-card))",
          foreground: "hsl(var(--kaos-card-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--kaos-muted))",
          foreground: "hsl(var(--kaos-muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--kaos-accent))",
          foreground: "hsl(var(--kaos-accent-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--kaos-primary))",
          foreground: "hsl(var(--kaos-primary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--kaos-destructive))",
          foreground: "hsl(var(--kaos-destructive-foreground))",
        },
        warn: {
          DEFAULT: "hsl(var(--kaos-warn))",
          foreground: "hsl(var(--kaos-warn-foreground))",
        },
        border: "hsl(var(--kaos-border))",
        input: "hsl(var(--kaos-input))",
        ring: "hsl(var(--kaos-ring))",
      },
    },
  },
};

export default preset;
