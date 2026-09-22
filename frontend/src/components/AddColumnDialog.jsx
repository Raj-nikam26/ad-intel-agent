import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api'

const FILLS = [
  { id: 'formula', label: 'Calculated from other columns' },
  { id: 'value', label: 'Same value in every row' },
  { id: 'copy', label: 'Copy of another column' },
  { id: 'empty', label: 'Empty' },
]

const ref = (c) => `[${c}]`

/**
 * Adds a column through the same audited edit path as the assistant, so
 * the change is a new version that shows in History and can be undone.
 * Calculated columns use a small Excel-like formula language that the
 * server parses and checks; it is never run as code.
 */
export default function AddColumnDialog({ sessionId, columns, onClose, onAdded }) {
  const [name, setName] = useState('')
  const [fill, setFill] = useState('formula')
  const [formula, setFormula] = useState('')
  const [value, setValue] = useState('')
  const [source, setSource] = useState(columns[0] || '')
  const [after, setAfter] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null)   // { values } | { error }
  const nameRef = useRef(null)
  const formulaRef = useRef(null)

  useEffect(() => {
    nameRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const trimmed = name.trim()
  const clash = columns.some((c) => c.trim().toLowerCase() === trimmed.toLowerCase())
  const payload = {
    name: trimmed || 'Preview',
    value: fill === 'value' ? value : null,
    sourceColumn: fill === 'copy' ? source : null,
    formula: fill === 'formula' ? formula : null,
    afterColumn: after || null,
  }

  // Live preview of the first rows while a formula is typed.
  useEffect(() => {
    if (fill !== 'formula' || !formula.trim()) { setPreview(null); return undefined }
    const t = setTimeout(async () => {
      try {
        const res = await api.addColumn(sessionId, { ...payload, name: clash || !trimmed ? '__preview__' : trimmed, dryRun: true })
        setPreview({ values: res.preview })
      } catch (err) {
        setPreview({ error: err.message })
      }
    }, 350)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formula, fill, sessionId])

  const valid = trimmed && !clash
    && (fill !== 'value' || value.trim())
    && (fill !== 'copy' || source)
    && (fill !== 'formula' || (formula.trim() && !preview?.error))

  function insert(col) {
    const el = formulaRef.current
    const token = ref(col)
    if (!el) { setFormula((f) => f + token); return }
    const start = el.selectionStart ?? formula.length
    const end = el.selectionEnd ?? formula.length
    const next = formula.slice(0, start) + token + formula.slice(end)
    setFormula(next)
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + token.length, start + token.length)
    })
  }

  async function submit(e) {
    e.preventDefault()
    if (!valid || saving) return
    setSaving(true); setError(null)
    try {
      onAdded(await api.addColumn(sessionId, payload))
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  const show = (v) => (v === null || v === undefined || v === '' ? '∅' : String(v))

  return (
    <div className="ws-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <form className="ws-modal" role="dialog" aria-modal="true" aria-labelledby="add-col-title" onSubmit={submit}>
        <header className="ws-modal-head">
          <h2 id="add-col-title">Add a column</h2>
          <button type="button" className="ws-icon-btn sm" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </header>

        <label className="ws-field">
          <span>Column name</span>
          <input ref={nameRef} value={name} onChange={(e) => setName(e.target.value)} maxLength={100}
                 placeholder="e.g. Perimeter" aria-invalid={clash} />
          {clash && <small className="ws-field-err">A column with this name already exists.</small>}
        </label>

        <fieldset className="ws-field">
          <legend>Fill it with</legend>
          <div className="ws-choice">
            {FILLS.map((f) => (
              <label key={f.id} className={fill === f.id ? 'on' : ''}>
                <input type="radio" name="fill" value={f.id} checked={fill === f.id} onChange={() => setFill(f.id)} />
                {f.label}
              </label>
            ))}
          </div>
        </fieldset>

        {fill === 'formula' && (
          <div className="ws-field">
            <label htmlFor="add-col-formula"><span>Formula</span></label>
            <input id="add-col-formula" ref={formulaRef} className="ws-mono-input" value={formula}
                   onChange={(e) => setFormula(e.target.value)} placeholder="e.g. 2 * ([Width] + [Height])"
                   aria-describedby="add-col-help" spellCheck={false} />
            <div className="ws-col-chips" aria-label="Insert a column">
              {columns.map((c) => (
                <button type="button" key={c} onClick={() => insert(c)} title={`Insert ${ref(c)}`}>{c}</button>
              ))}
            </div>
            <small id="add-col-help" className="ws-help">
              Click a column to insert it. Use + − * / ^, & to join text, and ROUND, ABS, MIN, MAX, SQRT, MOD.
            </small>
            {preview?.error && <small className="ws-field-err" role="alert">{preview.error}</small>}
            {preview?.values && (
              <div className="ws-preview">
                <span>First rows:</span>
                {preview.values.map((v, i) => <code key={i}>{show(v)}</code>)}
              </div>
            )}
          </div>
        )}
        {fill === 'value' && (
          <label className="ws-field">
            <span>Value</span>
            <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="e.g. Pending" />
          </label>
        )}
        {fill === 'copy' && (
          <label className="ws-field">
            <span>Copy values from</span>
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              {columns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        )}

        <label className="ws-field">
          <span>Position</span>
          <select value={after} onChange={(e) => setAfter(e.target.value)}>
            <option value="">At the end</option>
            {columns.map((c) => <option key={c} value={c}>After {c}</option>)}
          </select>
        </label>

        <p className="ws-modal-note">Saved as a new version — you can undo it from History.</p>
        {error && <p className="ws-field-err" role="alert">{error}</p>}

        <footer className="ws-modal-foot">
          <button type="button" className="ws-btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="ws-btn primary" disabled={!valid || saving}>
            {saving ? 'Adding…' : 'Add column'}
          </button>
        </footer>
      </form>
    </div>
  )
}
