import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  root: __dirname,
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        // 127.0.0.1 évite la résolution IPv6 (::1) de WSL2 qui provoque ECONNRESET
        target: 'http://127.0.0.1:8000',
        // Preserve the original host so the backend can resolve the tenant
        // from cpk.localhost / cn.localhost exactly like production.
        changeOrigin: false,
        secure: false,
        configure: (proxy) => {
          proxy.on('error', (err: NodeJS.ErrnoException, _req, res) => {
            if (err.code === 'ECONNRESET' || err.code === 'ECONNREFUSED') {
              console.warn(`[proxy] ${err.code} — backend temporarily unavailable`)
              if (!res.headersSent) {
                (res as import('http').ServerResponse).writeHead(502, { 'Content-Type': 'application/json' })
                ;(res as import('http').ServerResponse).end(JSON.stringify({ detail: 'Backend unavailable' }))
              }
            }
          })
        },
      },
    },
  },
})
