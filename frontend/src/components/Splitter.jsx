import { useCallback, useEffect, useRef } from 'react'

/**
 * Drag handle between two panes.
 *
 * Listeners go on `window` rather than the handle itself: with them on
 * the element, moving the pointer faster than React re-renders drops the
 * drag the moment the cursor leaves the 5px handle — which is most of
 * the time. Pointer capture would also work; window listeners keep this
 * dependency-free and behave identically across the two orientations.
 */
export default function Splitter({ orientation = 'vertical', onResize }) {
  const dragging = useRef(false)

  const onMove = useCallback((e) => {
    if (!dragging.current) return
    e.preventDefault()
    onResize(orientation === 'vertical' ? e.clientX : e.clientY)
  }, [onResize, orientation])

  const onUp = useCallback(() => {
    dragging.current = false
    document.body.classList.remove('resizing-v', 'resizing-h')
  }, [])

  useEffect(() => {
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [onMove, onUp])

  return (
    <div
      className={`splitter ${orientation}`}
      onMouseDown={() => {
        dragging.current = true
        document.body.classList.add(orientation === 'vertical' ? 'resizing-v' : 'resizing-h')
      }}
    />
  )
}
