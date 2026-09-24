// Company research: a local JSON store first, Tavily when unknown or older than 7 days.
import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { tavily } from '@tavily/core'
import { ResearchAnswer, ResearchRecord, type CompanyContext } from '@shared/schema'
import { askJson } from './llm'
import { researchSystem } from './prompts'

const FRESH_MS = 7 * 24 * 3600 * 1000

/** "HubSpot CRM", "Hub Spot", "hubspot.com" -> "hubspot" */
function key(name: string): string {
  return name
    .toLowerCase()
    .replace(/\.(com|io|ai|nl|net|org)\b/g, '')
    .replace(/\b(inc|ltd|llc|bv|b\.v\.|gmbh|group|crm|software|app)\b/g, '')
    .replace(/[^a-z0-9]/g, '')
}

function similar(a: string, b: string): boolean {
  if (a === b) return true
  if (a.length < 4 || b.length < 4) return false
  // Levenshtein ratio, enough for "flowbase" vs "flowbass".
  const d: number[][] = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)])
  for (let j = 1; j <= b.length; j++) d[0][j] = j
  for (let i = 1; i <= a.length; i++)
    for (let j = 1; j <= b.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
  return 1 - d[a.length][b.length] / Math.max(a.length, b.length) >= 0.85
}

export class ResearchStore {
  private records: ResearchRecord[] = []

  constructor(private file: string) {
    try {
      if (existsSync(file)) this.records = ResearchRecord.array().parse(JSON.parse(readFileSync(file, 'utf-8')))
    } catch (e) {
      console.warn('research store unreadable, starting empty', e)
    }
  }

  names(): string[] {
    return this.records.map((r) => r.name)
  }

  find(name: string): ResearchRecord | undefined {
    const k = key(name)
    return this.records.find((r) => [r.name, ...r.aliases].some((n) => similar(key(n), k)))
  }

  save(record: ResearchRecord, heardAs: string): void {
    const existing = this.find(record.name) ?? this.find(heardAs)
    if (existing) {
      const aliases = new Set([...existing.aliases, heardAs, record.name].filter((a) => a !== existing.name))
      Object.assign(existing, { ...record, name: existing.name, aliases: [...aliases] })
    } else {
      this.records.push({ ...record, aliases: heardAs !== record.name ? [heardAs] : [] })
    }
    const tmp = `${this.file}.tmp`
    writeFileSync(tmp, JSON.stringify(this.records, null, 1))
    renameSync(tmp, this.file) // atomic: a crash never leaves a half-written store
  }
}

export type Lookup = {
  record: ResearchRecord
  origin: 'store' | 'fresh'
  /** For an old record: resolves with the refreshed record if anything changed. */
  refresh?: Promise<ResearchRecord | null>
  costUsd: number
}

export class Researcher {
  private tvly: ReturnType<typeof tavily> | null

  constructor(
    private store: ResearchStore,
    tavilyKey: string | undefined
  ) {
    this.tvly = tavilyKey ? tavily({ apiKey: tavilyKey }) : null
  }

  get available(): boolean {
    return this.tvly !== null
  }

  async lookup(name: string, ctx: CompanyContext): Promise<Lookup> {
    const stored = this.store.find(name)
    if (stored) {
      const fresh = Date.now() - Date.parse(stored.fetched_at) < FRESH_MS
      if (fresh || !this.tvly) return { record: stored, origin: 'store', costUsd: 0 }
      const refresh = this.search(name, ctx).then(({ record }) => {
        const changed = record.bullets.join('|') !== stored.bullets.join('|')
        this.store.save(record, name)
        return changed ? record : null
      })
      refresh.catch(() => undefined)
      return { record: stored, origin: 'store', refresh, costUsd: 0 }
    }
    const { record, costUsd } = await this.search(name, ctx)
    this.store.save(record, name)
    return { record, origin: 'fresh', costUsd }
  }

  private async search(name: string, ctx: CompanyContext): Promise<{ record: ResearchRecord; costUsd: number }> {
    if (!this.tvly) throw new Error('Research is off: add TAVILY_API_KEY to .env')
    const res = await this.tvly.search(`${name} company what they do pricing`, { maxResults: 5, searchDepth: 'basic' })
    const results = res.results.slice(0, 5)
    if (!results.length) throw new Error(`No search results for ${name}`)
    const sources = results.map((r) => `TITLE: ${r.title}\nURL: ${r.url}\n${r.content.slice(0, 700)}`).join('\n\n')
    const answer = await askJson(ResearchAnswer, researchSystem(ctx), `COMPANY: ${name}\n\nSEARCH RESULTS:\n${sources}`, {
      maxTokens: 300
    })
    return {
      record: {
        name,
        aliases: [],
        bullets: answer.data.bullets,
        sources: results.slice(0, 3).map((r) => ({ title: r.title, url: r.url })),
        fetched_at: new Date().toISOString()
      },
      costUsd: answer.costUsd
    }
  }
}
