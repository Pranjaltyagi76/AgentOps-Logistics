/**
 * Tracks API requests that are still waiting after SLOW_AFTER_MS, so the shell can show a
 * "backend is waking up" banner while a free-tier host cold-starts (NFR-15).
 */
import { useSyncExternalStore } from 'react'

export const SLOW_AFTER_MS = 5_000

let slow = 0
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

/** Starts watching one request; call the returned function when it settles. */
export function watchRequest(): () => void {
  let flagged = false
  const timer = setTimeout(() => {
    flagged = true
    slow += 1
    emit()
  }, SLOW_AFTER_MS)
  return () => {
    clearTimeout(timer)
    if (flagged) {
      slow -= 1
      emit()
    }
  }
}

export function useSlowRequests(): number {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => slow,
  )
}
