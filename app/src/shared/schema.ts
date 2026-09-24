// Shapes shared by the main process and the screen. AI answers are checked against these.
import { z } from 'zod'

export const CompanyContext = z.object({
  company: z.string(),
  what_we_do: z.string(),
  positioning: z.string().default(''),
  main_message: z.string().default(''),
  usps: z.array(z.string()).default([]),
  offerings: z.array(z.object({ name: z.string(), price: z.string().default(''), details: z.string().default('') })).default([]),
  guarantee: z.string().default(''),
  cost_formula: z.string().default(''),
  ideal_customer: z.string().default(''),
  differentiators_vs: z
    .array(z.object({ against: z.string(), they_win: z.string().default(''), we_win: z.string() }))
    .default([]),
  facts: z.array(z.string()).default([]),
  never_say: z.array(z.string()).default([]),
  tone: z.string().default('')
})
export type CompanyContext = z.infer<typeof CompanyContext>

/** One piece of live advice (style E: one point, 15 words or fewer). */
export const AdviceAnswer = z.object({
  advice: z.string(),
  company: z.string().nullable().default(null)
})

export const CallMemory = z.object({
  budget: z.string().nullable().default(null),
  decision_makers: z.array(z.string()).default([]),
  pains: z.array(z.string()).default([]),
  objections: z.array(z.object({ topic: z.string(), status: z.enum(['open', 'answered']) })).default([]),
  companies: z.array(z.string()).default([]),
  timeline: z.string().nullable().default(null)
})
export type CallMemory = z.infer<typeof CallMemory>

export const ResearchAnswer = z.object({ bullets: z.array(z.string()).min(1).max(3) })

export const ResearchRecord = z.object({
  name: z.string(),
  aliases: z.array(z.string()).default([]),
  bullets: z.array(z.string()),
  sources: z.array(z.object({ title: z.string(), url: z.string() })),
  fetched_at: z.string()
})
export type ResearchRecord = z.infer<typeof ResearchRecord>

export const Debrief = z.object({
  summary: z.string(),
  went_well: z.array(z.string()).default([]),
  improve: z.array(z.string()).default([]),
  needs: z.array(z.string()).default([]),
  objections: z.array(z.object({ topic: z.string(), status: z.enum(['open', 'answered']) })).default([]),
  competitors: z.array(z.string()).default([]),
  next_steps: z.array(z.string()).default([])
})
export type Debrief = z.infer<typeof Debrief>

// ---- live state pushed to the screen --------------------------------------------------------

export type Device = { id: string; name: string; default: boolean }

export type AdviceItem = { id: number; at: number; heard: string; advice: string }

export type ResearchItem = {
  name: string
  status: 'searching' | 'done' | 'failed'
  bullets: string[]
  sources: { title: string; url: string }[]
  origin?: 'store' | 'fresh'
  updated?: boolean
}

export type Stats = {
  costUsd: number
  sttMs: number | null // last chunk
  llmFirstMs: number | null // last advice: time to first token
  llmTotalMs: number | null // last advice: full answer
  adviceCount: number
  hedgeFired: number
  lookups: number
}

export type TranscriptLine = { at: number; text: string }

export type MoodState = {
  mood: 'positive' | 'interested' | 'neutral' | 'skeptical' | 'worried' | 'annoyed'
  intensity: number // 0-1: how clearly this mood leads
  valence: number // -1 negative .. 1 positive
  engagement: number // 0-1
  face: boolean // a face is being read right now
  changes: number // bumps each time the mood changes, so the screen can pop
}

export type Phase = 'loading' | 'idle' | 'live' | 'debriefing' | 'debrief'

export type AppState = {
  phase: Phase
  audioReady: boolean
  devices: Device[]
  context: CompanyContext | null
  startedAt: number | null
  endedAt: number | null
  level: number
  transcript: TranscriptLine[]
  advice: AdviceItem[]
  research: ResearchItem[]
  mood: MoodState | null
  stats: Stats
  debrief: Debrief | null
}

export type Toast = { id: number; kind: 'error' | 'info'; text: string }

/** Commands the screen sends to the main process. */
export type Command =
  | { cmd: 'refreshDevices' }
  | { cmd: 'start'; device: string }
  | { cmd: 'stop' }
  | { cmd: 'backToMenu' }
  | { cmd: 'saveCall'; prospect: string }
  | { cmd: 'saveContext'; context: CompanyContext }
  | { cmd: 'buildContext'; files: { name: string; data: ArrayBuffer }[] }

export type CommandResult = { ok: true; data?: unknown } | { ok: false; error: string }

export interface GirardApi {
  send(command: Command): Promise<CommandResult>
  onState(listener: (state: AppState) => void): () => void
  onToast(listener: (toast: Toast) => void): () => void
}
