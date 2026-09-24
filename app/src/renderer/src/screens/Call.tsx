import { useEffect, useRef, useState } from 'react'
import type { AppState } from '@shared/schema'
import { api, fmtClock, fmtCost, fmtMs } from '../api'
import { MoodPop } from './MoodPop'

type Props = { state: AppState; onError: (text: string) => void }

export function CallScreen({ state, onError }: Props) {
  const [now, setNow] = useState(Date.now())
  const [selected, setSelected] = useState<number | null>(null) // index into advice; null = latest
  const [ending, setEnding] = useState(false)
  const transcriptEnd = useRef<HTMLDivElement>(null)
  const advice = state.advice
  const s = state.stats

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [])

  // New advice always snaps back to the latest.
  useEffect(() => {
    setSelected(null)
  }, [advice.length])

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: 'end' })
  }, [state.transcript.length])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!advice.length) return
      const current = selected ?? advice.length - 1
      if (e.key === 'ArrowLeft') setSelected(Math.max(0, current - 1))
      if (e.key === 'ArrowRight') setSelected(current + 1 >= advice.length ? null : current + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [advice.length, selected])

  const end = async () => {
    setEnding(true)
    const r = await api.send({ cmd: 'stop' })
    if (!r.ok) onError(r.error)
  }

  const shownIndex = selected ?? advice.length - 1
  const shown = advice[shownIndex]
  const since = (at: number) => fmtClock(at - (state.startedAt ?? at))

  return (
    <div className="flex h-full flex-col">
      <MoodPop mood={state.mood} />
      {/* header */}
      <header className="flex items-center gap-5 border-b border-line px-5 py-3 text-sm">
        <span className="flex items-center gap-2 font-medium">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-live" /> Live
        </span>
        <span className="font-mono text-muted tabular-nums">{fmtClock(now - (state.startedAt ?? now))}</span>
        <Level rms={state.level} />
        <span className="ml-auto font-mono tabular-nums" title="AI cost of this call so far">
          {fmtCost(s.costUsd)}
        </span>
        <span className="font-mono text-xs text-muted tabular-nums" title="Speech-to-text time for the last chunk">
          STT {fmtMs(s.sttMs)}
        </span>
        <span
          className="font-mono text-xs text-muted tabular-nums"
          title={`Last advice: first word ${fmtMs(s.llmFirstMs)}, full answer ${fmtMs(s.llmTotalMs)}`}
        >
          AI {fmtMs(s.llmTotalMs)}
        </span>
        <button
          onClick={() => void end()}
          disabled={ending}
          className="rounded-lg bg-bad/90 px-4 py-1.5 font-semibold text-black hover:bg-bad disabled:opacity-50"
        >
          {ending ? 'Ending…' : 'End call'}
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* history */}
        <aside className="w-64 shrink-0 overflow-y-auto border-r border-line py-3">
          <div className="px-4 pb-2 text-xs font-medium tracking-wide text-faint uppercase">History</div>
          {advice.length === 0 && <div className="px-4 text-sm text-faint">Advice will collect here.</div>}
          {advice.map((a, i) => (
            <button
              key={a.id}
              onClick={() => setSelected(i === advice.length - 1 ? null : i)}
              className={`block w-full px-4 py-2 text-left text-sm leading-snug ${
                i === shownIndex ? 'bg-panel text-ink' : 'text-muted hover:text-ink'
              }`}
            >
              <span className="mr-2 font-mono text-xs text-faint">{since(a.at)}</span>
              {a.advice}
            </button>
          ))}
        </aside>

        {/* advice + transcript */}
        <main className="flex min-w-0 flex-1 flex-col">
          <section className="flex flex-1 flex-col justify-center px-12 py-8">
            {shown ? (
              <div key={shown.id} className="advice-in selectable">
                <p className="text-3xl leading-snug font-medium tracking-tight">{shown.advice}</p>
                <p className="mt-4 text-sm text-faint">
                  After: “{shown.heard}”
                  {selected !== null && <span className="ml-3 text-accent">earlier advice · → for latest</span>}
                </p>
              </div>
            ) : (
              <p className="text-xl text-faint">Listening… advice appears when the prospect says something worth acting on.</p>
            )}
          </section>
          <section className="h-44 shrink-0 overflow-y-auto border-t border-line px-12 py-3">
            <div className="pb-1 text-xs font-medium tracking-wide text-faint uppercase">Prospect</div>
            {state.transcript.slice(-30).map((t, i) => (
              <p key={i} className="selectable py-0.5 text-sm text-muted">
                {t.text}
              </p>
            ))}
            <div ref={transcriptEnd} />
          </section>
        </main>
      </div>

      {/* research strip */}
      {state.research.length > 0 && (
        <footer className="flex gap-3 overflow-x-auto border-t border-line px-5 py-3">
          {state.research
            .slice()
            .reverse()
            .map((r) => (
              <div key={r.name} className="w-96 shrink-0 rounded-lg border border-line bg-panel px-4 py-3 text-sm">
                <div className="flex items-center gap-2 font-medium">
                  {r.status === 'searching' ? '🔎 Researching' : r.status === 'failed' ? '⚠ Could not research' : ''} {r.name}
                  {r.origin === 'store' && <span className="text-xs font-normal text-faint">saved</span>}
                  {r.updated && <span className="text-xs font-normal text-accent">updated</span>}
                </div>
                {r.bullets.length > 0 && (
                  <ul className="selectable mt-1.5 list-disc space-y-1 pl-4 text-muted">
                    {r.bullets.map((b, i) => (
                      <li key={i}>{b}</li>
                    ))}
                  </ul>
                )}
                {r.sources.length > 0 && (
                  <div className="mt-2 flex gap-3 text-xs">
                    {r.sources.map((src, i) => (
                      <a key={i} href={src.url} target="_blank" rel="noreferrer" className="truncate text-accent hover:underline" title={src.title}>
                        {new URL(src.url).hostname.replace(/^www\./, '')}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
        </footer>
      )}
    </div>
  )
}

function Level({ rms }: { rms: number }) {
  // Speech sits around 0.02-0.2 rms; scale so normal talking fills most of the bar.
  const pct = Math.min(100, Math.round(Math.sqrt(rms / 0.2) * 100))
  return (
    <span className="h-1.5 w-20 overflow-hidden rounded-full bg-line" title="Call audio level">
      <span className="block h-full rounded-full bg-live transition-[width] duration-100" style={{ width: `${pct}%` }} />
    </span>
  )
}
