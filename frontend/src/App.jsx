import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import DataGrid from './components/DataGrid'
import GraphPanel from './components/GraphPanel'
import ProblemsPanel from './components/ProblemsPanel'
import HistoryPanel from './components/HistoryPanel'
import AgentPanel from './components/AgentPanel'
import Splitter from './components/Splitter'
import LandingPage from './components/LandingPage'
import FormulaPanel from './components/FormulaPanel'

const SESSION_KEY = 'adintel.session'

const colLetter = (idx) => {
  let s = ''
  for (let n = idx + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s
  return s
}

// The latest tool call in a reply that has an Excel equivalent.
const formulaFrom = (toolCalls, label) => {
  const tc = [...(toolCalls || [])].reverse().find((t) => t.excel?.items?.length)
  return tc ? { label, excel: tc.excel } : null
}
import {
  FileSpreadsheet, Download, MessageSquare, X,
} from 'lucide-react'

/**
 * ExcelAI — IDE shell.
 *
 * Layout: Excel-style grid occupies the main canvas.
 * The AI chat panel slides in from the right on demand.
 * Landing page replaces the bare upload card.
 */
export default function App() {
  const [session, setSession] = useState(null)
  const [version, setVersion] = useState(0)
  const [agentConfigured, setAgentConfigured] = useState(true)

  const [mainTab, setMainTab] = useState('data')         // data | graph
  const [bottomTab, setBottomTab] = useState('problems') // problems | history
  const [bottomOpen, setBottomOpen] = useState(true)

  const [chatOpen, setChatOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatInputRef = useRef(null)

  const [query, setQuery] = useState('')
  const [queryDraft, setQueryDraft] = useState('')
  const [filterColumn, setFilterColumn] = useState('')
  const [missingOnly, setMissingOnly] = useState(false)
  const [sortBy, setSortBy] = useState('')
  const [sortDir, setSortDir] = useState('asc')

  const [highlightRows, setHighlightRows] = useState(null)
  const [selectedScope, setSelectedScope] = useState(null)
  const [changedCells, setChangedCells] = useState(new Set())
  const [changeSummary, setChangeSummary] = useState(null)
  const [selectedVersion, setSelectedVersion] = useState(0)
  const [gridStats, setGridStats] = useState({ total: 0, filtered: 0 })
  const [focusedCell, setFocusedCell] = useState(null)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [formulaEntry, setFormulaEntry] = useState(null)
  const [restoring, setRestoring] = useState(() => {
    try { return !!localStorage.getItem(SESSION_KEY) } catch { return false }
  })

  const [chatWidth] = useState(380)
  const [bottomHeight, setBottomHeight] = useState(200)

  useEffect(() => {
    api.health()
      .then((h) => setAgentConfigured(h.agent_configured))
      .catch(() => setAgentConfigured(false))
  }, [])

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setQuery(queryDraft), 250)
    return () => clearTimeout(t)
  }, [queryDraft])

  function openSession(data) {
    setSession(data)
    setVersion(data.current_version || 0)
    setSelectedVersion(data.current_version || 0)
    setMessages(data.transcript || [])
    setChangedCells(new Set())
    setChangeSummary(null)
    const lastWithFormula = [...(data.transcript || [])].reverse()
      .map((m) => formulaFrom(m.toolCalls, m.text?.slice(0, 80)))
      .find(Boolean)
    setFormulaEntry(lastWithFormula || null)
    try { localStorage.setItem(SESSION_KEY, data.session_id) } catch { /* private mode */ }
  }

  // Reopen the last session after a reload - it is saved on the server.
  useEffect(() => {
    let id = null
    try { id = localStorage.getItem(SESSION_KEY) } catch { /* ignore */ }
    if (!id) return
    api.session(id)
      .then(openSession)
      .catch(() => { try { localStorage.removeItem(SESSION_KEY) } catch { /* ignore */ } })
      .finally(() => setRestoring(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function start(loader) {
    setUploading(true); setError(null)
    try {
      openSession(await loader())
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  function handleUpload(e) {
    const file = e.target.files[0]
    if (file) start(() => api.upload(file))
  }

  function closeFile() {
    try { localStorage.removeItem(SESSION_KEY) } catch { /* ignore */ }
    setSession(null)
  }

  const loadDiff = useCallback(async (v) => {
    if (!session) return
    try {
      const d = await api.diff(session.session_id, v)
      setChangedCells(new Set(d.changed_cells.map((c) => `${c.row}::${c.column}`)))
      setChangeSummary(
        d.changed_cell_count
          ? { cells: d.changed_cell_count, rows: d.changed_row_count, version: v }
          : null,
      )
    } catch {
      setChangedCells(new Set())
      setChangeSummary(null)
    }
  }, [session])

  async function sendMessage() {
    const text = input.trim()
    if (!text || !session || chatLoading) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text }])
    setChatLoading(true); setError(null)
    try {
      const res = await api.chat(session.session_id, text)
      setMessages((m) => [...m, {
        role: 'assistant',
        text: res.reply,
        toolCalls: res.tool_calls,
        versionBadge: res.data_changed ? res.version : null,
      }])
      const fx = formulaFrom(res.tool_calls, text.slice(0, 80))
      if (fx) {
        setFormulaEntry(fx)
        setBottomTab('excel')
        setBottomOpen(true)
      }
      if (res.data_changed) {
        setVersion(res.version)
        setSelectedVersion(res.version)
        await loadDiff(res.version)
        if (!fx) { setBottomTab('history'); setBottomOpen(true) }
      }
    } catch (err) {
      setError(err.message)
      setMessages((m) => [...m, { role: 'system', text: `Error: ${err.message}` }])
    } finally {
      setChatLoading(false)
    }
  }

  function selectIssue(issue) {
    setSelectedScope(issue.scope)
    setHighlightRows(issue.row_indices)
    setMainTab('data')
    setQueryDraft(''); setQuery(''); setFilterColumn(''); setMissingOnly(false)
  }

  function draftMessage(text) {
    setInput(text)
    setChatOpen(true)
    chatInputRef.current?.focus()
    requestAnimationFrame(() => {
      const el = chatInputRef.current
      if (el) el.setSelectionRange(el.value.length, el.value.length)
    })
  }

  function onSortChange(col) {
    if (sortBy === col) {
      if (sortDir === 'asc') setSortDir('desc')
      else { setSortBy(''); setSortDir('asc') }
    } else {
      setSortBy(col); setSortDir('asc')
    }
  }

  async function onRestored(res) {
    setVersion(res.current_version)
    setSelectedVersion(res.current_version)
    await loadDiff(res.current_version)
  }

  function showFormula(entry, label) {
    setFormulaEntry({ label, excel: entry })
    setBottomTab('excel')
    setBottomOpen(true)
  }

  // ─── Landing page ───────────────────────────────────────────────
  if (!session) {
    if (restoring) return <div className="boot">Opening your last file…</div>
    return (
      <LandingPage
        onUpload={handleUpload}
        onSample={() => start(api.sample)}
        uploading={uploading}
        error={error}
      />
    )
  }

  // ─── IDE ────────────────────────────────────────────────────────
  const fileName = session.filename || 'Spreadsheet.xlsx'

  return (
    <div className="ide">
      {/* ── Ribbon / Toolbar ── */}
      <header className="titlebar">
        <div className="titlebar-top">
          {/* Logo */}
          <div className="tb-app-logo">
            <FileSpreadsheet size={17} />
            <span className="tb-app-name">ExcelAI</span>
          </div>

          {/* File info */}
          <div className="tb-left">
            <span className="tb-filename" title={fileName}>{fileName}</span>
            <span className={`tb-version${version > 0 ? ' edited' : ''}`}>
              v{version}{version === 0 ? ' · original' : ' · edited'}
            </span>
          </div>

          {/* Name box + formula bar */}
          <div className="tb-center">
            <span className="tb-namebox" title="Selected cell">
              {focusedCell
                ? `${colLetter(session.columns.indexOf(focusedCell.column))}${focusedCell.row + 2}`
                : ''}
            </span>
            <span className="tb-formula-label">fx</span>
            {focusedCell && (
              <span className="tb-cellvalue" title={String(focusedCell.value ?? '')}>
                {focusedCell.value ?? ''}
              </span>
            )}
            <input
              className="tb-search"
              placeholder="Search all columns…"
              value={queryDraft}
              onChange={(e) => setQueryDraft(e.target.value)}
            />
            <select
              className="tb-col-select"
              value={filterColumn}
              onChange={(e) => setFilterColumn(e.target.value)}
            >
              <option value="">All columns</option>
              {session.columns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <label className={`tb-toggle${missingOnly ? ' on' : ''}`} title="Show rows with missing values only">
              <input
                type="checkbox"
                checked={missingOnly}
                disabled={!filterColumn}
                onChange={(e) => setMissingOnly(e.target.checked)}
              />
              Missing only
            </label>
            {(highlightRows || query || missingOnly || sortBy) && (
              <button
                className="tb-clear"
                onClick={() => {
                  setHighlightRows(null); setSelectedScope(null)
                  setQueryDraft(''); setQuery(''); setFilterColumn('')
                  setMissingOnly(false); setSortBy(''); setSortDir('asc')
                }}
              >
                Clear filters
              </button>
            )}
          </div>

          {/* Right actions */}
          <div className="tb-right">
            <button className="tb-close" onClick={closeFile} title="Close this file and open another">
              Close file
            </button>
            <a className="tb-export" href={api.exportUrl(session.session_id)}>
              <Download size={13} />
              Export v{version}
            </a>
            <button
              className={`tb-chat-toggle${chatOpen ? ' active' : ''}`}
              onClick={() => setChatOpen((o) => !o)}
              title={chatOpen ? 'Hide AI Assistant' : 'Open AI Assistant'}
            >
              <MessageSquare size={13} />
              AI Assistant
            </button>
          </div>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="ide-body">
        <div className="ide-main">
          {/* Tab bar */}
          <div className="tabbar">
            <button className={mainTab === 'data' ? 'active' : ''} onClick={() => setMainTab('data')}>
              Data
              <span className="tab-count">{gridStats.filtered.toLocaleString()}</span>
            </button>
            <button className={mainTab === 'graph' ? 'active' : ''} onClick={() => setMainTab('graph')}>
              Knowledge Graph
            </button>
            {highlightRows && (
              <span className="tab-filterchip">
                {highlightRows.length.toLocaleString()} rows from <code>{selectedScope}</code>
              </span>
            )}
            {changeSummary && (
              <span className="tab-changechip">
                v{changeSummary.version}: {changeSummary.cells.toLocaleString()} cells changed
              </span>
            )}
          </div>

          {/* Editor */}
          <div
            className="editor-area"
            style={{ height: bottomOpen ? `calc(100% - ${bottomHeight}px - 34px)` : 'calc(100% - 34px)' }}
          >
            {mainTab === 'data' ? (
              <DataGrid
                sessionId={session.session_id}
                version={version}
                columnMeta={session.column_meta}
                changedCells={changedCells}
                highlightRows={highlightRows}
                query={query}
                filterColumn={filterColumn}
                missingOnly={missingOnly}
                sortBy={sortBy}
                sortDir={sortDir}
                onSortChange={onSortChange}
                onStatsChange={setGridStats}
                onCellFocus={setFocusedCell}
              />
            ) : (
              <GraphPanel sessionId={session.session_id} version={version} />
            )}
          </div>

          {/* Horizontal splitter */}
          {bottomOpen && (
            <Splitter
              orientation="horizontal"
              onResize={(y) =>
                setBottomHeight(Math.max(100, Math.min(window.innerHeight - 200, window.innerHeight - y)))
              }
            />
          )}

          {/* Bottom panel */}
          <div className="bottom-panel" style={{ height: bottomOpen ? bottomHeight : 30 }}>
            <div className="tabbar sub">
              <button
                className={bottomTab === 'problems' ? 'active' : ''}
                onClick={() => { setBottomTab('problems'); setBottomOpen(true) }}
              >
                Problems
              </button>
              <button
                className={bottomTab === 'history' ? 'active' : ''}
                onClick={() => { setBottomTab('history'); setBottomOpen(true) }}
              >
                History
              </button>
              <button
                className={bottomTab === 'excel' ? 'active' : ''}
                onClick={() => { setBottomTab('excel'); setBottomOpen(true) }}
              >
                Do it in Excel
              </button>
              <button className="panel-collapse" onClick={() => setBottomOpen((o) => !o)}>
                {bottomOpen ? '▾' : '▴'}
              </button>
            </div>
            {bottomOpen && (
              <div className="bottom-content">
                {bottomTab === 'problems' ? (
                  <ProblemsPanel
                    sessionId={session.session_id}
                    version={version}
                    onSelectIssue={selectIssue}
                    selectedScope={selectedScope}
                    onDraftMessage={draftMessage}
                  />
                ) : bottomTab === 'history' ? (
                  <HistoryPanel
                    sessionId={session.session_id}
                    version={version}
                    selectedVersion={selectedVersion}
                    onSelectVersion={(v) => { setSelectedVersion(v); loadDiff(v) }}
                    onRestored={onRestored}
                    onShowFormula={(e) => showFormula(e.excel, `v${e.version} · ${e.reason}`)}
                  />
                ) : (
                  <FormulaPanel entry={formulaEntry} />
                )}
              </div>
            )}
          </div>
        </div>

        {/* ── Slide-in Chat Panel ── */}
        <div
          className={`ide-side${chatOpen ? ' chat-open' : ''}`}
          style={{ width: chatWidth }}
        >
          <AgentPanel
            messages={messages}
            input={input}
            setInput={setInput}
            onSend={sendMessage}
            loading={chatLoading}
            agentConfigured={agentConfigured}
            inputRef={chatInputRef}
            onClose={() => setChatOpen(false)}
            onShowFormula={(m) => {
              const fx = formulaFrom(m.toolCalls, m.text?.slice(0, 80))
              if (fx) showFormula(fx.excel, fx.label)
            }}
          />
        </div>
      </div>

      {/* ── Status bar ── */}
      <footer className="statusbar">
        <span className="sb-item">
          {session.row_count.toLocaleString()} rows × {session.column_count} cols
        </span>
        <span className="sb-item">
          {gridStats.filtered.toLocaleString()} shown
        </span>
        <span className={`sb-item${version > 0 ? ' accent' : ''}`}>
          Version {version}
        </span>
        {changeSummary && (
          <span className="sb-item accent">
            {changeSummary.cells.toLocaleString()} cells changed in v{changeSummary.version}
          </span>
        )}
        {focusedCell && (
          <span className="sb-item mono">
            Row {focusedCell.row} · {focusedCell.column} = {focusedCell.value ?? '∅'}
          </span>
        )}
        <span className="sb-spacer" />
        {error && <span className="sb-item err">{error}</span>}
        <span className={`sb-item${agentConfigured ? '' : ' err'}`}>
          {agentConfigured ? '● Agent ready' : '○ No API key'}
        </span>
      </footer>
    </div>
  )
}
