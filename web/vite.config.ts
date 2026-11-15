import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const WEB_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(WEB_DIR, '..')
const DATA_DIR = path.join(REPO_ROOT, 'data')

const CONTENT_TYPES: Record<string, string> = {
  '.json': 'application/json',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.jpg': 'image/jpeg',
}

/**
 * Phase 4 reads committed files from ../data, which sits outside the Vite root.
 * Served at /data/* in dev, copied into dist/data on build. Phase 5 replaces both
 * with API calls; nothing else in the app knows the difference.
 */
function repoData(): Plugin {
  return {
    name: 'zenithsquad-repo-data',

    configureServer(server) {
      server.middlewares.use('/data', (req, res, next) => {
        const relative = decodeURIComponent((req.url ?? '/').split('?')[0])
        const resolved = path.join(DATA_DIR, relative)

        // Never serve outside data/, and never serve the FITS cache.
        if (!resolved.startsWith(DATA_DIR) || relative.includes('cache')) return next()

        let stat: fs.Stats
        try {
          stat = fs.statSync(resolved)
        } catch {
          res.statusCode = 404
          res.end(`not found: data${relative}`)
          return
        }
        if (stat.isDirectory()) return next()

        res.setHeader('Content-Type', CONTENT_TYPES[path.extname(resolved)] ?? 'application/octet-stream')
        res.end(fs.readFileSync(resolved))
      })
    },

    closeBundle() {
      const out = path.join(WEB_DIR, 'dist', 'data')
      fs.mkdirSync(out, { recursive: true })
      fs.cpSync(path.join(DATA_DIR, 'targets.json'), path.join(out, 'targets.json'))
      fs.cpSync(path.join(DATA_DIR, 'fallback'), path.join(out, 'fallback'), { recursive: true })
    },
  }
}

export default defineConfig({
  plugins: [react(), repoData()],
  server: {
    // Phase 5: the app asks for /api/*, and in dev that is the FastAPI process on :8000. Proxying
    // keeps dev same-origin, so no CORS and no env var is needed to run both halves together.
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
