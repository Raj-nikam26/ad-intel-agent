import { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api'

export const TYPE_COLORS = {
  Advertiser: '#4ea1ff',
  Publication: '#f0a35e',
  Category: '#6ed39b',
  SubCategory: '#3f9c74',
  Location: '#c98bdb',
  SalesOffice: '#e8c76a',
  Unknown: '#8a8f98',
}

/**
 * Force-directed view of the retrieved subgraph.
 *
 * This panel exists to make the retrieval step legible. The claim "this
 * uses GraphRAG" is cheap; being able to click an advertiser and see the
 * exact publications, categories, locations and sales offices the answer
 * was grounded in is the thing that makes it checkable. Edge thickness
 * is the collapsed weight from the server - a thick line means hundreds
 * of ad insertions, not one relationship drawn bold for style.
 *
 * The simulation is deliberately small: Barnes-Hut and friends matter at
 * thousands of nodes, and the server caps a neighborhood at 200. Plain
 * O(n^2) repulsion over <=200 nodes is a few thousand operations per
 * frame, which is nothing, and it keeps this readable.
 */
export default function GraphPanel({ sessionId, version }) {
  const [stats, setStats] = useState(null)
  const [view, setView] = useState(null)
  const [center, setCenter] = useState(null)
  const [depth, setDepth] = useState(1)
  const [search, setSearch] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [hover, setHover] = useState(null)

  const svgRef = useRef(null)
  const simRef = useRef({ nodes: [], edges: [], raf: null })
  const dragRef = useRef(null)
  const [, tick] = useState(0)

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    api.graphStats(sessionId)
      .then((s) => {
        setStats(s)
        if (!center && s.top_advertisers.length) loadNode(s.top_advertisers[0].id, depth)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, version])

  const loadNode = useCallback(async (nodeId, d = depth) => {
    setLoading(true); setError(null)
    try {
      const v = await api.graphNeighborhood(sessionId, nodeId, d)
      setCenter(nodeId)
      setView(v)
      initSim(v, nodeId)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [sessionId, depth])

  useEffect(() => {
    if (!search.trim()) { setResults([]); return }
    const t = setTimeout(() => {
      api.graphSearch(sessionId, search.trim())
        .then((r) => setResults(r.results))
        .catch(() => setResults([]))
    }, 250)
    return () => clearTimeout(t)
  }, [search, sessionId])

  function initSim(v, centerId) {
    const W = 800, H = 560
    const nodes = v.nodes.map((n, i) => {
      const isCenter = n.id === centerId
      const angle = (i / Math.max(1, v.nodes.length)) * Math.PI * 2
      return {
        ...n,
        x: isCenter ? W / 2 : W / 2 + Math.cos(angle) * 180 + (Math.random() - 0.5) * 40,
        y: isCenter ? H / 2 : H / 2 + Math.sin(angle) * 180 + (Math.random() - 0.5) * 40,
        vx: 0, vy: 0,
        pinned: isCenter,
      }
    })
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
    const edges = v.edges
      .map((e) => ({ ...e, s: byId[e.source], t: byId[e.target] }))
      .filter((e) => e.s && e.t)

    simRef.current.nodes = nodes
    simRef.current.edges = edges
    simRef.current.alpha = 1
    run()
  }

  function run() {
    cancelAnimationFrame(simRef.current.raf)
    const W = 800, H = 560
    const step = () => {
      const sim = simRef.current
      const { nodes, edges } = sim
      if (!nodes.length) return
      const alpha = sim.alpha ?? 0

      for (const n of nodes) { n.fx = 0; n.fy = 0 }

      // repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j]
          let dx = b.x - a.x, dy = b.y - a.y
          let d2 = dx * dx + dy * dy
          if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; dy = Math.random() - 0.5 }
          const f = 9000 / d2
          const d = Math.sqrt(d2)
          const ux = dx / d, uy = dy / d
          a.fx -= ux * f; a.fy -= uy * f
          b.fx += ux * f; b.fy += uy * f
        }
      }

      // springs — heavier edges pull a little tighter, so high-volume
      // relationships sit visibly closer to the advertiser
      for (const e of edges) {
        const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y
        const d = Math.max(1, Math.hypot(dx, dy))
        const rest = 120 - Math.min(50, Math.log2(1 + e.weight) * 8)
        const f = (d - rest) * 0.02
        const ux = dx / d, uy = dy / d
        e.s.fx += ux * f; e.s.fy += uy * f
        e.t.fx -= ux * f; e.t.fy -= uy * f
      }

      for (const n of nodes) {
        n.fx += (W / 2 - n.x) * 0.004
        n.fy += (H / 2 - n.y) * 0.004
        if (n.pinned || n === dragRef.current?.node) { n.vx = 0; n.vy = 0; continue }
        n.vx = (n.vx + n.fx) * 0.82
        n.vy = (n.vy + n.fy) * 0.82
        n.x += n.vx * alpha
        n.y += n.vy * alpha
        n.x = Math.max(30, Math.min(W - 30, n.x))
        n.y = Math.max(30, Math.min(H - 30, n.y))
      }

      sim.alpha = Math.max(0, alpha - 0.004)
      tick((t) => t + 1)
      if (sim.alpha > 0.01) sim.raf = requestAnimationFrame(step)
    }
    simRef.current.raf = requestAnimationFrame(step)
  }

  useEffect(() => () => cancelAnimationFrame(simRef.current.raf), [])

  function svgPoint(evt) {
    const svg = svgRef.current
    const r = svg.getBoundingClientRect()
    return {
      x: ((evt.clientX - r.left) / r.width) * 800,
      y: ((evt.clientY - r.top) / r.height) * 560,
    }
  }

  const onDown = (n) => (e) => {
    e.preventDefault()
    dragRef.current = { node: n }
    simRef.current.alpha = Math.max(simRef.current.alpha ?? 0, 0.35)
    run()
  }
  const onMove = (e) => {
    if (!dragRef.current) return
    const p = svgPoint(e)
    dragRef.current.node.x = p.x
    dragRef.current.node.y = p.y
    dragRef.current.moved = true
    tick((t) => t + 1)
  }
  const onUp = () => { dragRef.current = null }

  const { nodes, edges } = simRef.current
  const centerNode = nodes.find((n) => n.id === center)

  return (
    <div className="graph-panel">
      <div className="graph-toolbar">
        <div className="graph-search">
          <input
            placeholder="Search the graph — advertiser, publication, category…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {results.length > 0 && (
            <div className="graph-results">
              {results.map((r) => (
                <button key={r.id} onClick={() => { loadNode(r.id); setSearch(''); setResults([]) }}>
                  <span className="dot" style={{ background: TYPE_COLORS[r.type] || TYPE_COLORS.Unknown }} />
                  <span className="r-label">{r.label}</span>
                  <span className="r-type">{r.type}</span>
                  <span className="r-degree">{r.degree}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="depth-toggle">
          <span>hops</span>
          {[1, 2].map((d) => (
            <button
              key={d}
              className={depth === d ? 'active' : ''}
              onClick={() => { setDepth(d); if (center) loadNode(center, d) }}
            >{d}</button>
          ))}
        </div>
      </div>

      {stats && (
        <div className="graph-stats">
          <span><b>{stats.node_count.toLocaleString()}</b> nodes</span>
          <span><b>{stats.edge_count.toLocaleString()}</b> edges</span>
          {Object.entries(stats.nodes_by_type).map(([t, n]) => (
            <span key={t} className="type-chip">
              <span className="dot" style={{ background: TYPE_COLORS[t] || TYPE_COLORS.Unknown }} />
              {t} <b>{n}</b>
            </span>
          ))}
        </div>
      )}

      {error && <div className="panel-error">{error}</div>}

      <div className="graph-canvas">
        <svg
          ref={svgRef}
          viewBox="0 0 800 560"
          preserveAspectRatio="xMidYMid meet"
          onMouseMove={onMove}
          onMouseUp={onUp}
          onMouseLeave={onUp}
        >
          <g>
            {edges.map((e, i) => (
              <line
                key={i}
                x1={e.s.x} y1={e.s.y} x2={e.t.x} y2={e.t.y}
                className={`gedge ${e.relation}`}
                strokeWidth={Math.min(6, 0.8 + Math.log2(1 + e.weight))}
              />
            ))}
          </g>
          <g>
            {nodes.map((n) => {
              const r = n.id === center ? 16 : 8 + Math.min(6, Math.log2(1 + n.degree))
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x},${n.y})`}
                  className={`gnode${n.id === center ? ' center' : ''}`}
                  onMouseDown={onDown(n)}
                  onMouseEnter={() => setHover(n)}
                  onMouseLeave={() => setHover(null)}
                  onDoubleClick={() => loadNode(n.id)}
                >
                  <circle r={r} fill={TYPE_COLORS[n.type] || TYPE_COLORS.Unknown} />
                  <text y={r + 12} textAnchor="middle">
                    {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>

        {view?.truncated && (
          <div className="graph-truncated">
            neighborhood capped at {view.nodes.length} nodes — this node is a hub
          </div>
        )}

        <div className="graph-hint">
          drag nodes · double-click to re-center
        </div>
      </div>

      <div className="graph-inspector">
        {hover ? (
          <>
            <div className="insp-type" style={{ color: TYPE_COLORS[hover.type] }}>{hover.type}</div>
            <div className="insp-name">{hover.label}</div>
            <div className="insp-meta">{hover.degree.toLocaleString()} connections in the full graph</div>
          </>
        ) : centerNode ? (
          <>
            <div className="insp-type" style={{ color: TYPE_COLORS[centerNode.type] }}>
              centred on {centerNode.type}
            </div>
            <div className="insp-name">{centerNode.label}</div>
            <div className="insp-meta">
              showing {nodes.length} nodes · {edges.length} collapsed relationships
              {loading && ' · loading…'}
            </div>
          </>
        ) : (
          <div className="insp-meta">{loading ? 'building graph…' : 'search for a node to begin'}</div>
        )}
      </div>
    </div>
  )
}
