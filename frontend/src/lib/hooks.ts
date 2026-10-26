import { useEffect, useRef, useState, type RefObject } from 'react'

/** Browser tab title: "<page> · WhyCode". */
export function useTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · WhyCode`
  }, [title])
}

/** Current time, refreshed every `intervalMs`, for "Synced 10 min ago". */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

/** The latest value of a callback, without re-running effects when the caller passes a new one. */
export function useLatest<T>(value: T): RefObject<T> {
  const ref = useRef(value)
  useEffect(() => {
    ref.current = value
  })
  return ref
}

/** Close a popover on Escape or on a press outside `ref`. */
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, onDismiss: () => void) {
  const dismiss = useLatest(onDismiss)
  useEffect(() => {
    if (!open) return
    const onPointer = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) dismiss.current()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dismiss.current()
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, ref, dismiss])
}
