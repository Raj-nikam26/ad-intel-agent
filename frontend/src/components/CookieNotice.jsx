import { useState } from 'react'
import { Cookie } from 'lucide-react'

const KEY = 'excelai.cookie-notice'

/**
 * The site uses only essential storage (the sign-in session and the last
 * opened file), which needs no opt-in; this notice tells visitors so and is
 * dismissed for good once acknowledged.
 */
export default function CookieNotice() {
  const [open, setOpen] = useState(() => {
    try { return !localStorage.getItem(KEY) } catch { return false }
  })
  if (!open) return null

  const close = () => {
    try { localStorage.setItem(KEY, new Date().toISOString()) } catch { /* private mode */ }
    setOpen(false)
  }

  return (
    <div className="ck" role="region" aria-label="Cookie notice">
      <span className="ck-icon" aria-hidden="true"><Cookie size={18} /></span>
      <p>
        We use only essential cookies to keep you signed in — no tracking or advertising.{' '}
        <a href="/privacy">Read the privacy policy</a>
      </p>
      <button className="lp-btn lp-btn-dark lp-btn-sm" onClick={close}>Got it</button>
    </div>
  )
}
