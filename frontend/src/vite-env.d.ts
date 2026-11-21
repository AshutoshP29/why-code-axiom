/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** WhyCode API base, e.g. "/api" (through the dev proxy) or "http://localhost:8000/api". Unset = sample data. */
  readonly VITE_API_URL?: string
  /** "off" hides Add repository, Sync now and Re-run ingestion (see lib/features.ts). */
  readonly VITE_INGEST_ACTIONS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
