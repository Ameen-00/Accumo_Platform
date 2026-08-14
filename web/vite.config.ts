import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: browser talks to Vite, Vite forwards API calls to FastAPI.
// Prod: Caddy (or any reverse proxy) serves dist/ and the same API paths.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/imports": "http://127.0.0.1:8000",
      "/runs": "http://127.0.0.1:8000",
      "/exceptions": "http://127.0.0.1:8000",
      "/reports": "http://127.0.0.1:8000",
      "/identities": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
