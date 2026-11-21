/**
 * Adding, syncing and re-reading a repository need the ingestion API, which the live build does
 * not serve yet. Build with VITE_INGEST_ACTIONS=off to leave those buttons out instead of showing
 * ones that fail.
 */
export const INGEST_ACTIONS = import.meta.env.VITE_INGEST_ACTIONS !== 'off'
