import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Public pages listed in the sitemap. The workspace lives at "/" behind
// sign-in, so "/" is the only app URL worth indexing.
const PAGES = [
  { path: '/', priority: '1.0' },
  { path: '/privacy', priority: '0.3' },
  { path: '/terms', priority: '0.3' },
]

/**
 * Absolute site URL for canonical/OG tags, the sitemap and robots.txt.
 * VITE_SITE_URL wins; on Vercel the production domain is provided
 * automatically at build time.
 */
function siteUrl(env) {
  const url = env.VITE_SITE_URL
    || (process.env.VERCEL_PROJECT_PRODUCTION_URL && `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`)
    || 'http://localhost:5173'
  return url.replace(/\/+$/, '')
}

function seo(url) {
  return {
    name: 'excelai-seo',
    transformIndexHtml: { order: 'pre', handler: (html) => html.replaceAll('%SITE_URL%', url) },
    generateBundle() {
      const today = new Date().toISOString().slice(0, 10)
      const urls = PAGES.map(({ path, priority }) =>
        `  <url><loc>${url}${path}</loc><lastmod>${today}</lastmod><priority>${priority}</priority></url>`,
      ).join('\n')
      this.emitFile({
        type: 'asset',
        fileName: 'sitemap.xml',
        source: `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
      })
      this.emitFile({
        type: 'asset',
        fileName: 'robots.txt',
        source: `User-agent: *\nAllow: /\n\nSitemap: ${url}/sitemap.xml\n`,
      })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), seo(siteUrl(env))],
    server: { port: 5173 },
    build: {
      rollupOptions: {
        output: {
          // Long-lived vendor chunks: app changes don't invalidate them.
          manualChunks: {
            react: ['react', 'react-dom'],
            clerk: ['@clerk/react'],
          },
        },
      },
    },
  }
})
