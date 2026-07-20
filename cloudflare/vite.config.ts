import { defineConfig } from "vite";

export default defineConfig({
  root: "dashboard",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
});
