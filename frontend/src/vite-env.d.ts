/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** WhyCode API base, e.g. "/api" (through the dev proxy) or "http://localhost:8000/api". Unset = sample data. */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
