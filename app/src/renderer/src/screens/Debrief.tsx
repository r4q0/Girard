import { useState } from 'react'
import type { AppState } from '@shared/schema'
import { api, fmtClock, fmtCost } from '../api'

type Props = { state: AppState; onError: (text: string) => void }

/** End of a call: name it, save the Word file (debrief, stats, transcript), go back to the menu. */
export function DebriefScreen({ state, onError }: Props) {
  const [name, setName] = useState('')
  const [saved, setSaved] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const s = state.stats

  if (state.phase === 'debriefing') {
    return (
      <div className="grid h-full place-items-center">
        <div className="text-center">
          <div className="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-line border-t-live" />
          <p className="mt-4 text-sm text-muted">Writing the debrief…</p>
        </div>
      </div>
    )
  }

  const save = async () => {
    setSaving(true)
    const r = await api.send({ cmd: 'saveCall', prospect: name })
    setSaving(false)
    if (r.ok) setSaved(String(r.data))
    else onError(r.error)
  }

  return (
    <div className="grid h-full place-items-center px-6">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold tracking-tight">Call ended</h1>
        <p className="mt-1 font-mono text-xs text-muted tabular-nums">
          {fmtClock((state.endedAt ?? 0) - (state.startedAt ?? 0))} · {s.adviceCount} advice · {fmtCost(s.costUsd)}
        </p>

        <label className="mt-10 block text-xs font-medium tracking-wide text-muted uppercase">Name this call</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && name.trim() && !saving && void save()}
          placeholder="e.g. the prospect's company"
          autoFocus
          className="mt-2 w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none focus:border-accent"
        />
        <button
          onClick={() => void save()}
          disabled={saving || !name.trim()}
          className="mt-4 w-full rounded-lg bg-live py-3 text-sm font-semibold text-black hover:brightness-110 disabled:opacity-40"
        >
          {saving ? 'Saving…' : saved ? 'Saved' : 'Save file'}
        </button>
        {saved && <p className="mt-2 truncate text-xs text-muted" title={saved}>{saved}</p>}

        <button
          onClick={() => void api.send({ cmd: 'backToMenu' })}
          className="mt-10 w-full text-sm text-muted hover:text-ink"
        >
          Back to menu{saved ? '' : ' (not saved)'}
        </button>
      </div>
    </div>
  )
}
