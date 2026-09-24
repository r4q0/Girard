// Fake bridge for checking layouts in a plain browser: ?demo=start | call | debrief
import type { AppState, GirardApi } from '@shared/schema'
import sample from '../../../resources/sample-context.json'

export function demoApi(): GirardApi {
  const mode = new URLSearchParams(location.search).get('demo') ?? 'start'
  const t0 = Date.now() - 252_000
  const state: AppState = {
    phase: mode === 'call' ? 'live' : mode === 'debrief' ? 'debrief' : 'idle',
    audioReady: true,
    devices: [
      { id: 'a', name: 'Headphones (AirPods Pro)', default: true },
      { id: 'b', name: 'Speakers (Realtek(R) Audio)', default: false }
    ],
    context: sample as AppState['context'],
    startedAt: t0,
    endedAt: t0 + 252_000,
    level: 0.06,
    transcript: [
      { at: t0 + 10_000, text: 'So basically we have three people who spend most of their morning typing incoming orders from email into Exact.' },
      { at: t0 + 30_000, text: "What's your hourly rate?" },
      { at: t0 + 60_000, text: "We're also talking to Flowbase, they said it would be about 40 cents per document." },
      { at: t0 + 90_000, text: 'Right now we use Zapier for some of it but it keeps breaking.' }
    ],
    advice: [
      { id: 1, at: t0 + 11_000, heard: 'three people … typing orders into Exact', advice: 'Ask how many orders per morning and minutes each to size the yearly cost.' },
      { id: 2, at: t0 + 31_000, heard: "What's your hourly rate?", advice: 'We work fixed price, not hourly. What do those three mornings cost per year?' },
      { id: 3, at: t0 + 61_000, heard: 'Flowbase, 40 cents per document', advice: 'Ask Flowbase’s yearly total at their volume: per-document fees grow, our price is fixed.' },
      { id: 4, at: t0 + 91_000, heard: 'Zapier … keeps breaking', advice: 'Ask which Zapier steps break and how often orders get delayed.' }
    ],
    research: [
      {
        name: 'Zapier',
        status: 'searching',
        bullets: [],
        sources: []
      },
      {
        name: 'Flowbase',
        status: 'done',
        origin: 'store',
        bullets: ['Document automation platform, self-service start.', 'Charges per processed document.', 'Koref: fixed price, Dutch hosting, liability after go-live.'],
        sources: [{ title: 'Flowbase pricing', url: 'https://www.example.com/pricing' }]
      }
    ],
    mood: { mood: 'skeptical', intensity: 0.46, valence: -0.3, engagement: 0.6, face: true, changes: 1 },
    stats: { costUsd: 0.0213, sttMs: 362, llmFirstMs: 431, llmTotalMs: 640, adviceCount: 4, hedgeFired: 1, lookups: 2 },
    debrief: {
      summary:
        'The prospect runs order entry by hand: three people type email orders into Exact every morning. They compared Koref with Flowbase at 40 cents per document and were burned by an IT supplier that went over budget. Pricing was asked twice, so it is not settled. The co-owner decides.',
      went_well: ['Kept the talk on the cost of the morning order entry', 'Fixed price answered the overrun worry'],
      improve: ['The hourly-rate question came back: explain the fixed price with their own numbers'],
      needs: ['Orders from email into Exact without typing', 'Replace the breaking Zapier steps'],
      objections: [
        { topic: 'Pricing model unclear', status: 'open' },
        { topic: 'Past supplier went over budget', status: 'answered' }
      ],
      competitors: ['Flowbase', 'Zapier'],
      next_steps: ['Send a one-page summary for the co-owner', 'Book the EUR 500 workflow assessment']
    }
  }
  return {
    send: async () => ({ ok: true }),
    onState: (listener) => {
      setTimeout(() => listener(state), 0)
      return () => undefined
    },
    onToast: () => () => undefined
  }
}
