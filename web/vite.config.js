import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" so the static build works on Vercel, GitHub Pages, or any subpath.
export default defineConfig({
  base: "./",
  plugins: [react()],
});
