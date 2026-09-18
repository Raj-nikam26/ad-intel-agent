import { useEffect, useState } from 'react'
import { api } from '../api'

const ROLE_HELP = {
  subject: 'What each row is about. Graph questions are answered about these values.',
  entity: 'An attribute to group and link by.',
  flag: "Mostly blank, where blank means 'no' - not missing data.",
  measure: 'A number to total or compare.',
  date: 'When the row happened.',
  identifier: 'Almost unique per row, so not linked in the graph.',
  text: 'Free text. Checked for blanks, but not linked.',
  empty: 'No values at all.',
}
const CHANGEABLE = ['subject', 'entity', 'flag', 'text']

/**
 * What the app worked out about this file, and a way to correct it.
 *
 * The roles are a guess from the data, and a wrong guess would otherwise
 * be invisible: the graph would link the wrong things and the blank
 * checks would look at the wrong columns. Showing the guess is what makes
 * it safe to open any file.
 */
export default function SchemaPanel({ sessionId, onChanged }) {
  const [mapping, setMapping] = useState(null)
  const [draft, setDraft] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!sessionId) return
    api.mapping(sessionId)
      .then((m) => { setMapping(m); setDraft(m.roles) })
      .catch((e) => setError(e.message))
  }, [sessionId])

  if (error) return <div className="panel-error">{error}</div>
  if (!mapping) return <div className="panel-empty">Reading the file's structure…</div>

  const changed = draft && JSON.stringify(draft) !== JSON.stringify(mapping.roles)

  function setRole(column, role) {
    setDraft((d) => {
      const next = { ...d, [column]: role }
      // Only one column can be the subject.
      if (role === 'subject') {
        for (const key of Object.keys(next)) {
          if (key !== column && next[key] === 'subject') next[key] = 'entity'
        }
      }
      return next
    })
  }

  async function save() {
    setBusy(true); setError(null)
    try {
      const subject = Object.keys(draft).find((c) => draft[c] === 'subject') || null
      const updated = await api.setMapping(sessionId, {
        subject,
        entities: Object.keys(draft).filter((c) => draft[c] === 'entity'),
        flags: Object.keys(draft).filter((c) => draft[c] === 'flag'),
      })
      setMapping(updated)
      setDraft(updated.roles)
      onChanged?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="schema-panel">
      <div className="schema-head">
        <span>
          Worked out from the data itself. Change anything that looks wrong — the graph and the
          blank checks follow these roles.
        </span>
        {changed && (
          <button className="xl-btn" disabled={busy} onClick={save}>
            {busy ? 'Rebuilding…' : 'Apply and rebuild graph'}
          </button>
        )}
      </div>

      <div className="tbl-scroll">
        <table className="hist-table schema-table">
          <thead>
            <tr>
              <th>Column</th><th>Role</th><th>Distinct</th><th>Blank</th><th>Example values</th>
            </tr>
          </thead>
          <tbody>
            {mapping.columns.map((c) => {
              const role = draft[c.name]
              return (
                <tr key={c.name} className={role === 'subject' ? 'current' : ''}>
                  <td className="hist-v">{c.name}</td>
                  <td>
                    <select
                      className="schema-role"
                      value={CHANGEABLE.includes(role) ? role : role}
                      onChange={(e) => setRole(c.name, e.target.value)}
                      title={ROLE_HELP[role]}
                    >
                      {[...new Set([...CHANGEABLE, role])].map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                  <td className="num">{c.distinct.toLocaleString()}</td>
                  <td className="num">{c.missing.toLocaleString()}</td>
                  <td className="schema-ex">{c.examples.join(' · ')}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
