import type { Toast } from '@shared/schema'

export function Toasts({ toasts, below, onClose }: { toasts: Toast[]; below: boolean; onClose: (id: number) => void }) {
  return (
    <div className={`pointer-events-none fixed right-4 z-50 flex w-96 flex-col gap-2 ${below ? 'top-40' : 'top-14'}`}>
      {toasts.map((t) => (
        <button
          key={t.id}
          onClick={() => onClose(t.id)}
          className={`pointer-events-auto rounded-lg border px-4 py-3 text-left text-sm shadow-lg backdrop-blur ${
            t.kind === 'error' ? 'border-bad/40 bg-bad/10 text-ink' : 'border-line bg-panel/90 text-ink'
          }`}
        >
          {t.text}
        </button>
      ))}
    </div>
  )
}
