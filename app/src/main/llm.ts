// GLM-5.2 on Nebius Token Factory for every job: advice, call memory, research summaries, debrief.
import OpenAI from 'openai'
import type { z } from 'zod'
import { cleanDeep } from '@shared/text'

export const MODEL = 'zai-org/GLM-5.2'
const BASE_URL = 'https://api.tokenfactory.nebius.com/v1'
// Fallback list prices (USD per token) if the price lookup fails.
let price = { prompt: 0.0000014, completion: 0.0000044 }

let client: OpenAI | null = null

export function initLlm(apiKey: string): void {
  client = new OpenAI({ baseURL: BASE_URL, apiKey, timeout: 30_000, maxRetries: 0 })
  void loadPrices(apiKey)
}

async function loadPrices(apiKey: string): Promise<void> {
  try {
    const res = await fetch(`${BASE_URL}/models?verbose=true`, { headers: { Authorization: `Bearer ${apiKey}` } })
    const body = (await res.json()) as { data: { id: string; pricing?: { prompt: string; completion: string } }[] }
    const p = body.data.find((m) => m.id === MODEL)?.pricing
    if (p) price = { prompt: Number(p.prompt), completion: Number(p.completion) }
  } catch {
    // keep the fallback prices
  }
}

export type Usage = { prompt: number; completion: number }
export const costOf = (u: Usage): number => u.prompt * price.prompt + u.completion * price.completion

export type CallResult<T> = {
  data: T
  firstMs: number
  totalMs: number
  hedged: boolean
  /** Everything this call cost, including a hedge copy and a retry. */
  costUsd: number
}

type Options = {
  maxTokens: number
  /** Fire one duplicate if no token has arrived after this many ms; first to stream wins. */
  hedgeMs?: number
  temperature?: number
  signal?: AbortSignal
}

type Attempt = { text: string; firstMs: number; usage: Usage }

function extractJson(text: string): unknown {
  const m = text.match(/\{[\s\S]*\}/)
  if (!m) throw new Error('no JSON in answer')
  return JSON.parse(m[0])
}

/** One streamed request. Resolves `first` as soon as the first token arrives. */
function stream(
  messages: OpenAI.Chat.ChatCompletionMessageParam[],
  opts: Options,
  abort: AbortController
): { first: Promise<void>; done: Promise<Attempt> } {
  if (!client) throw new Error('AI client not initialised (NEBIUS_API_KEY missing?)')
  const t0 = performance.now()
  let firstMs = -1
  let resolveFirst!: () => void
  const first = new Promise<void>((r) => (resolveFirst = r))
  const done = (async () => {
    const s = await client!.chat.completions.create(
      {
        model: MODEL,
        messages,
        max_tokens: opts.maxTokens,
        temperature: opts.temperature ?? 0,
        stream: true,
        stream_options: { include_usage: true },
        // GLM-5.2 thinks by default; live advice cannot wait for that.
        reasoning_effort: 'none' as never
      },
      { signal: abort.signal }
    )
    let text = ''
    let usage: Usage = { prompt: 0, completion: 0 }
    for await (const chunk of s) {
      const delta = chunk.choices[0]?.delta?.content
      if (delta) {
        if (firstMs < 0) {
          firstMs = performance.now() - t0
          resolveFirst()
        }
        text += delta
      }
      if (chunk.usage) usage = { prompt: chunk.usage.prompt_tokens, completion: chunk.usage.completion_tokens }
    }
    resolveFirst()
    return { text, firstMs: firstMs < 0 ? performance.now() - t0 : firstMs, usage }
  })()
  done.catch(() => resolveFirst())
  return { first, done }
}

async function once(
  messages: OpenAI.Chat.ChatCompletionMessageParam[],
  opts: Options
): Promise<{ attempt: Attempt; hedged: boolean; costUsd: number }> {
  const a = new AbortController()
  opts.signal?.addEventListener('abort', () => a.abort())
  const first = stream(messages, opts, a)
  if (!opts.hedgeMs) {
    const attempt = await first.done
    return { attempt, hedged: false, costUsd: costOf(attempt.usage) }
  }
  const timer = new Promise<'late'>((r) => setTimeout(() => r('late'), opts.hedgeMs))
  const race = await Promise.race([first.first.then(() => 'first' as const), timer])
  if (race === 'first') {
    const attempt = await first.done
    return { attempt, hedged: false, costUsd: costOf(attempt.usage) }
  }
  // No token yet: fire a copy; whichever starts streaming first wins, the other is cancelled.
  const b = new AbortController()
  opts.signal?.addEventListener('abort', () => b.abort())
  const second = stream(messages, opts, b)
  const winner = await Promise.race([first.first.then(() => 0), second.first.then(() => 1)])
  const [win, lose, loseAbort] = winner === 0 ? [first, second, b] : [second, first, a]
  loseAbort.abort()
  lose.done.catch(() => undefined)
  const attempt = await win.done
  // A cancelled request still pays for its prompt; its usage never arrives, so assume the same prompt size.
  const costUsd = costOf(attempt.usage) + costOf({ prompt: attempt.usage.prompt, completion: 0 })
  return { attempt, hedged: true, costUsd }
}

/** Ask for JSON matching `schema`. One retry on an invalid answer; never returns unvalidated data. */
export async function askJson<S extends z.ZodTypeAny>(
  schema: S,
  system: string,
  user: string,
  opts: Options
): Promise<CallResult<z.infer<S>>> {
  const messages: OpenAI.Chat.ChatCompletionMessageParam[] = [
    { role: 'system', content: system },
    { role: 'user', content: user }
  ]
  const t0 = performance.now()
  let cost = 0
  let lastError: unknown
  for (let i = 0; i < 2; i++) {
    const { attempt, hedged, costUsd } = await once(messages, opts)
    cost += costUsd
    try {
      // Em dashes are removed here, so no AI text anywhere in Girard ever shows one.
      const data = schema.parse(cleanDeep(extractJson(attempt.text)))
      return { data, firstMs: attempt.firstMs, totalMs: performance.now() - t0, hedged, costUsd: cost }
    } catch (e) {
      lastError = e
    }
  }
  const err = new Error(`AI answer was not valid: ${String(lastError)}`) as Error & { costUsd: number }
  err.costUsd = cost
  throw err
}

/** Tiny request that warms the model and connection for this system prompt. */
export async function warm(system: string): Promise<number> {
  if (!client) return 0
  try {
    const r = await client.chat.completions.create({
      model: MODEL,
      max_tokens: 1,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: 'ok' }
      ],
      reasoning_effort: 'none' as never
    })
    return costOf({ prompt: r.usage?.prompt_tokens ?? 0, completion: r.usage?.completion_tokens ?? 0 })
  } catch {
    return 0
  }
}
