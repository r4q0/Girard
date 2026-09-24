import { useEffect, useState } from 'react'
import type { AppState } from '@shared/schema'
import { api } from '../api'

type Props = { state: AppState; onEditContext: () => void; onError: (text: string) => void }

export function StartScreen({ state, onEditContext, onError }: Props) {
  const [device, setDevice] = useState('')
  const [starting, setStarting] = useState(false)

  // Pick the default output once the list arrives, and again if the chosen one disappears.
  useEffect(() => {
    if (!state.devices.some((d) => d.id === device)) {
      setDevice(state.devices.find((d) => d.default)?.id ?? state.devices[0]?.id ?? '')
    }
  }, [state.devices, device])

  const start = async () => {
    setStarting(true)
    const r = await api.send({ cmd: 'start', device })
    if (!r.ok) onError(r.error)
    setStarting(false)
  }

  const ready = state.audioReady && !!device && !!state.context

  return (
    <div className="grid h-full place-items-center px-6">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold tracking-tight">Girard</h1>
        <p className="mt-1 text-sm text-muted">Live advice while you sell. Girard hears only the other side of the call.</p>

        <label className="mt-10 block text-xs font-medium tracking-wide text-muted uppercase">Call audio from</label>
        <div className="mt-2 flex gap-2">
          <select
            value={device}
            onChange={(e) => setDevice(e.target.value)}
            disabled={!state.devices.length}
            className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none focus:border-accent"
          >
            {!state.devices.length && <option>{state.audioReady ? 'No outputs found' : 'Loading…'}</option>}
            {state.devices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
                {d.default ? ' (default)' : ''}
              </option>
            ))}
          </select>
          <button
            onClick={() => void api.send({ cmd: 'refreshDevices' })}
            title="Refresh outputs"
            className="rounded-lg border border-line bg-panel px-3 text-muted hover:text-ink"
          >
            ↻
          </button>
        </div>
        <p className="mt-2 text-xs text-faint">Pick the headset or speakers your call plays through.</p>

        <label className="mt-8 block text-xs font-medium tracking-wide text-muted uppercase">Selling for</label>
        <div className="mt-2 flex items-center justify-between rounded-lg border border-line bg-panel px-3 py-2.5 text-sm">
          <span>{state.context?.company ?? 'No company context yet'}</span>
          <button onClick={onEditContext} className="text-accent hover:underline">
            {state.context ? 'Edit' : 'Set up'}
          </button>
        </div>

        <button
          onClick={() => void start()}
          disabled={!ready || starting}
          className="mt-10 w-full rounded-lg bg-live py-3 text-sm font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {!state.audioReady ? 'Loading speech model…' : starting ? 'Starting…' : 'Start call'}
        </button>
      </div>
    </div>
  )
}
