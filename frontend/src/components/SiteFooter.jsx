import { FileSpreadsheet } from 'lucide-react'
import { CONTACT_EMAIL, SITE_NAME } from '../site'

export default function SiteFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-wrap lp-footer-inner">
        <div className="lp-footer-brand">
          <a className="lp-brand" href="/" aria-label={`${SITE_NAME} home`}>
            <span className="lp-logo"><FileSpreadsheet size={16} strokeWidth={2.2} /></span>
            {SITE_NAME}
          </a>
          <p>Find and fix problems in any spreadsheet. Your original file is never modified.</p>
        </div>
        <nav className="lp-footer-links" aria-label="Legal">
          <a href="/privacy">Privacy policy</a>
          <a href="/terms">Terms of service</a>
          {CONTACT_EMAIL && <a href={`mailto:${CONTACT_EMAIL}`}>Contact</a>}
        </nav>
      </div>
      <div className="lp-wrap lp-footer-base">© {new Date().getFullYear()} {SITE_NAME}. All rights reserved.</div>
    </footer>
  )
}
