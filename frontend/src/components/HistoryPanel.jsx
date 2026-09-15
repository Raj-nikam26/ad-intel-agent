import { useEffect, useState } from 'react'
import { api } from '../api'

const fmtTime = (ts) =>
  new Date(ts * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

const OP_LABEL = {
  fill_missing_value: 'Filled blanks',
  fill_missing_value_bulk: 'Filled all blanks',
  standardize_value: 'Changed values',
  flag_rows: 'Flagged rows',
  restore: 'Restored',
}

/**
 * Version history. Nothing here is ever deleted: restoring an old version
 * adds a new one on top, so every step stays visible and can itself be
 * undone.
 */
export default function HistoryPanel({ sessionId, version, selectedVersion, onSelectVersion, onRestored, onShowFormula }) {
  const [hist, setHist] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!sessionId) return
    api.history(sessionId).then(setHist).catch((e) => setError(e.message))
  }, [sessionId, version])

  if (error) return <div className="panel-error">{error}</div>
  if (!hist) return <div className="panel-empty">Loading history…</div>

  async function restore(to) {
    setBusy(to); setError(null)
    try {
      const res = await api.revert(sessionId, to)
      onRestored(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const rows = [
    ...[...hist.audit_log].reverse(),
    { version: 0, operation: 'original', scope: '', rows_affected: 0, reason: 'File as uploaded' },
  ]

  return (
    <table className="hist-table">
      <thead>
        <tr>
          <th>Version</th><th>Change</th><th>Rows</th><th>Why</th><th>When</th><th />
        </tr>
      </thead>
      <tbody>
        {rows.map((e) => {
          const isCurrent = e.version === version
          const label = e.operation === 'original'
            ? 'Original file'
            : `${OP_LABEL[e.operation] || e.operation}${e.scope ? ` · ${e.scope}` : ''}`
          return (
            <tr
              key={e.version}
              className={`${isCurrent ? 'current' : ''}${selectedVersion === e.version ? ' selected' : ''}`}
              onClick={() => onSelectVersion(e.version)}
            >
              <td className="hist-v">
                v{e.version}
                {isCurrent && <span className="hist-badge">current</span>}
              </td>
              <td>{label}</td>
              <td className="num">{e.version === 0 ? '—' : e.rows_affected.toLocaleString()}</td>
              <td className="hist-why" title={e.reason}>{e.reason}</td>
              <td className="hist-when">{e.timestamp ? fmtTime(e.timestamp) : ''}</td>
              <td className="hist-actions" onClick={(ev) => ev.stopPropagation()}>
                {e.excel && (
                  <button className="link-btn" onClick={() => onShowFormula(e)}>Excel steps</button>
                )}
                {!isCurrent && (
                  <button className="xl-btn" disabled={busy !== null} onClick={() => restore(e.version)}>
                    {busy === e.version ? 'Restoring…' : 'Restore'}
                  </button>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
