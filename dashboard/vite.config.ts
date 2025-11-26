import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const allowedHosts = ["*", "monimoni-dashboard-oyw1xe-7f563e-45-87-120-125.traefik.me", "kerimyeniyildiz.com.tr", "www.kerimyeniyildiz.com.tr"];

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
    allowedHosts,
  },
});
