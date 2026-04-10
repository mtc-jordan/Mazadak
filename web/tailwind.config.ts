import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: "#1C3557", light: "#2A4A72", dark: "#152840" },
        gold: { DEFAULT: "#9A6420", light: "#B8802F", dim: "rgba(154,100,32,0.12)" },
        cream: { DEFAULT: "#FBF5E8", dark: "#F0EAD8" },
        sand: "#F0EAD8",
        ink: "#1A1814",
        mist: "#8A8275",
        ember: { DEFAULT: "#C4420A", light: "#E87351", dim: "rgba(196,66,10,0.08)" },
        emerald: { DEFAULT: "#0D5C3A", light: "#30A06A", dim: "rgba(13,92,58,0.08)" },
        fog: "#F5F2EC",
      },
      fontFamily: {
        sora: ["Sora", "sans-serif"],
      },
      animation: {
        "pulse-slow": "pulse 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
