import { useEffect } from 'react'
import { ArrowLeft, FileSpreadsheet } from 'lucide-react'
import { SITE_NAME } from '../site'

export default function NotFound() {
  useEffect(() => {
    document.title = `Page not found — ${SITE_NAME}`
    // Keep this URL out of search results.
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])

  return (
    <div className="lp nf">
      <main className="nf-inner" id="main">
        <a className="lp-brand" href="/" aria-label={`${SITE_NAME} home`}>
          <span className="lp-logo"><FileSpreadsheet size={16} strokeWidth={2.2} /></span>
          {SITE_NAME}
        </a>
        <div className="nf-cell" aria-hidden="true">
          <span className="nf-ref">#REF!</span>
        </div>
        <p className="lp-eyebrow">Error 404</p>
        <h1>This cell is empty.</h1>
        <p className="nf-text">
          The page you’re looking for doesn’t exist or has moved. Check the address, or head back to start.
        </p>
        <a className="lp-btn lp-btn-dark lp-btn-lg" href="/"><ArrowLeft size={16} /> Back to home</a>
      </main>
    </div>
  )
}
