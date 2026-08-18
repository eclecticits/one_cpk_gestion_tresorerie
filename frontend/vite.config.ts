import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  root: __dirname,
  plugins: [react()],
  build: {
    // Les libs volumineuses (xlsx, jspdf, recharts...) dépassent largement
    // 500 kB une fois isolées dans leur propre chunk vendor ; c'est voulu
    // (meilleur cache long terme) donc on relève juste le seuil d'alerte.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Le helper de dynamic import de Vite est partagé par TOUTES les
          // pages lazy() et par les libs (jspdf en interne l'utilise aussi).
          // Sans cette règle, Rollup peut l'embarquer dans un gros chunk
          // vendor (ex: vendor-jspdf, 420 kB) — l'entrée statique importerait
          // alors ce chunk entier juste pour ce helper de quelques octets,
          // et index.html le modulepreload-erait sur CHAQUE chargement.
          if (id.includes('vite/preload-helper')) {
            return 'vendor-preload-helper'
          }

          if (!id.includes('node_modules')) {
            return undefined
          }

          // React + react-dom + react-router DOIVENT rester dans le même
          // chunk : les séparer casse l'ordre d'initialisation (react-dom
          // et react-router dépendent du même module React au chargement).
          if (
            /node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(id)
          ) {
            return 'vendor-react'
          }

          if (/node_modules\/(recharts|d3-[^/]+|victory-vendor)\//.test(id)) {
            return 'vendor-recharts'
          }

          if (/node_modules\/xlsx\//.test(id)) {
            return 'vendor-xlsx'
          }

          if (/node_modules\/(jspdf|jspdf-autotable)\//.test(id)) {
            return 'vendor-jspdf'
          }

          if (/node_modules\/(html2canvas)\//.test(id)) {
            return 'vendor-html2canvas'
          }

          if (/node_modules\/lucide-react\//.test(id)) {
            return 'vendor-icons'
          }

          if (/node_modules\/date-fns\//.test(id)) {
            return 'vendor-date-fns'
          }

          if (/node_modules\/@tanstack\/react-query\//.test(id)) {
            return 'vendor-react-query'
          }

          return undefined
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    watch: {
      // WSL2 + Windows-mounted drive (/mnt/d/...): inotify events from DrvFs
      // are unreliable, so file edits don't trigger HMR without polling.
      usePolling: true,
      interval: 300,
    },
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
