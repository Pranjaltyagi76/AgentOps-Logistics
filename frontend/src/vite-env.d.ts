/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** FastAPI backend origin, e.g. http://localhost:8000 */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
