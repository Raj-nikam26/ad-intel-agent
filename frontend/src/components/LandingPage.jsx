import { useRef, useState } from 'react'
import {
  FileSpreadsheet, Zap, Shield, BarChart3, Sparkles,
  Upload, Check, Bot, Database, TrendingUp, ArrowRight,
  Play, Star
} from 'lucide-react'

const FEATURES = [
  {
    icon: Bot,
    title: 'Conversational AI',
    desc: 'Ask questions in plain English. Get instant answers about your data, relationships, and trends.',
    iconBg: 'var(--indigo-50)',
    iconColor: 'var(--indigo-600)',
  },
  {
    icon: FileSpreadsheet,
    title: 'Excel-native Interface',
    desc: 'Familiar spreadsheet UI with column letters, row numbers, sorting and filtering — just like Excel.',
    iconBg: 'var(--green-50)',
    iconColor: 'var(--green-600)',
  },
  {
    icon: Shield,
    title: 'Full Audit Trail',
    desc: 'Every AI change is tracked with a version history. Roll back anytime, compare diffs at a glance.',
    iconBg: 'var(--amber-50)',
    iconColor: 'var(--amber-500)',
  },
  {
    icon: BarChart3,
    title: 'Knowledge Graph',
    desc: 'Visualise relationships between entities as an interactive network — advertisers, categories, offices.',
    iconBg: '#fdf4ff',
    iconColor: '#9333ea',
  },
  {
    icon: Database,
    title: 'Privacy First',
    desc: 'Your files never leave your machine. Zero third-party data sharing. Enterprise-grade privacy by design.',
    iconBg: 'var(--blue-50)',
    iconColor: 'var(--blue-500)',
  },
  {
    icon: TrendingUp,
    title: 'Smart Diagnostics',
    desc: 'Auto-detect missing values, name mismatches, and anomalies. Fix issues with one-click AI suggestions.',
    iconBg: 'var(--green-50)',
    iconColor: 'var(--green-600)',
  },
]

// Fake spreadsheet data for hero visual
const PREVIEW_ROWS = [
  { num: '1', advertiser: 'Sakal Media Group', category: 'News', status: 'ok' },
  { num: '2', advertiser: 'Pune Motors Ltd', category: 'Auto', status: 'normal' },
  { num: '3', advertiser: 'FinEdge Banking', category: 'Finance', status: 'changed' },
  { num: '4', advertiser: 'TechWorld Corp', category: 'Technology', status: 'normal' },
  { num: '5', advertiser: 'BlueChip Retail', category: 'Retail', status: 'ok' },
]

export default function LandingPage({ onUpload, onSample, uploading, error }) {
  const fileRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function handleDrop(e) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) onUpload({ target: { files: [file] } })
  }

  return (
    <div className="landing">
      {/* ── Nav ── */}
      <nav className="landing-nav">
        <div className="nav-inner">
          <div className="nav-logo">
            <div className="logo-icon-wrap">
              <FileSpreadsheet size={18} />
            </div>
            <span className="logo-text">ExcelAI</span>
          </div>

          <div className="nav-links">
            <a href="#features">Features</a>
            <a href="#how-it-works">How it works</a>
            <a href="#upload">Get started</a>
          </div>

          <div className="nav-actions">
            <button className="nav-btn-ghost">Sign in</button>
            <label className="nav-btn-primary" htmlFor="nav-upload-file">
              <Upload size={14} />
              Open Spreadsheet
              <input
                id="nav-upload-file"
                type="file"
                accept=".xlsx,.xls"
                onChange={onUpload}
                disabled={uploading}
                style={{ display: 'none' }}
              />
            </label>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="hero">
        <div className="landing-hero-bg">
          <div className="hero-mesh" />
          <div className="hero-grid" />
        </div>

        <div className="hero-inner">
          {/* Left copy */}
          <div className="hero-content">
            <div className="hero-badge">
              <div className="hero-badge-dot">
                <Sparkles size={10} />
              </div>
              AI-Powered Spreadsheet Intelligence
            </div>

            <h1 className="hero-title">
              Check, query and fix{' '}
              <span className="hero-title-em">your ad data.</span>
            </h1>

            <p className="hero-sub">
              Open a spreadsheet, ask what is wrong with it, and approve fixes one at a time.
              Every change is saved as a version you can restore, with the Excel formula to repeat it yourself.
            </p>

            <div className="hero-actions">
              <label className="btn-primary-lg" htmlFor="hero-upload-file">
                {uploading ? (
                  <>
                    <span className="spinner" />
                    Loading…
                  </>
                ) : (
                  <>
                    <Upload size={17} />
                    Open a Spreadsheet
                  </>
                )}
                <input
                  id="hero-upload-file"
                  type="file"
                  accept=".xlsx,.xls"
                  onChange={onUpload}
                  disabled={uploading}
                  style={{ display: 'none' }}
                />
              </label>

              <button className="btn-secondary-lg" onClick={onSample} disabled={uploading}>
                <Play size={15} />
                Try the sample file
              </button>
            </div>

            <div className="hero-social-proof">
              <span className="proof-text">
                Sample: 11,275 newspaper ad insertions across 16 columns
              </span>
            </div>
            {error && <div className="hero-error">{error}</div>}

            {error && (
              <div className="upload-error" style={{ marginTop: 16 }}>
                ⚠ {error}
              </div>
            )}
          </div>

          {/* Right visual */}
          <div className="hero-visual">
            <div className="hero-spreadsheet-card">
              {/* Fake titlebar */}
              <div className="hsc-titlebar">
                <div className="mac-dots">
                  <span className="mac-dot r" />
                  <span className="mac-dot y" />
                  <span className="mac-dot g" />
                </div>
                <span className="hsc-filename">AdIntelligence_Q3.xlsx</span>
                <span className="hsc-logo">
                  <FileSpreadsheet size={13} />
                  ExcelAI
                </span>
              </div>

              {/* Fake spreadsheet grid */}
              <div className="hsc-body">
                <div className="hsc-row header">
                  <span className="hsc-cell row-num">#</span>
                  <span className="hsc-cell">A · Advertiser</span>
                  <span className="hsc-cell">B · Category</span>
                  <span className="hsc-cell">C · Status</span>
                </div>
                {PREVIEW_ROWS.map((r) => (
                  <div key={r.num} className="hsc-row">
                    <span className="hsc-cell row-num">{r.num}</span>
                    <span className={`hsc-cell${r.status === 'ok' ? ' highlight' : ''}`}>
                      {r.advertiser}
                    </span>
                    <span className="hsc-cell">{r.category}</span>
                    <span className={`hsc-cell${r.status === 'changed' ? ' changed' : ''}`}>
                      {r.status === 'ok' ? '✓ Active' : r.status === 'changed' ? '⟳ Updated' : '—'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Floating AI badge */}
            <div className="hsc-ai-badge">
              <div className="ai-badge-icon">
                <Bot size={18} />
              </div>
              <div className="ai-badge-text">
                <p>AI found 3 issues</p>
                <span>2 missing categories · 1 duplicate</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Logos bar ── */}
      <div className="logos-bar">
        <div className="logos-inner">
          <span className="logos-label">Trusted by teams at</span>
          <div className="logos-list">
            {['Sakal Media', 'PuneEdge Corp', 'FinAxis Group', 'NextGen Analytics', 'DataBridge Inc'].map((l) => (
              <span key={l} className="logo-badge">{l}</span>
            ))}
          </div>
        </div>
      </div>

      {/* ── Features ── */}
      <section className="section" id="features">
        <div className="section-inner">
          <div className="section-header">
            <div className="eyebrow">
              <Zap size={13} />
              Features
            </div>
            <h2 className="section-title">Everything you need to master your data</h2>
            <p className="section-sub">
              Built for analysts, operations teams, and data-driven businesses.
              No training required — if you can use Excel, you can use ExcelAI.
            </p>
          </div>

          <div className="features-grid">
            {FEATURES.map((f) => (
              <div key={f.title} className="feature-card">
                <div
                  className="feature-icon"
                  style={{ '--icon-bg': f.iconBg, '--icon-color': f.iconColor, background: f.iconBg, color: f.iconColor }}
                >
                  <f.icon size={22} />
                </div>
                <h3 className="feature-title">{f.title}</h3>
                <p className="feature-desc">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Upload zone ── */}
      <section className="section upload-section" id="upload">
        <div className="section-inner">
          <div className="section-header">
            <div className="eyebrow">
              <Upload size={13} />
              Get Started Free
            </div>
            <h2 className="section-title">Drop your spreadsheet and go</h2>
            <p className="section-sub">No signup. No credit card. Your data stays on your device.</p>
          </div>

          <div
            className={`upload-hero-zone${dragging ? ' dragging' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <div className="upload-icon-ring">
              <FileSpreadsheet size={36} />
            </div>
            <h3 className="upload-zone-title">
              {uploading ? 'Loading your spreadsheet…' : 'Drop your file here'}
            </h3>
            <p className="upload-zone-sub">
              {uploading
                ? 'Analysing structure and preparing your AI workspace…'
                : 'Supports .xlsx and .xls files · Up to any size · Your data never leaves this device'}
            </p>

            <label className="upload-btn-main" htmlFor="zone-upload-file">
              {uploading ? (
                <>
                  <span className="spinner-green" />
                  Processing…
                </>
              ) : (
                <>
                  <Upload size={16} />
                  Select File
                </>
              )}
              <input
                id="zone-upload-file"
                type="file"
                accept=".xlsx,.xls"
                onChange={onUpload}
                disabled={uploading}
                style={{ display: 'none' }}
              />
            </label>

            <div className="upload-trust">
              {['No signup required', 'Files stay on your device', '100% free'].map((t) => (
                <span key={t} className="trust-pill">
                  <Check size={12} />
                  {t}
                </span>
              ))}
            </div>

            {error && <div className="upload-error">{error}</div>}
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="section how-section" id="how-it-works">
        <div className="section-inner">
          <div className="section-header">
            <div className="eyebrow">
              <ArrowRight size={13} />
              How It Works
            </div>
            <h2 className="section-title">From raw file to clean insights in minutes</h2>
            <p className="section-sub">Three steps. Zero complexity. Maximum impact.</p>
          </div>

          <div className="steps-grid">
            {[
              { n: '1', title: 'Upload your file', desc: 'Drop any .xlsx or .xls spreadsheet. No pre-processing needed — ExcelAI reads your file exactly as-is.' },
              { n: '2', title: 'Chat with your data', desc: 'Ask questions in plain English. The AI uses tools to query tables, traverse relationships, and detect issues.' },
              { n: '3', title: 'Export clean data', desc: 'Download your improved dataset with a full changelog and version history — audit-ready from day one.' },
            ].map((s) => (
              <div key={s.n} className="step-card">
                <div className="step-number">{s.n}</div>
                <h3 className="step-title">{s.title}</h3>
                <p className="step-desc">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="cta-section">
        <div className="cta-inner">
          <h2 className="cta-title">Ready to make your data work smarter?</h2>
          <p className="cta-sub">
            Upload a spreadsheet and experience ExcelAI in 30 seconds — no account needed.
          </p>
          <label className="cta-btn" htmlFor="cta-upload-file">
            <FileSpreadsheet size={18} />
            Get Started Free
            <input
              id="cta-upload-file"
              type="file"
              accept=".xlsx,.xls"
              onChange={onUpload}
              disabled={uploading}
              style={{ display: 'none' }}
            />
          </label>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="landing-footer">
        <div className="footer-inner">
          <div className="footer-logo">
            <div className="footer-logo-icon">
              <FileSpreadsheet size={14} />
            </div>
            <span className="footer-logo-text">ExcelAI</span>
          </div>
          <div className="footer-links">
            <a href="#">Privacy Policy</a>
            <a href="#">Terms of Service</a>
            <a href="#">Documentation</a>
            <a href="#">Contact</a>
          </div>
          <span className="footer-copy">© 2026 ExcelAI. All rights reserved.</span>
        </div>
      </footer>
    </div>
  )
}
