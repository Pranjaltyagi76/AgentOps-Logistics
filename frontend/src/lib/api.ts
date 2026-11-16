import axios, { AxiosError } from 'axios'

import { getSession, setSession } from './session'
import { watchRequest } from './slowRequests'

/** Base URL of the FastAPI backend, baked in at build time. Never put secrets in VITE_* vars. */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export const api = axios.create({
  baseURL: `${API_BASE_URL.replace(/\/+$/, '')}/api/v1`,
  // Free-tier backends cold-start slowly; the UI shows a "waking up" state meanwhile.
  timeout: 60_000,
  headers: { 'Content-Type': 'application/json' },
})

/** Backend error envelope: {"error": {code, message, details, request_id}} */
interface ErrorEnvelope {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
    request_id?: string | null
  }
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number | null
  readonly details: Record<string, unknown>
  readonly requestId: string | null

  constructor(opts: {
    code: string
    message: string
    status: number | null
    details?: Record<string, unknown>
    requestId?: string | null
  }) {
    super(opts.message)
    this.name = 'ApiError'
    this.code = opts.code
    this.status = opts.status
    this.details = opts.details ?? {}
    this.requestId = opts.requestId ?? null
  }
}

function isErrorEnvelope(data: unknown): data is ErrorEnvelope {
  if (typeof data !== 'object' || data === null || !('error' in data)) return false
  const error = (data as { error: unknown }).error
  return typeof error === 'object' && error !== null && 'code' in error && 'message' in error
}

/** Converts any thrown value from axios into an ApiError with a stable shape. */
export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  if (err instanceof AxiosError) {
    const status = err.response?.status ?? null
    const data: unknown = err.response?.data
    if (isErrorEnvelope(data)) {
      return new ApiError({
        code: data.error.code,
        message: data.error.message,
        status,
        details: data.error.details,
        requestId: data.error.request_id,
      })
    }
    if (!err.response) {
      return new ApiError({
        code: err.code === 'ECONNABORTED' ? 'timeout' : 'network_error',
        message: 'Cannot reach the backend. It may be starting up or offline.',
        status: null,
      })
    }
    return new ApiError({ code: 'http_error', message: err.message, status })
  }
  return new ApiError({ code: 'unknown_error', message: String(err), status: null })
}

const SESSION_ERROR_CODES = new Set(['not_authenticated', 'invalid_token', 'token_expired'])

// Settles the slow-request watch started for each request (see slowRequests.ts).
const doneWatching = new WeakMap<object, () => void>()

function settle(config: object | undefined) {
  if (!config) return
  doneWatching.get(config)?.()
  doneWatching.delete(config)
}

api.interceptors.request.use((config) => {
  const session = getSession()
  if (session) config.headers.set('Authorization', `Bearer ${session.token}`)
  doneWatching.set(config, watchRequest())
  return config
})

api.interceptors.response.use(
  (response) => {
    settle(response.config)
    return response
  },
  (error: unknown) => {
    if (error instanceof AxiosError) settle(error.config)
    const apiError = toApiError(error)
    // A rejected session token signs the user out; the router then shows the login page.
    if (apiError.status === 401 && SESSION_ERROR_CODES.has(apiError.code) && getSession()) {
      setSession(null)
    }
    return Promise.reject(apiError)
  },
)

/** Downloads a report export with the session's token (a plain link would not carry it). */
export async function downloadFile(path: string, params: Record<string, string>, filename: string) {
  const response = await api.get<Blob>(path, { params, responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
