/**
 * Current sign-in session. Kept in memory and mirrored to sessionStorage, so it survives a
 * page reload but not closing the tab. Tokens are short-lived bearer JWTs (decision D-14).
 */
export type Role = 'owner' | 'viewer'

export interface Session {
  token: string
  role: Role
  email: string | null
  expiresAt: string
}

const STORAGE_KEY = 'agentops.session'
const CHANGE_EVENT = 'agentops:session'

function isExpired(session: Session): boolean {
  return Date.parse(session.expiresAt) <= Date.now()
}

function load(): Session | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Session
    return parsed.token && !isExpired(parsed) ? parsed : null
  } catch {
    return null
  }
}

let current: Session | null = load()

export function getSession(): Session | null {
  if (current && isExpired(current)) setSession(null)
  return current
}

export function setSession(session: Session | null): void {
  current = session
  try {
    if (session) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage can be unavailable (private mode); the in-memory session still works.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function subscribeSession(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback)
  return () => window.removeEventListener(CHANGE_EVENT, callback)
}
