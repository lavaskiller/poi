import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Python backend (server.py) serves the /api/* routes on port 8420.
// In dev, proxy them so the SPA can call /api/* on the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8420',
    },
  },
})
