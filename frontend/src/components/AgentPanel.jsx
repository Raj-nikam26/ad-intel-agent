import { useEffect, useRef } from 'react'
import { Bot, X, Send, Sparkles } from 'lucide-react'

const TOOL_LABEL = {
  detect_issues:                          'Scanned for issues',
  get_advertiser_summary:                 'Graph lookup — advertiser',
  find_advertisers_by_category_and_office:'Graph traversal — office × category',
  tabular_query:                          'Table query',
  apply_edit:                             'Applied edit',
}

const SUGGESTIONS = [
  'What data quality issues exist in this file?',
  'Which advertisers in Pune handle Bank/Finance ads?',
  'Summarise Sakal Media Group across all publications',
  'How many rows are missing a Category value?',
]

/**
 * AI Assistant panel — slides in from the right.
 * Indigo-accented, premium chat interface.
 */
export default function AgentPanel({
  messages, input, setInput, onSend, loading, agentConfigured, inputRef, onClose, onShowFormula,
}) {
  const bottomRef = useRef(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  return (
    <div className="agent-panel">
      {/* ── Header ── */}
      <div className="agent-head">
        <div className="agent-title-group">
          <div className="agent-avatar">
            <Bot size={17} />
          </div>
          <div className="agent-info">
            <div className="agent-title">AI Assistant</div>
            <div className="agent-sub">
              <span className={`agent-status-dot${agentConfigured ? '' : ' offline'}`} />
              {agentConfigured ? 'Ready · Powered by OpenRouter' : 'No API key configured'}
            </div>
          </div>
        </div>

        {!agentConfigured && (
          <span className="agent-warn" title="Set OPENROUTER_API_KEY in backend/.env">
            No key
          </span>
        )}

        <button className="agent-close-btn" onClick={onClose} title="Close assistant">
          <X size={16} />
        </button>
      </div>

      {/* ── Messages ── */}
      <div className="agent-messages">
        {messages.length === 0 && (
          <div className="agent-suggestions">
            <p className="suggestions-label">
              Ask a question or request a change to your data:
            </p>
            <div className="suggestion-list">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="suggestion-btn"
                  onClick={() => setInput(s)}
                >
                  <Sparkles size={13} className="suggestion-icon" />
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role !== 'system' && (
              <div className="msg-role">
                {m.role === 'user' ? 'You' : 'AI Assistant'}
              </div>
            )}
            <div className="msg-text">{m.text}</div>

            {m.toolCalls?.length > 0 && (
              <div className="tool-trace">
                {m.toolCalls.map((tc, j) => {
                  const isEdit = tc.name === 'apply_edit'
                  const failed = tc.result?.error
                  return (
                    <details
                      key={j}
                      className={`tool-call${isEdit ? ' edit' : ''}${failed ? ' failed' : ''}`}
                    >
                      <summary>
                        <span className="tool-dot" />
                        {TOOL_LABEL[tc.name] || tc.name}
                        {isEdit && tc.result?.rows_affected != null && (
                          <span className="tool-badge">
                            {tc.result.rows_affected} rows → v{tc.result.version}
                          </span>
                        )}
                        {failed && <span className="tool-badge err">failed</span>}
                      </summary>
                      <pre>{JSON.stringify(tc.arguments, null, 2)}</pre>
                      {tc.result && (
                        <pre className="tool-result">
                          {JSON.stringify(tc.result, null, 2).slice(0, 2000)}
                        </pre>
                      )}
                    </details>
                  )
                })}
              </div>
            )}

            {m.versionBadge != null && (
              <div className="msg-version">Data updated to v{m.versionBadge}</div>
            )}
            {m.toolCalls?.some((t) => t.excel?.items?.length) && (
              <button className="msg-fx" onClick={() => onShowFormula(m)}>
                fx&nbsp; Show how to do this in Excel
              </button>
            )}
          </div>
        ))}

        {loading && (
          <div className="msg assistant">
            <div className="msg-role">AI Assistant</div>
            <div className="thinking">
              <span /><span /><span />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Input ── */}
      <div className="agent-input">
        <div className="agent-input-row">
          <textarea
            ref={inputRef}
            rows={2}
            placeholder={
              agentConfigured
                ? 'Ask a question or request a data change…'
                : 'Set OPENROUTER_API_KEY in backend/.env to enable'
            }
            value={input}
            disabled={!agentConfigured}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                onSend()
              }
            }}
          />
          <button
            className="agent-send-btn"
            onClick={onSend}
            disabled={loading || !agentConfigured || !input.trim()}
            title="Send message (Enter)"
          >
            {loading ? (
              <span className="spinner" style={{ borderTopColor: 'white' }} />
            ) : (
              <Send size={15} />
            )}
          </button>
        </div>
        <div className="agent-input-hint">Enter to send · Shift+Enter for new line</div>
      </div>
    </div>
  )
}
