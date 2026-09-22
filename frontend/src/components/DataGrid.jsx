import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { api } from '../api'

const ROW_H = 32        // must match --cell-h in workspace.css
const CHUNK = 200
const OVERSCAN = 10

/**
 * Excel-style virtual grid.
 *
 * Renders column letters (A, B, C...) and frozen row-number column.
 * Virtualized scrolling: only renders visible rows.
 */
export default function DataGrid({
  sessionId, version, columnMeta, changedCells, highlightRows,
  query, filterColumn, missingOnly, sortBy, sortDir, onSortChange,
  onStatsChange, onCellFocus, revealColumn,
}) {
  const scrollRef = useRef(null)
  const headerRef = useRef(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportH, setViewportH] = useState(600)
  const [columns, setColumns] = useState([])
  const [filteredRows, setFilteredRows] = useState(0)
  const [error, setError] = useState(null)
  const [loadingChunks, setLoadingChunks] = useState(0)
  const [focusedCell, setFocusedCellLocal] = useState(null) // {rowId, col}

  // Scroll a newly added column into view once it arrives from the server.
  useEffect(() => {
    if (!revealColumn || !scrollRef.current) return
    const cell = scrollRef.current.parentElement?.querySelector(
      `.grid-head-cell[data-col="${CSS.escape(revealColumn)}"]`)
    if (!cell) return
    const body = scrollRef.current
    const left = cell.offsetLeft - body.clientWidth / 2 + cell.offsetWidth / 2
    body.scrollTo({ left: Math.max(0, left), behavior: 'smooth' })
  }, [revealColumn, columns])

  const chunksRef = useRef(new Map())
  const inFlightRef = useRef(new Set())
  const [, forceRender] = useState(0)

  const rowsParam = useMemo(
    () => (highlightRows && highlightRows.length ? highlightRows.join(',') : null),
    [highlightRows],
  )

  const viewKey = `${sessionId}|${version}|${query}|${filterColumn}|${missingOnly}|${sortBy}|${sortDir}|${rowsParam}`

  useEffect(() => {
    chunksRef.current = new Map()
    inFlightRef.current = new Set()
    setScrollTop(0)
    if (scrollRef.current) scrollRef.current.scrollTop = 0
    forceRender((n) => n + 1)
  }, [viewKey])

  const baseParams = useMemo(() => ({
    q: query || undefined,
    column: filterColumn || undefined,
    missing_only: missingOnly || undefined,
    sort_by: sortBy || undefined,
    sort_dir: sortDir,
    rows: rowsParam || undefined,
  }), [query, filterColumn, missingOnly, sortBy, sortDir, rowsParam])

  const fetchChunk = useCallback(async (chunkIdx) => {
    const key = `${viewKey}#${chunkIdx}`
    if (chunksRef.current.has(chunkIdx) || inFlightRef.current.has(key)) return
    inFlightRef.current.add(key)
    setLoadingChunks((n) => n + 1)
    try {
      const page = await api.data(sessionId, {
        ...baseParams, offset: chunkIdx * CHUNK, limit: CHUNK,
      })
      if (!key.startsWith(viewKey)) return
      chunksRef.current.set(chunkIdx, page.rows)
      setColumns(page.columns)
      setFilteredRows(page.filtered_rows)
      onStatsChange?.({ total: page.total_rows, filtered: page.filtered_rows })
      setError(null)
      forceRender((n) => n + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      inFlightRef.current.delete(key)
      setLoadingChunks((n) => Math.max(0, n - 1))
    }
  }, [sessionId, baseParams, viewKey, onStatsChange])

  useEffect(() => { fetchChunk(0) }, [fetchChunk])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const measure = () => setViewportH(el.clientHeight)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const endIdx = Math.min(filteredRows, Math.ceil((scrollTop + viewportH) / ROW_H) + OVERSCAN)

  useEffect(() => {
    if (!filteredRows) return
    const first = Math.floor(startIdx / CHUNK)
    const last = Math.floor(Math.max(0, endIdx - 1) / CHUNK)
    for (let c = first; c <= last; c++) fetchChunk(c)
  }, [startIdx, endIdx, filteredRows, fetchChunk])

  const getRow = (i) => chunksRef.current.get(Math.floor(i / CHUNK))?.[i % CHUNK]

  const metaByName = useMemo(() => {
    const m = {}
    for (const c of columnMeta || []) m[c.name] = c
    return m
  }, [columnMeta])

  const highlightSet = useMemo(() => new Set(highlightRows || []), [highlightRows])

  // Convert index to Excel column letter(s): 0→A, 1→B, 25→Z, 26→AA...
  function colLetter(idx) {
    let s = ''
    let n = idx + 1
    while (n > 0) {
      n--
      s = String.fromCharCode(65 + (n % 26)) + s
      n = Math.floor(n / 26)
    }
    return s
  }

  const visible = []
  for (let i = startIdx; i < endIdx; i++) visible.push(i)

  const headerCell = (col, colIdx) => {
    const meta = metaByName[col]
    const active = sortBy === col
    return (
      <div
        key={col}
        data-col={col}
        className={`grid-cell grid-head-cell${active ? ' sorted' : ''}`}
        onClick={() => onSortChange(col)}
        title={
          meta
            ? `${col}\ndtype: ${meta.dtype}\nblank in ${meta.missing_count} rows` +
              (meta.blank_means ? `\n\nblank means: ${meta.blank_means}` : '')
            : col
        }
      >
        <div className="head-stack">
          <span className="head-letter">{colLetter(colIdx)}</span>
          <span className="head-name">{col}</span>
        </div>
        {meta?.blank_means && (
          <span className="head-badge semantic" title={meta.blank_means}>ⓘ</span>
        )}
        {meta?.is_gap_checked && meta.missing_count > 0 && (
          <span className="head-badge gap" title={`${meta.missing_count} missing values`}>
            {meta.missing_count}
          </span>
        )}
        {active && <span className="sort-arrow">{sortDir === 'asc' ? '▲' : '▼'}</span>}
      </div>
    )
  }

  return (
    <div className="grid-wrap">
      {/* Column headers */}
      <div className="grid-header" ref={headerRef}>
        {/* Corner cell */}
        <div
          className="grid-cell grid-head-cell rownum"
          title="Row 1 holds the column names"
        >
          1
        </div>
        {columns.map((col, i) => headerCell(col, i))}
      </div>

      {/* Rows */}
      <div
        className="grid-body"
        ref={scrollRef}
        onScroll={(e) => {
          setScrollTop(e.currentTarget.scrollTop)
          // Keep the header aligned with the cells: it is a separate
          // element, so it does not scroll sideways on its own.
          if (headerRef.current) headerRef.current.scrollLeft = e.currentTarget.scrollLeft
        }}
      >
        <div className="grid-spacer" style={{ height: filteredRows * ROW_H }}>
          {visible.map((i) => {
            const row = getRow(i)
            if (!row) {
              return (
                <div key={i} className="grid-row skeleton" style={{ top: i * ROW_H }}>
                  <div className="grid-cell rownum">…</div>
                  {columns.map((c) => (
                    <div key={c} className="grid-cell">
                      <span className="skel-bar" />
                    </div>
                  ))}
                </div>
              )
            }
            const rowId = row.__row__
            const isHighlighted = highlightSet.has(rowId)
            return (
              <div
                key={i}
                className={`grid-row${isHighlighted ? ' highlighted' : ''}`}
                style={{ top: i * ROW_H }}
              >
                {/* Row number */}
                {/* Sheet row number: headers are row 1, so data starts at 2 -
                    the same addresses the Excel formulas use. */}
                <div className="grid-cell rownum">
                  {rowId + 2}
                </div>

                {/* Data cells */}
                {columns.map((col) => {
                  const v = row[col]
                  const meta = metaByName[col]
                  const blank = v === null || v === undefined || String(v).trim() === ''
                  const changed = changedCells?.has(`${rowId}::${col}`)
                  const isFocused = focusedCell?.rowId === rowId && focusedCell?.col === col

                  let cls = 'grid-cell'
                  if (isFocused) cls += ' selected'
                  if (changed) cls += ' changed'
                  if (blank) cls += meta?.blank_means ? ' semantic-blank' : ' missing'

                  return (
                    <div
                      key={col}
                      className={cls}
                      tabIndex={0}
                      title={
                        changed
                          ? `Changed by AI → ${v}`
                          : (blank ? (meta?.blank_means || 'Missing value') : String(v))
                      }
                      onClick={() => {
                        setFocusedCellLocal({ rowId, col })
                        onCellFocus?.({ row: rowId, column: col, value: v })
                      }}
                      onFocus={() => {
                        setFocusedCellLocal({ rowId, col })
                        onCellFocus?.({ row: rowId, column: col, value: v })
                      }}
                    >
                      {blank ? (meta?.blank_means ? '–' : '∅') : String(v)}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>

      {error && <div className="grid-error">{error}</div>}
      {loadingChunks > 0 && <div className="grid-loading">Loading…</div>}
    </div>
  )
}
