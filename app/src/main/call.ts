// The call engine: audio events in, advice / research / stats / debrief out to the screen.
import {
  AdviceAnswer,
  CallMemory,
  Debrief,
  type AppState,
  type CompanyContext,
  type Stats,
  type Toast
} from '@shared/schema'
import { askJson, warm } from './llm'
import { adviceSystem, adviceUser, debriefSystem, debriefUser, MEMORY_SYSTEM, memoryUser } from './prompts'
import type { Researcher, ResearchStore } from './research'
import type { Sidecar, SidecarEvent } from './sidecar'

const HEDGE_MS = 650 // GLM-5.2's first token usually lands at ~0.43 s; only rescue the stuck ones
const RECENT_LINES = 8
const GIVEN_ADVICE = 8
const REWARM_AFTER_MS = 45_000 // re-warm on new speech only if the last warm-up is this old
const MEMORY_EVERY_LINES = 2
const MEMORY_MAX_WAIT_MS = 10_000

const emptyStats = (): Stats => ({
  costUsd: 0,
  sttMs: null,
  llmFirstMs: null,
  llmTotalMs: null,
  adviceCount: 0,
  hedgeFired: 0,
  lookups: 0
})

export class CallEngine {
  state: AppState = {
    phase: 'loading',
    audioReady: false,
    devices: [],
    context: null,
    startedAt: null,
    endedAt: null,
    level: 0,
    transcript: [],
    advice: [],
    research: [],
    mood: null,
    stats: emptyStats(),
    debrief: null
  }
  private memory: CallMemory = CallMemory.parse({})
  private lines: string[] = [] // filtered lines sent to advice
  private memoryPending: string[] = []
  private memoryBusy = false
  private memoryTimer: NodeJS.Timeout | null = null
  private inFlight = new Set<Promise<unknown>>()
  private researched = new Set<string>()
  private lastWarm = 0
  private system = ''
  private pushTimer: NodeJS.Timeout | null = null
  private stopped: (() => void) | null = null
  private toastId = 0

  constructor(
    private sidecar: Sidecar,
    private emotion: Sidecar,
    private researcher: Researcher,
    private store: ResearchStore,
    private push: (state: AppState) => void,
    private toast: (toast: Toast) => void
  ) {
    sidecar.on('event', (e: SidecarEvent) => this.onAudio(e))
    emotion.on('event', (e: SidecarEvent) => this.onMood(e))
  }

  // ---- mood (face + words, local, never on the advice path) ---------------------------------

  private moodErrorShown = false

  private onMood(e: SidecarEvent): void {
    if (e.type === 'mood') {
      if (this.state.phase !== 'live') return
      const changes = (this.state.mood?.changes ?? 0) + (e.changed ? 1 : 0)
      this.state.mood = { mood: e.mood, intensity: e.intensity, valence: e.valence, engagement: e.engagement, face: e.face, changes }
      this.changed()
    } else if (e.type === 'error' && !this.moodErrorShown) {
      this.moodErrorShown = true // one notice per call is enough; the call itself is unaffected
      this.notify('info', `Mood tracking: ${e.message}`)
    }
  }

  // ---- plumbing ----------------------------------------------------------------------------

  private changed(): void {
    if (this.pushTimer) return
    this.pushTimer = setTimeout(() => {
      this.pushTimer = null
      this.push(this.state)
    }, 40)
  }

  notify(kind: Toast['kind'], text: string): void {
    this.toast({ id: ++this.toastId, kind, text })
  }

  private addCost(usd: number): void {
    this.state.stats.costUsd += usd
    this.changed()
  }

  private track<T>(p: Promise<T>): Promise<T> {
    this.inFlight.add(p)
    p.finally(() => this.inFlight.delete(p)).catch(() => undefined)
    return p
  }

  setContext(ctx: CompanyContext): void {
    this.state.context = ctx
    this.changed()
  }

  private knownNames(): string[] {
    const ctx = this.state.context
    return [...new Set([...(ctx ? [ctx.company] : []), ...this.store.names(), ...this.memory.companies])]
  }

  // ---- audio events --------------------------------------------------------------------------

  private onAudio(e: SidecarEvent): void {
    switch (e.type) {
      case 'ready':
        this.state.audioReady = true
        if (this.state.phase === 'loading') this.state.phase = 'idle'
        this.sidecar.send({ cmd: 'devices' })
        break
      case 'devices':
        this.state.devices = e.devices
        break
      case 'level':
        this.state.level = e.rms
        break
      case 'speech':
        if (this.state.phase === 'live' && Date.now() - this.lastWarm > REWARM_AFTER_MS) this.warmUp()
        return
      case 'heard':
        if (this.state.phase !== 'live') return
        this.state.transcript.push({ at: Date.now(), text: e.text })
        break
      case 'line':
        if (this.state.phase !== 'live') return
        if (e.stt_ms) this.state.stats.sttMs = e.stt_ms
        this.emotion.send({ cmd: 'text', text: e.text })
        this.onLine(e.text)
        break
      case 'stopped':
        this.stopped?.()
        return
      case 'error':
        this.notify('error', e.message)
        return
      case 'exit':
        this.state.audioReady = false
        this.stopped?.()
        if (this.state.phase === 'live') this.notify('error', 'The audio engine stopped. Restarting it; this call has no audio until you start a new one.')
        break
    }
    this.changed()
  }

  // ---- call lifecycle ------------------------------------------------------------------------

  start(device: string): void {
    const ctx = this.state.context
    if (!ctx) throw new Error('Set up your company context first.')
    if (!this.state.audioReady) throw new Error('The audio engine is still starting.')
    Object.assign(this.state, {
      phase: 'live',
      startedAt: Date.now(),
      endedAt: null,
      transcript: [],
      advice: [],
      research: [],
      mood: null,
      stats: emptyStats(),
      debrief: null
    })
    this.moodErrorShown = false
    this.emotion.send({ cmd: 'start' })
    this.memory = CallMemory.parse({})
    this.lines = []
    this.memoryPending = []
    this.researched.clear()
    this.system = adviceSystem(ctx)
    this.warmUp()
    this.sidecar.send({ cmd: 'start', device, names: this.knownNames() })
    this.changed()
  }

  async stop(): Promise<void> {
    if (this.state.phase !== 'live') return
    this.state.phase = 'debriefing'
    this.state.endedAt = Date.now()
    this.changed()
    // Let the last words come through the audio engine, then let in-flight work land.
    await new Promise<void>((resolve) => {
      this.stopped = resolve
      this.sidecar.send({ cmd: 'stop' })
      setTimeout(resolve, 4000)
    })
    this.stopped = null
    this.emotion.send({ cmd: 'stop' })
    await Promise.race([Promise.allSettled([...this.inFlight]), new Promise((r) => setTimeout(r, 6000))])
    if (this.memoryTimer) clearTimeout(this.memoryTimer)
    await this.writeDebrief()
  }

  /** Leave the debrief: the call is gone unless it was saved. */
  backToMenu(): void {
    if (this.state.phase === 'live' || this.state.phase === 'debriefing') return
    Object.assign(this.state, {
      phase: this.state.audioReady ? 'idle' : 'loading',
      startedAt: null,
      endedAt: null,
      transcript: [],
      advice: [],
      research: [],
      mood: null,
      stats: emptyStats(),
      debrief: null
    })
    this.sidecar.send({ cmd: 'devices' })
    this.changed()
  }

  private warmUp(): void {
    this.lastWarm = Date.now()
    void warm(this.system).then((usd) => this.addCost(usd))
  }

  // ---- advice --------------------------------------------------------------------------------

  private onLine(text: string): void {
    const recent = this.lines.slice(-RECENT_LINES)
    this.lines.push(text)
    const given = this.state.advice.slice(-GIVEN_ADVICE).map((a) => a.advice)
    const id = this.lines.length
    const p = askJson(AdviceAnswer, this.system, adviceUser(this.memory, given, recent, text), {
      maxTokens: 80,
      hedgeMs: HEDGE_MS
    })
      .then((r) => {
        if (this.state.phase === 'idle') return
        const s = this.state.stats
        s.llmFirstMs = Math.round(r.firstMs)
        s.llmTotalMs = Math.round(r.totalMs)
        if (r.hedged) s.hedgeFired++
        this.addCost(r.costUsd)
        const advice = r.data.advice.trim()
        if (advice) {
          s.adviceCount++
          // Keep history in the order the prospect spoke, even if answers arrive out of order.
          this.state.advice.push({ id, at: Date.now(), heard: text, advice })
          this.state.advice.sort((a, b) => a.id - b.id)
        }
        if (r.data.company) this.research(r.data.company)
        this.changed()
      })
      .catch((e) => {
        this.addCost((e as { costUsd?: number }).costUsd ?? 0)
        this.notify('error', `No advice for that line: ${(e as Error).message}`)
      })
    this.track(p)
    this.memoryPending.push(text)
    this.scheduleMemory()
  }

  // ---- call memory (background, never blocks advice) ----------------------------------------

  private scheduleMemory(): void {
    if (this.memoryPending.length >= MEMORY_EVERY_LINES) {
      void this.updateMemory()
    } else if (!this.memoryTimer) {
      this.memoryTimer = setTimeout(() => void this.updateMemory(), MEMORY_MAX_WAIT_MS)
    }
  }

  private async updateMemory(): Promise<void> {
    if (this.memoryTimer) clearTimeout(this.memoryTimer)
    this.memoryTimer = null
    if (this.memoryBusy || !this.memoryPending.length) return
    this.memoryBusy = true
    const batch = this.memoryPending.splice(0)
    try {
      const r = await this.track(askJson(CallMemory, MEMORY_SYSTEM, memoryUser(this.memory, batch), { maxTokens: 600 }))
      this.addCost(r.costUsd)
      const before = this.memory.companies.join('|')
      this.memory = r.data
      if (this.memory.companies.join('|') !== before) this.sidecar.send({ cmd: 'names', names: this.knownNames() })
    } catch (e) {
      this.addCost((e as { costUsd?: number }).costUsd ?? 0)
      this.memoryPending.unshift(...batch) // try again with the next lines
    } finally {
      this.memoryBusy = false
      if (this.memoryPending.length >= MEMORY_EVERY_LINES) void this.updateMemory()
    }
  }

  // ---- research ------------------------------------------------------------------------------

  private research(name: string): void {
    const ctx = this.state.context
    const k = name.toLowerCase().replace(/[^a-z0-9]/g, '')
    if (!ctx || !k || this.researched.has(k) || k === ctx.company.toLowerCase().replace(/[^a-z0-9]/g, '')) return
    this.researched.add(k)
    if (!this.researcher.available && !this.store.find(name)) {
      this.notify('info', `Research is off: add TAVILY_API_KEY to .env to look up ${name}.`)
      return
    }
    const item = { name, status: 'searching' as const, bullets: [] as string[], sources: [] as { title: string; url: string }[] }
    this.state.research.push(item)
    this.state.stats.lookups++
    this.changed()
    const p = this.researcher
      .lookup(name, ctx)
      .then((found) => {
        this.addCost(found.costUsd)
        Object.assign(item, {
          name: found.record.name,
          status: 'done',
          bullets: found.record.bullets,
          sources: found.record.sources,
          origin: found.origin
        })
        this.changed()
        found.refresh?.then((updated) => {
          if (!updated) return
          Object.assign(item, { bullets: updated.bullets, sources: updated.sources, updated: true })
          this.changed()
        })
        this.sidecar.send({ cmd: 'names', names: this.knownNames() })
      })
      .catch((e) => {
        Object.assign(item, { status: 'failed' })
        this.notify('error', `Research on ${name} failed: ${(e as Error).message}`)
        this.changed()
      })
    this.track(p)
  }

  // ---- debrief -------------------------------------------------------------------------------

  private async writeDebrief(): Promise<void> {
    const ctx = this.state.context!
    try {
      if (this.memoryPending.length) await this.updateMemory()
      const r = await askJson(
        Debrief,
        debriefSystem(ctx),
        debriefUser(this.memory, this.state.transcript.map((t) => t.text), this.state.advice.map((a) => a.advice)),
        { maxTokens: 2000 }
      )
      this.addCost(r.costUsd)
      this.state.debrief = r.data
    } catch (e) {
      this.notify('error', `Could not write the debrief: ${(e as Error).message}`)
    }
    this.state.phase = 'debrief'
    this.changed()
  }
}
