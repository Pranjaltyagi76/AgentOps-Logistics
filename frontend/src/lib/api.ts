import axios, { AxiosError } from 'axios'

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

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(toApiError(error)),
)
