import { createContext, useContext } from 'react'
import { createHttpApi } from './http'
import { createMockApi } from './mock'
import type { WhyCodeApi } from './types'

export interface ApiContextValue {
  api: WhyCodeApi
  /** True when the screens are fed by sample data instead of the real API. */
  sample: boolean
}

export const ApiContext = createContext<ApiContextValue | null>(null)

export function useApi(): ApiContextValue {
  const value = useContext(ApiContext)
  if (!value) throw new Error('useApi must be used inside <ApiContext>')
  return value
}

/** The real API when VITE_API_URL is set, sample data otherwise. */
export function defaultApi(): ApiContextValue {
  const url = import.meta.env.VITE_API_URL
  return url ? { api: createHttpApi(url), sample: false } : { api: createMockApi(), sample: true }
}
