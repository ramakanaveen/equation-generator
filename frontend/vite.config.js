import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.VITE_BACKEND_URL || 'http://localhost:8000'
  const devPort    = parseInt(env.VITE_PORT || '5173', 10)

  return {
    plugins: [react()],
    server: {
      port: devPort,
      proxy: { '/api': backendUrl },
    },
  }
})
