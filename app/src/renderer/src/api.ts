import type { AppState, GirardApi } from '@shared/schema'
import { demoApi } from './demo'

declare global {
  interface Window {
    girard?: GirardApi
  }
}

/** The real bridge inside Electron; a fake one in a plain browser (layout checks: ?demo=start|call|debrief). */
export const api: GirardApi = window.girard ?? demoApi()

export const fmtMs = (ms: number | null): string =>
  ms == null ? '-' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`

export const fmtCost = (usd: number): string => `$${usd < 0.1 ? usd.toFixed(4) : usd.toFixed(2)}`

export const fmtClock = (ms: number): string => {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export type { AppState }
