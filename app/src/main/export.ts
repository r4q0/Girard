// "Save call": one Word document with the debrief, stats and transcript.
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { Document, HeadingLevel, Packer, Paragraph, TextRun } from 'docx'
import type { AppState } from '@shared/schema'

const h = (text: string, level: (typeof HeadingLevel)[keyof typeof HeadingLevel] = HeadingLevel.HEADING_2) =>
  new Paragraph({ text, heading: level, spacing: { before: 240, after: 120 } })
const p = (text: string) => new Paragraph({ children: [new TextRun(text)], spacing: { after: 80 } })
const bullets = (items: string[]) => items.map((t) => new Paragraph({ text: t, bullet: { level: 0 } }))

function duration(ms: number): string {
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)} min ${s % 60} s`
}

export async function saveCallDocx(state: AppState, prospect: string, documentsDir: string): Promise<string> {
  const started = new Date(state.startedAt ?? Date.now())
  const date = started.toISOString().slice(0, 10)
  const safe = (prospect.trim() || 'Call').replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-')
  const dir = join(documentsDir, 'Girard', `${date}_${safe}`)
  mkdirSync(dir, { recursive: true })

  const d = state.debrief
  const s = state.stats
  const children: Paragraph[] = [
    h(`Call with ${prospect.trim() || 'prospect'}`, HeadingLevel.TITLE),
    p(`${started.toLocaleString()} · ${duration((state.endedAt ?? Date.now()) - started.getTime())} · ${state.context?.company ?? ''}`)
  ]
  if (d) {
    children.push(h('Summary'), p(d.summary))
    if (d.went_well.length) children.push(h('What went well'), ...bullets(d.went_well))
    if (d.improve.length) children.push(h('What to improve'), ...bullets(d.improve))
    if (d.needs.length) children.push(h('Customer needs'), ...bullets(d.needs))
    if (d.objections.length) children.push(h('Objections'), ...bullets(d.objections.map((o) => `${o.topic} (${o.status})`)))
    if (d.competitors.length) children.push(h('Competitors mentioned'), ...bullets(d.competitors))
    if (d.next_steps.length) children.push(h('Next steps'), ...bullets(d.next_steps))
  }
  children.push(
    h('Call stats'),
    ...bullets([
      `Advice shown: ${s.adviceCount}`,
      `Company lookups: ${s.lookups}`,
      `AI cost: $${s.costUsd.toFixed(4)}`
    ])
  )
  if (state.advice.length) children.push(h('Advice shown'), ...bullets(state.advice.map((a) => `${a.advice}  (after: "${a.heard}")`)))
  children.push(h('Transcript (prospect)'), ...state.transcript.map((t) => p(t.text)))

  const file = join(dir, `Girard call ${date} ${safe}.docx`)
  writeFileSync(file, await Packer.toBuffer(new Document({ sections: [{ children }] })))
  return file
}
