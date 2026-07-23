import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// The Python backend (server.py) serves the /api/* routes on port 8420.
// In dev, proxy them so the SPA can call /api/* on the same origin.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const backendPort = env.POI_PORT || '8420'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        // Keep the proxy aligned when dev_up.sh/server.py use a custom POI_PORT.
        '/api': `http://localhost:${backendPort}`,
      },
    },
  }
})
