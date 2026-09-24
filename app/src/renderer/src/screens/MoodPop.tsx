import type { MoodState } from '@shared/schema'

const LOOK: Record<MoodState['mood'], { emoji: string; label: string; color: string }> = {
  positive: { emoji: '😊', label: 'Positive', color: '#3ddc84' },
  interested: { emoji: '😮', label: 'Interested', color: '#7aa7ff' },
  neutral: { emoji: '😐', label: 'Neutral', color: '#8d929b' },
  skeptical: { emoji: '🤨', label: 'Skeptical', color: '#f5b942' },
  worried: { emoji: '😟', label: 'Worried', color: '#b48cff' },
  annoyed: { emoji: '😠', label: 'Annoyed', color: '#ff6b6b' }
}

/** The prospect's mood, top right. It pops every time the mood changes. */
export function MoodPop({ mood }: { mood: MoodState | null }) {
  if (!mood) return null
  const look = LOOK[mood.mood]
  const marker = Math.round(((mood.valence + 1) / 2) * 100)
  return (
    <div className="pointer-events-none fixed top-16 right-5 z-40">
      {/* keyed on each change so the pop animation replays */}
      <div
        key={mood.changes}
        className="mood-pop flex w-56 items-center gap-3 rounded-2xl border bg-panel/95 px-4 py-3 backdrop-blur"
        style={{ borderColor: look.color, ['--mood' as string]: look.color }}
      >
        <span className="mood-emoji text-4xl leading-none">{look.emoji}</span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-bold tracking-wide uppercase" style={{ color: look.color }}>
            {look.label}
          </div>
          <div className="relative mt-2 h-1.5 rounded-full bg-gradient-to-r from-bad via-faint to-live opacity-80">
            <span
              className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg bg-ink transition-[left] duration-500"
              style={{ left: `${marker}%` }}
            />
          </div>
          <div className="mt-1.5 text-[10px] tracking-wide text-faint uppercase">{mood.face ? 'face + words' : 'words only'}</div>
        </div>
      </div>
    </div>
  )
}
