import { useRef, useState } from 'react'
import {
  FileSpreadsheet, UploadCloud, SearchCheck, Network, History, FunctionSquare, ArrowRight, Sparkles,
} from 'lucide-react'

const FEATURES = [
  {
    icon: SearchCheck,
    title: 'Problems found for you',
    text: 'Blank cells, columns that disagree and near-duplicate names, listed with the exact rows.',
  },
  {
    icon: Network,
    title: 'Questions across columns',
    text: 'Ask how customers, offices or categories connect. Answers come from a graph of your own data.',
  },
  {
    icon: History,
    title: 'Every change reversible',
    text: 'Edits happen only when you ask, show the cells they touched, and can be restored any time.',
  },
  {
    icon: FunctionSquare,
    title: 'Repeat it in Excel',
    text: 'Each answer and fix comes with the formula or steps to do the same in your own file.',
  },
]

const STEPS = [
  ['Open a file', 'Any .xlsx or .xls, read exactly as it is.'],
  ['Review what was found', 'Problems and column roles, worked out for you.'],
  ['Fix what you choose', 'Each fix is a new version you can undo.'],
]

/** A small, static picture of the workspace - what the product looks like. */
function ProductPreview() {
  const rows = [
    ['Sakal Media Group', 'Finance', 'Pune'],
    ['Parle Products', 'Fmcg', 'Mumbai'],
    ['Lokmat Group', null, 'Nagpur'],
    ['Tata Motors', 'Auto', 'Pune'],
    ['Bajaj Finserv', 'Finance', null],
  ]
  return (
    <div className="lp-preview" aria-hidden="true">
      <div className="lp-pv-bar">
        <span className="lp-pv-dots"><i /><i /><i /></span>
        <span className="lp-pv-file">Advertisers.xlsx</span>
        <span className="lp-pv-ver">v2</span>
      </div>
      <div className="lp-pv-body">
        <table className="lp-pv-grid">
          <thead>
            <tr><th /><th>A · Advertiser</th><th>B · Category</th><th>C · Office</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="n">{i + 2}</td>
                {r.map((c, j) => (
                  <td key={j} className={c === null ? 'gap' : undefined}>
                    {c ?? '∅'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="lp-pv-chat">
          <div className="lp-pv-msg me">What's missing in Category?</div>
          <div className="lp-pv-msg bot">
            <Sparkles size={12} /> 1 row has no Category — row 4. Want me to fill it?
          </div>
          <div className="lp-pv-fx"><span>fx</span> =SUMPRODUCT(--(TRIM(B2:B6)=""))</div>
        </div>
      </div>
    </div>
  )
}

/**
 * Entry screen.
 *
 * Signed out: a public page - what the product does, with Sign in and Get
 * started. Opening a file asks the visitor to sign in first.
 * Signed in: the same page with a working upload area and the account.
 */
export default function LandingPage({
  onUpload, onSample, uploading, error, account, onSignIn, onSignUp,
}) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const signedIn = !!account || !onSignIn

  const pick = (file) => file && onUpload({ target: { files: [file] } })
  const needSignIn = () => onSignIn?.()

  return (
    <div className="lp">
      <header className="lp-nav">
        <div className="lp-brand">
          <span className="lp-logo"><FileSpreadsheet size={16} /></span>
          ExcelAI
        </div>
        <nav className="lp-links">
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
        </nav>
        {account ? (
          <div className="lp-account">
            <span className="lp-account-text">
              <span className="lp-account-label">Signed in as</span>
              <span className="lp-account-name">{account.name}</span>
            </span>
            {account.button}
          </div>
        ) : onSignIn ? (
          <div className="lp-auth">
            <button className="lp-link-btn" onClick={onSignIn}>Sign in</button>
            <button className="lp-btn lp-btn-primary lp-btn-sm" onClick={onSignUp || onSignIn}>
              Get started
            </button>
          </div>
        ) : <span />}
      </header>

      <section className="lp-hero">
        <div className="lp-hero-inner">
          <div className="lp-copy">
            <p className="lp-kicker"><Sparkles size={13} /> Spreadsheet checks with an assistant</p>
            <h1>
              Find what's wrong with your spreadsheet.
              <span> Fix only what you approve.</span>
            </h1>
            <p className="lp-sub">
              Open any Excel file to see its problems, ask how its data connects,
              and make changes you can always undo.
            </p>

            {signedIn ? (
              <div
                className={`lp-drop${dragging ? ' is-dragging' : ''}`}
                onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]) }}
              >
                <UploadCloud size={22} className="lp-drop-icon" />
                <div className="lp-drop-text">
                  <strong>{uploading ? 'Opening your file…' : 'Drop an Excel file here'}</strong>
                  <span>.xlsx or .xls, up to 25 MB</span>
                </div>
                <button className="lp-btn lp-btn-primary" disabled={uploading}
                        onClick={() => inputRef.current?.click()}>
                  Choose file
                </button>
                <input ref={inputRef} type="file" accept=".xlsx,.xls" hidden
                       onChange={onUpload} disabled={uploading} />
              </div>
            ) : (
              <div className="lp-cta">
                <button className="lp-btn lp-btn-primary lp-btn-lg" onClick={onSignUp || onSignIn}>
                  Get started — it's free <ArrowRight size={16} />
                </button>
                <span className="lp-cta-note">Sign in with Google or email</span>
              </div>
            )}

            <button className="lp-sample" disabled={uploading}
                    onClick={signedIn ? onSample : needSignIn}>
              or try it with the sample file
              <span>11,275 newspaper ad insertions</span>
              <ArrowRight size={14} />
            </button>
            {error && <p className="lp-error">{error}</p>}
          </div>

          <ProductPreview />
        </div>
      </section>

      <section className="lp-band" id="features">
        <div className="lp-wrap">
          <h2 className="lp-h2">Everything you need to trust a spreadsheet</h2>
          <div className="lp-features">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <div key={title} className="lp-feature">
                <span className="lp-feature-icon"><Icon size={18} /></span>
                <div>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-wrap lp-how" id="how">
        <h2 className="lp-h2">How it works</h2>
        <ol className="lp-timeline">
          {STEPS.map(([title, text], i) => (
            <li key={title}>
              <span className="lp-step-n">{i + 1}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </li>
          ))}
        </ol>
      </section>

      <footer className="lp-footer">
        <span>ExcelAI</span>
        <span>Your original file is never modified.</span>
      </footer>
    </div>
  )
}
