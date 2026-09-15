import { useState } from 'react'

/**
 * "Do it in Excel" drawer.
 *
 * Shows, for the latest answer or change, the formula or menu steps that
 * give the same result in the user's own copy of the sheet. Cell
 * addresses match the grid: headers are row 1, data starts on row 2.
 */
function Copy({ text }) {
  const [done, setDone] = useState(false)
  return (
    <button
      className="fx-copy"
      onClick={() => {
        navigator.clipboard?.writeText(text)
        setDone(true)
        setTimeout(() => setDone(false), 1200)
      }}
    >
      {done ? 'Copied' : 'Copy'}
    </button>
  )
}

export default function FormulaPanel({ entry }) {
  if (!entry) {
    return (
      <div className="panel-empty">
        Ask the assistant a question or make a change. The Excel formula for it appears here.
      </div>
    )
  }

  return (
    <div className="fx-panel">
      <div className="fx-source">
        From: <span>{entry.label}</span>
      </div>

      {entry.excel.items.map((item, i) => (
        <section key={i} className="fx-item">
          <h4>
            {item.title}
            {item.unverified && <span className="fx-flag">not checked</span>}
          </h4>

          {item.formulas?.map((f, j) => (
            <div key={j} className="fx-formula">
              <div className="fx-label">
                {f.label}
                {f.expected != null && <span className="fx-expected">should return {String(f.expected)}</span>}
              </div>
              <div className="fx-code-row">
                <code>{f.formula}</code>
                <Copy text={f.formula} />
              </div>
            </div>
          ))}

          {item.cells?.length > 0 && (
            <div className="fx-formula">
              <div className="fx-label">Cells to select in the Name Box</div>
              {item.cells.map((c, j) => (
                <div key={j} className="fx-code-row">
                  <code>{c}</code>
                  <Copy text={c} />
                </div>
              ))}
            </div>
          )}

          {item.steps?.length > 0 && (
            <ol className="fx-steps">
              {item.steps.map((s, j) => <li key={j}>{s}</li>)}
            </ol>
          )}

          {item.notes?.map((n, j) => <p key={j} className="fx-note">{n}</p>)}
        </section>
      ))}

      {entry.excel.notes?.map((n, j) => <p key={j} className="fx-note fx-global">{n}</p>)}
    </div>
  )
}
