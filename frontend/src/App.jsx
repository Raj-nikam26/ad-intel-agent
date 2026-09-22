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
import SchemaPanel from './components/SchemaPanel'
import AddColumnDialog from './components/AddColumnDialog'

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
  ChevronDown, ChevronUp, Columns3, Download, FileSpreadsheet, Filter, FilterX, History,
  Info, Network, Plus, Search, Sparkles, SquareFunction, Table2, TriangleAlert, X,
} from 'lucide-react'

/**
 * ExcelAI workspace.
 *
 * App bar (file, view switch, actions), a toolbar for the selected cell
 * and filters, then the grid and the drawer (problems, history, columns,
 * Excel formulas) as cards, with the assistant docked on the right.
 */
export default function App({ account = null }) {
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
  const [addingColumn, setAddingColumn] = useState(false)
  const [revealColumn, setRevealColumn] = useState(null)
  const [notice, setNotice] = useState(null)
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
    setNotice(data.notice || null)
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

  // Edits can add columns, so the column list and per-column counts are
  // re-read after any new version. Messages and view state are kept.
  async function refreshColumns() {
    if (!session) return
    try {
      const fresh = await api.session(session.session_id)
      setSession((s) => ({
        ...s,
        columns: fresh.columns,
        column_meta: fresh.column_meta,
        column_count: fresh.column_count,
        row_count: fresh.row_count,
      }))
    } catch { /* the grid still reloads its own columns */ }
  }

  async function onColumnAdded(res) {
    setAddingColumn(false)
    setVersion(res.current_version)
    setSelectedVersion(res.current_version)
    if (res.excel) setFormulaEntry({ label: `Add column ${res.column}`, excel: res.excel })
    setMainTab('data')
    setRevealColumn(res.column)
    await Promise.all([loadDiff(res.current_version), refreshColumns()])
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
        await Promise.all([loadDiff(res.version), refreshColumns()])
        if (!fx) { setBottomTab('history'); setBottomOpen(true) }
        const added = [...(res.tool_calls || [])].reverse().find((t) =>
          t.arguments?.operation === 'add_column' && t.result?.status === 'applied')
        if (added) { setMainTab('data'); setRevealColumn(added.arguments.new_column?.trim()) }
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
    // The panel is hidden while closed, so focus once it has rendered.
    requestAnimationFrame(() => {
      const el = chatInputRef.current
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length) }
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
    await Promise.all([loadDiff(res.current_version), refreshColumns()])
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
        account={account}
        onUpload={handleUpload}
        onSample={() => start(api.sample)}
        uploading={uploading}
        error={error}
      />
    )
  }

  // ─── Workspace ──────────────────────────────────────────────────
  const fileName = session.filename || 'Spreadsheet.xlsx'
  const filtersActive = !!(highlightRows || query || missingOnly || sortBy || filterColumn)
  const cellRef = focusedCell
    ? `${colLetter(session.columns.indexOf(focusedCell.column))}${focusedCell.row + 2}`
    : ''
  const clearFilters = () => {
    setHighlightRows(null); setSelectedScope(null)
    setQueryDraft(''); setQuery(''); setFilterColumn('')
    setMissingOnly(false); setSortBy(''); setSortDir('asc')
  }
  const openBottom = (tab) => { setBottomTab(tab); setBottomOpen(true) }

  return (
    <div className="ws">
      {/* ── App bar ── */}
      <header className="ws-bar">
        <div className="ws-brand">
          <span className="ws-logo"><FileSpreadsheet size={16} strokeWidth={2.2} /></span>
          <div className="ws-file">
            <span className="ws-file-name" title={fileName}>{fileName}</span>
            <span className="ws-file-meta">
              <span className={`ws-pill${version > 0 ? ' edited' : ''}`}>
                v{version} · {version === 0 ? 'original' : 'edited'}
              </span>
              {session.row_count.toLocaleString()} rows · {session.column_count} columns
            </span>
          </div>
        </div>

        <nav className="ws-seg" aria-label="View">
          <button className={mainTab === 'data' ? 'on' : ''} onClick={() => setMainTab('data')}>
            <Table2 size={15} /> Data
          </button>
          <button className={mainTab === 'graph' ? 'on' : ''} onClick={() => setMainTab('graph')}>
            <Network size={15} /> Knowledge graph
          </button>
        </nav>

        <div className="ws-actions">
          <button
            className={`ws-btn ai${chatOpen ? ' on' : ''}`}
            onClick={() => setChatOpen((o) => !o)}
            title={chatOpen ? 'Hide the assistant' : 'Open the assistant'}
          >
            <Sparkles size={15} /> Assistant
          </button>
          <button
            className="ws-btn primary"
            onClick={() => api.exportFile(session.session_id, `edited_v${version}.xlsx`).catch((e) => setError(e.message))}
          >
            <Download size={15} /> Export
          </button>
          <button className="ws-icon-btn" onClick={closeFile} title="Close this file">
            <X size={17} />
          </button>
          {account && (
            <div className="ws-account" title={account.email || account.name}>
              {account.button}
            </div>
          )}
        </div>
      </header>

      {/* ── Toolbar ── */}
      <div className="ws-toolbar">
        <div className="ws-fx" title="Selected cell">
          <span className="ws-fx-ref">{cellRef || '—'}</span>
          <span className="ws-fx-sign">fx</span>
          <span className="ws-fx-val" title={String(focusedCell?.value ?? '')}>
            {focusedCell ? (focusedCell.value ?? <em>empty</em>) : <em>Select a cell</em>}
          </span>
        </div>

        <label className="ws-search">
          <Search size={15} />
          <input
            placeholder="Search every column…"
            value={queryDraft}
            onChange={(e) => setQueryDraft(e.target.value)}
          />
          {queryDraft && (
            <button onClick={() => { setQueryDraft(''); setQuery('') }} title="Clear search"><X size={13} /></button>
          )}
        </label>

        <div className="ws-select">
          <Filter size={14} />
          <select value={filterColumn} onChange={(e) => setFilterColumn(e.target.value)}>
            <option value="">All columns</option>
            {session.columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <ChevronDown size={14} />
        </div>

        <label
          className={`ws-switch${missingOnly ? ' on' : ''}${filterColumn ? '' : ' disabled'}`}
          title={filterColumn ? 'Show only rows where this column is empty' : 'Pick a column first'}
        >
          <input
            type="checkbox"
            checked={missingOnly}
            disabled={!filterColumn}
            onChange={(e) => setMissingOnly(e.target.checked)}
          />
          <span className="ws-switch-track"><span /></span>
          Missing only
        </label>

        {filtersActive && (
          <button className="ws-text-btn" onClick={clearFilters}>
            <FilterX size={14} /> Clear
          </button>
        )}

        <button className="ws-btn" onClick={() => setAddingColumn(true)} title="Add a new column">
          <Plus size={15} /> Add column
        </button>

        <div className="ws-chips">
          {notice && (
            <span className="ws-chip blue" title={notice}>
              <Info size={13} /> {notice.split('.')[0]}
              <button onClick={() => setNotice(null)} aria-label="Dismiss"><X size={12} /></button>
            </span>
          )}
          {highlightRows && (
            <span className="ws-chip green">
              {highlightRows.length.toLocaleString()} rows · <code>{selectedScope}</code>
            </span>
          )}
          {changeSummary && (
            <span className="ws-chip amber">
              {changeSummary.cells.toLocaleString()} cells changed in v{changeSummary.version}
            </span>
          )}
        </div>
      </div>

      {/* ── Body ── */}
      <div className="ws-body">
        <main className="ws-main">
          <section className="ws-card ws-editor">
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
                revealColumn={revealColumn}
              />
            ) : (
              <GraphPanel sessionId={session.session_id} version={version} />
            )}
          </section>

          {bottomOpen && (
            <Splitter
              orientation="horizontal"
              onResize={(y) =>
                setBottomHeight(Math.max(120, Math.min(window.innerHeight - 260, window.innerHeight - y - 40)))
              }
            />
          )}

          <section
            className={`ws-card ws-drawer${bottomOpen ? '' : ' closed'}`}
            style={bottomOpen ? { height: bottomHeight } : undefined}
          >
            <div className="ws-drawer-tabs">
              {BOTTOM_TABS.map(({ id, label, icon: Icon, title }) => (
                <button
                  key={id}
                  className={bottomTab === id && bottomOpen ? 'on' : ''}
                  onClick={() => openBottom(id)}
                  title={title}
                >
                  <Icon size={14} /> {label}
                </button>
              ))}
              <span className="ws-grow" />
              <button
                className="ws-icon-btn sm"
                onClick={() => setBottomOpen((o) => !o)}
                title={bottomOpen ? 'Collapse panel' : 'Expand panel'}
              >
                {bottomOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
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
                ) : bottomTab === 'schema' ? (
                  <SchemaPanel
                    sessionId={session.session_id}
                    onChanged={() => setVersion((v) => v)}
                  />
                ) : (
                  <FormulaPanel entry={formulaEntry} />
                )}
              </div>
            )}
          </section>
        </main>

        <aside className={`ws-card ws-assistant${chatOpen ? ' open' : ''}`} style={{ '--chat-w': `${chatWidth}px` }}>
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
        </aside>
      </div>

      {addingColumn && (
        <AddColumnDialog
          sessionId={session.session_id}
          columns={session.columns}
          onClose={() => setAddingColumn(false)}
          onAdded={onColumnAdded}
        />
      )}

      {/* ── Status bar ── */}
      <footer className="ws-status">
        <span>{gridStats.filtered.toLocaleString()} of {session.row_count.toLocaleString()} rows shown</span>
        <span className={version > 0 ? 'accent' : ''}>Version {version}</span>
        {focusedCell && (
          <span className="mono">{cellRef} · {focusedCell.column}</span>
        )}
        <span className="ws-grow" />
        {error && (
          <span className="err" title={error}>
            {error}
            <button onClick={() => setError(null)} title="Dismiss"><X size={12} /></button>
          </span>
        )}
        <span className={`ws-dot${agentConfigured ? ' ok' : ''}`}>
          {agentConfigured ? 'Assistant ready' : 'Assistant offline'}
        </span>
      </footer>
    </div>
  )
}

const BOTTOM_TABS = [
  { id: 'problems', label: 'Problems', icon: TriangleAlert },
  { id: 'history', label: 'History', icon: History },
  { id: 'schema', label: 'Columns', icon: Columns3, title: 'What the app worked out about your columns' },
  { id: 'excel', label: 'Do it in Excel', icon: SquareFunction },
]
