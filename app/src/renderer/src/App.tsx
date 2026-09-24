import { useEffect, useState } from 'react'
import type { AppState, Toast } from '@shared/schema'
import { api } from './api'
import { CallScreen } from './screens/Call'
import { ContextEditor } from './screens/ContextEditor'
import { DebriefScreen } from './screens/Debrief'
import { StartScreen } from './screens/Start'
import { Toasts } from './Toasts'

export function App() {
  const [state, setState] = useState<AppState | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    const offState = api.onState(setState)
    const offToast = api.onToast((t) => {
      setToasts((all) => [...all, t])
      setTimeout(() => setToasts((all) => all.filter((x) => x.id !== t.id)), t.kind === 'error' ? 8000 : 5000)
    })
    void api.send({ cmd: 'refreshDevices' })
    return () => {
      offState()
      offToast()
    }
  }, [])

  const toast = (text: string) =>
    setToasts((all) => {
      const t: Toast = { id: Date.now(), kind: 'error', text }
      setTimeout(() => setToasts((x) => x.filter((y) => y.id !== t.id)), 8000)
      return [...all, t]
    })

  let screen = <div className="grid h-full place-items-center text-muted">Starting…</div>
  if (state) {
    if (editing) screen = <ContextEditor context={state.context} onClose={() => setEditing(false)} onError={toast} />
    else if (state.phase === 'live') screen = <CallScreen state={state} onError={toast} />
    else if (state.phase === 'debriefing' || state.phase === 'debrief') screen = <DebriefScreen state={state} onError={toast} />
    else screen = <StartScreen state={state} onEditContext={() => setEditing(true)} onError={toast} />
  }

  return (
    <>
      {screen}
      <Toasts toasts={toasts} below={state?.phase === 'live'} onClose={(id) => setToasts((all) => all.filter((t) => t.id !== id))} />
    </>
  )
}
