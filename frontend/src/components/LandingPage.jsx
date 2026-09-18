import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight, Check, ChevronDown, FileSpreadsheet, History, KeyRound, Lock, Network,
  SearchCheck, ShieldCheck, Sparkles, SquareFunction, UploadCloud, Wand2,
} from 'lucide-react'
import SiteFooter from './SiteFooter'

const FEATURES = [
  {
    icon: SearchCheck,
    title: 'Problems found for you',
    text: 'Blank cells, columns that disagree and near-duplicate names — each listed with the exact rows.',
    big: true,
    demo: 'problems',
  },
  {
    icon: Network,
    title: 'Answers across columns',
    text: 'Ask how customers, offices or categories connect. Answers come from a graph built from your own rows.',
    big: true,
    demo: 'graph',
  },
  {
    icon: History,
    title: 'Every change reversible',
    text: 'Edits happen only when you ask, highlight the cells they touched, and can be restored any time.',
  },
  {
    icon: SquareFunction,
    title: 'Repeat it in Excel',
    text: 'Each answer comes with the formula or steps to do the same in your own workbook.',
  },
  {
    icon: Wand2,
    title: 'Works with any file',
    text: 'Columns are recognised automatically — names, categories, amounts, dates and flags.',
  },
]

const STEPS = [
  ['Open a file', 'Any .xlsx or .xls up to 25 MB. It is read exactly as it is — nothing is changed.'],
  ['Review what was found', 'Problems are listed by type with the rows involved, and each column’s role is worked out.'],
  ['Fix what you choose', 'Ask the assistant for a change. It becomes a new version you can compare and undo.'],
]

const TRUST = [
  { icon: Lock, title: 'Private to your account', text: 'Files are tied to the account that opened them. Nobody else can load them.' },
  { icon: ShieldCheck, title: 'Your original stays intact', text: 'Changes are saved as new versions. The file you opened is never overwritten.' },
  { icon: KeyRound, title: 'Encrypted in transit', text: 'All traffic uses HTTPS, and stored versions are signed so tampering is detected.' },
]

const FAQ = [
  ['Which files can I open?', 'Excel workbooks in .xlsx or .xls format, up to 25 MB. The first sheet is loaded; columns and their types are recognised automatically.'],
  ['Will it change my file without asking?', 'No. The assistant only edits when you ask it to, every edit is saved as a new version with a reason, and any earlier version can be restored.'],
  ['Can I get the edited file back?', 'Yes. Export downloads the current version as an .xlsx file at any time.'],
  ['Do I need to know formulas?', 'No. Ask in plain English. When an answer has an Excel equivalent, the formula and steps are shown so you can repeat it yourself.'],
  ['Is it free?', 'Yes. Usage limits apply to keep the service fair for everyone.'],
]

/** A static picture of the workspace - what the product looks like. */
function ProductPreview() {
  const rows = [
    ['Sakal Media Group', 'Finance', 'Pune'],
    ['Parle Products', 'Fmcg', 'Mumbai'],
    ['Lokmat Group', null, 'Nagpur'],
    ['Tata Motors', 'Auto', 'Pune'],
    ['Bajaj Finserv', 'Finance', null],
    ['Godrej Properties', 'Real Estate', 'Mumbai'],
  ]
  return (
    <div className="lp-shot" aria-hidden="true">
      <div className="lp-window">
        <div className="lp-win-bar">
          <span className="lp-win-dots"><i /><i /><i /></span>
          <span className="lp-win-file"><FileSpreadsheet size={13} /> Advertisers.xlsx</span>
          <span className="lp-win-ver">v2 · edited</span>
        </div>
        <div className="lp-win-body">
          <table className="lp-grid">
            <thead>
              <tr><th /><th><small>A</small>Advertiser</th><th><small>B</small>Category</th><th><small>C</small>Office</th></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={i === 2 ? 'hl' : undefined}>
                  <td className="n">{i + 2}</td>
                  {r.map((c, j) => (
                    <td key={j} className={c === null ? 'gap' : i === 5 && j === 1 ? 'chg' : undefined}>
                      {c ?? '∅'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="lp-float lp-float-chat">
        <div className="lp-bubble me">Which rows are missing a Category?</div>
        <div className="lp-bubble bot">
          <span className="lp-bot-ic"><Sparkles size={11} /></span>
          <span>1 row — <b>Lokmat Group</b> on row 4. Want me to fill it from similar rows?</span>
        </div>
        <div className="lp-fx"><span>fx</span>=COUNTBLANK(B2:B7)</div>
      </div>

      <div className="lp-float lp-float-issues">
        <div className="lp-issues-head">Problems <b>3</b></div>
        <div className="lp-issue"><i className="r" /> 1 missing Category</div>
        <div className="lp-issue"><i className="r" /> 1 missing Office</div>
        <div className="lp-issue"><i className="a" /> 2 similar names</div>
      </div>
    </div>
  )
}

function FeatureDemo({ kind }) {
  if (kind === 'problems') {
    return (
      <div className="lp-demo" aria-hidden="true">
        <div className="lp-demo-row"><i className="r" /> 138 rows missing <code>Category</code><span>Show</span></div>
        <div className="lp-demo-row"><i className="r" /> 146 rows missing <code>Sub Category</code><span>Show</span></div>
        <div className="lp-demo-row"><i className="a" /> “Sakal Media” vs “Sakal Media Grp”<span>Merge</span></div>
      </div>
    )
  }
  return (
    <div className="lp-demo lp-demo-graph" aria-hidden="true">
      <svg viewBox="0 0 260 110" role="presentation">
        <g stroke="#cbd5e1" strokeWidth="1.2">
          <line x1="130" y1="55" x2="40" y2="25" /><line x1="130" y1="55" x2="45" y2="88" />
          <line x1="130" y1="55" x2="215" y2="22" /><line x1="130" y1="55" x2="222" y2="85" />
          <line x1="130" y1="55" x2="130" y2="12" />
        </g>
        <circle cx="130" cy="55" r="13" fill="#059669" />
        <circle cx="40" cy="25" r="7" fill="#6366f1" /><circle cx="45" cy="88" r="7" fill="#f59e0b" />
        <circle cx="215" cy="22" r="7" fill="#6366f1" /><circle cx="222" cy="85" r="7" fill="#0ea5e9" />
        <circle cx="130" cy="12" r="6" fill="#f59e0b" />
      </svg>
    </div>
  )
}

/**
 * Public entry page.
 *
 * Signed out: what the product does, with Sign in and Get started; opening
 * a file asks the visitor to sign in first. Signed in (or with sign-in
 * turned off): the same page with a working upload area.
 */
export default function LandingPage({
  onUpload, onSample, uploading, error, account, onSignIn, onSignUp,
}) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const signedIn = !!account || !onSignIn
  const start = onSignUp || onSignIn

  useEffect(() => { document.title = 'ExcelAI — find and fix problems in any spreadsheet' }, [])

  const pick = (file) => file && onUpload({ target: { files: [file] } })

  return (
    <div className="lp" onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 8)}>
      <a className="lp-skip" href="#main">Skip to content</a>

      <header className={`lp-nav${scrolled ? ' is-scrolled' : ''}`}>
        <div className="lp-nav-inner">
          <a className="lp-brand" href="/" aria-label="ExcelAI home">
            <span className="lp-logo"><FileSpreadsheet size={16} strokeWidth={2.2} /></span>
            ExcelAI
          </a>
          <nav className="lp-links" aria-label="Sections">
            <a href="#features">Features</a>
            <a href="#how">How it works</a>
            <a href="#security">Security</a>
            <a href="#faq">FAQ</a>
          </nav>
          {account ? (
            <div className="lp-account">
              <span className="lp-account-name">{account.name}</span>
              {account.button}
            </div>
          ) : onSignIn ? (
            <div className="lp-auth">
              <button className="lp-link-btn" onClick={onSignIn}>Sign in</button>
              <button className="lp-btn lp-btn-dark lp-btn-sm" onClick={start}>Get started</button>
            </div>
          ) : <span />}
        </div>
      </header>

      <main id="main">
        <section className="lp-hero">
          <div className="lp-hero-bg" aria-hidden="true" />
          <div className="lp-wrap lp-hero-inner">
            <div className="lp-copy">
              <p className="lp-badge"><span>New</span> Ask questions across every column</p>
              <h1>
                Find what’s wrong with your spreadsheet.{' '}
                <span className="lp-grad">Fix only what you approve.</span>
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
                  <span className="lp-drop-icon"><UploadCloud size={20} /></span>
                  <div className="lp-drop-text">
                    <strong>{uploading ? 'Opening your file…' : 'Drop an Excel file here'}</strong>
                    <span>.xlsx or .xls, up to 25 MB</span>
                  </div>
                  <button className="lp-btn lp-btn-dark" disabled={uploading}
                          onClick={() => inputRef.current?.click()}>
                    Choose file
                  </button>
                  <input ref={inputRef} type="file" accept=".xlsx,.xls" hidden aria-label="Choose an Excel file"
                         onChange={onUpload} disabled={uploading} />
                </div>
              ) : (
                <div className="lp-cta">
                  <button className="lp-btn lp-btn-dark lp-btn-lg" onClick={start}>
                    Get started free <ArrowRight size={16} />
                  </button>
                  <button className="lp-btn lp-btn-ghost lp-btn-lg" onClick={onSignIn}>
                    Try the sample file
                  </button>
                </div>
              )}

              {signedIn && (
                <button className="lp-sample" disabled={uploading} onClick={onSample}>
                  or try it with the sample file <span>· 11,275 ad insertions</span>
                  <ArrowRight size={14} />
                </button>
              )}
              {error && <p className="lp-error" role="alert">{error}</p>}

              <ul className="lp-ticks">
                <li><Check size={14} /> Original file never modified</li>
                <li><Check size={14} /> Every edit reversible</li>
                <li><Check size={14} /> Free to use</li>
              </ul>
            </div>

            <ProductPreview />
          </div>
        </section>

        <section className="lp-strip" aria-label="At a glance">
          <div className="lp-wrap lp-strip-inner">
            <div><b>Any</b><span>Excel file, any columns</span></div>
            <div><b>Seconds</b><span>to check 10,000+ rows</span></div>
            <div><b>Every</b><span>change saved as a version</span></div>
            <div><b>Formula</b><span>for each answer</span></div>
          </div>
        </section>

        <section className="lp-section" id="features">
          <div className="lp-wrap">
            <p className="lp-eyebrow">Features</p>
            <h2 className="lp-h2">Everything you need to trust a spreadsheet</h2>
            <p className="lp-lead">From a first look at a messy file to a clean one you can hand over.</p>
            <div className="lp-bento">
              {FEATURES.map(({ icon: Icon, title, text, big, demo }) => (
                <article key={title} className={`lp-card${big ? ' big' : ''}`}>
                  <span className="lp-card-icon"><Icon size={18} /></span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                  {demo && <FeatureDemo kind={demo} />}
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section lp-alt" id="how">
          <div className="lp-wrap">
            <p className="lp-eyebrow">How it works</p>
            <h2 className="lp-h2">Three steps, no setup</h2>
            <ol className="lp-steps">
              {STEPS.map(([title, text], i) => (
                <li key={title}>
                  <span className="lp-step-n">{i + 1}</span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="lp-section" id="security">
          <div className="lp-wrap">
            <p className="lp-eyebrow">Security</p>
            <h2 className="lp-h2">Your data stays yours</h2>
            <div className="lp-trust">
              {TRUST.map(({ icon: Icon, title, text }) => (
                <div key={title} className="lp-trust-item">
                  <span className="lp-trust-icon"><Icon size={18} /></span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section lp-alt" id="faq">
          <div className="lp-wrap lp-faq-wrap">
            <div>
              <p className="lp-eyebrow">FAQ</p>
              <h2 className="lp-h2">Questions, answered</h2>
              <p className="lp-lead">Anything else? See the <a href="/privacy">privacy policy</a> and <a href="/terms">terms</a>.</p>
            </div>
            <div className="lp-faq">
              {FAQ.map(([q, a]) => (
                <details key={q}>
                  <summary>{q}<ChevronDown size={18} /></summary>
                  <p>{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-final">
          <div className="lp-wrap lp-final-inner">
            <h2>Open a spreadsheet and see what it’s hiding.</h2>
            <p>It takes a few seconds, and nothing changes until you say so.</p>
            {signedIn ? (
              <button className="lp-btn lp-btn-light lp-btn-lg" onClick={() => inputRef.current?.click()} disabled={uploading}>
                Choose a file <ArrowRight size={16} />
              </button>
            ) : (
              <button className="lp-btn lp-btn-light lp-btn-lg" onClick={start}>
                Get started free <ArrowRight size={16} />
              </button>
            )}
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  )
}
