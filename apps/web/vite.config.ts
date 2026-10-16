import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: proxy API calls so the browser stays same-origin (no CORS, SSE works).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:4000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
