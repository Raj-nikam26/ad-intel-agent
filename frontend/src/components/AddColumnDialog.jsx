import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api'

const FILLS = [
  { id: 'empty', label: 'Empty' },
  { id: 'value', label: 'Same value in every row' },
  { id: 'copy', label: 'Copy of another column' },
]

/**
 * Adds a column through the same audited edit path as the assistant, so
 * the change is a new version that shows in History and can be undone.
 */
export default function AddColumnDialog({ sessionId, columns, onClose, onAdded }) {
  const [name, setName] = useState('')
  const [fill, setFill] = useState('empty')
  const [value, setValue] = useState('')
  const [source, setSource] = useState(columns[0] || '')
  const [after, setAfter] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const nameRef = useRef(null)

  useEffect(() => {
    nameRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const trimmed = name.trim()
  const clash = columns.some((c) => c.trim().toLowerCase() === trimmed.toLowerCase())
  const valid = trimmed && !clash && (fill !== 'value' || value.trim()) && (fill !== 'copy' || source)

  async function submit(e) {
    e.preventDefault()
    if (!valid || saving) return
    setSaving(true); setError(null)
    try {
      const res = await api.addColumn(sessionId, {
        name: trimmed,
        value: fill === 'value' ? value : null,
        sourceColumn: fill === 'copy' ? source : null,
        afterColumn: after || null,
      })
      onAdded(res)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

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
                 placeholder="e.g. Review status" aria-invalid={clash} />
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
