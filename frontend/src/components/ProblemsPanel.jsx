import { useEffect, useState } from 'react'
import { api } from '../api'

const TYPE_LABEL = {
  missing_value: 'Missing values',
  name_mismatch: 'Name mismatch',
  near_duplicate_advertiser: 'Near-duplicate advertiser',
}

const TYPE_SEVERITY = {
  missing_value: 'error',
  name_mismatch: 'warn',
  near_duplicate_advertiser: 'info',
}

/**
 * The Problems panel, modelled on an IDE's error list: each row is a
 * finding you click to navigate to, not a paragraph you read.
 *
 * `Ask the agent to fix this` deliberately does NOT call an edit
 * endpoint directly. It drafts a message into the chat box for the user
 * to review and send. The whole safety model of this project is that
 * data only changes when a person explicitly asks in conversation and
 * the request is audited with a reason - a one-click "fix" button in the
 * UI would route around that, and would make the audit log's `reason`
 * field a lie.
 */
export default function ProblemsPanel({ sessionId, version, onSelectIssue, selectedScope, onDraftMessage }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [typeFilter, setTypeFilter] = useState('all')

  useEffect(() => {
    if (!sessionId) return
    setLoading(true); setError(null)
    api.issues(sessionId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [sessionId, version])

  if (loading && !data) return <div className="panel-empty">scanning for issues…</div>
  if (error) return <div className="panel-error">{error}</div>
  if (!data) return null

  const shown = data.issues.filter((i) => typeFilter === 'all' || i.issue_type === typeFilter)

  return (
    <div className="problems">
      <div className="problems-filters">
        <button className={typeFilter === 'all' ? 'active' : ''} onClick={() => setTypeFilter('all')}>
          All <b>{data.total_issues}</b>
        </button>
        {Object.entries(data.counts_by_type).map(([t, n]) => (
          <button key={t} className={typeFilter === t ? 'active' : ''} onClick={() => setTypeFilter(t)}>
            <span className={`sev ${TYPE_SEVERITY[t] || 'info'}`} />
            {TYPE_LABEL[t] || t} <b>{n}</b>
          </button>
        ))}
        {loading && <span className="problems-refreshing">re-scanning…</span>}
      </div>

      <div className="problems-list">
        {shown.length === 0 && <div className="panel-empty">No issues of this type.</div>}
        {shown.map((issue, i) => {
          const selected = selectedScope === issue.scope
          const isMissing = issue.issue_type === 'missing_value'
          const column = isMissing ? issue.scope.replace('column:', '') : null
          return (
            <div
              key={`${issue.scope}-${i}`}
              className={`problem${selected ? ' selected' : ''}`}
              onClick={() => onSelectIssue(issue)}
            >
              <span className={`sev ${TYPE_SEVERITY[issue.issue_type] || 'info'}`} />
              <div className="problem-body">
                <div className="problem-desc">{issue.description}</div>
                <div className="problem-meta">
                  <code>{issue.scope}</code>
                  <span>{issue.total_rows_affected.toLocaleString()} rows</span>
                </div>
              </div>
              <button
                className="problem-action"
                onClick={(e) => {
                  e.stopPropagation()
                  onDraftMessage(
                    isMissing
                      ? `Fix all ${issue.total_rows_affected} rows missing a value in "${column}" — set them to `
                      : `About ${issue.scope}: ${issue.description} Please fix this by `,
                  )
                }}
                title="Draft a fix request into the agent chat (you review and send it)"
              >
                Ask agent to fix →
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
