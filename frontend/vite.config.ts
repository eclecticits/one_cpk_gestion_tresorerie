import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        // Preserve the original host so the backend can resolve the tenant
        // from cpk.localhost / cn.localhost exactly like production.
        changeOrigin: false,
        secure: false,
      },
    },
  },
})
