import { useState } from 'react'
import type { CompanyContext } from '@shared/schema'
import { api } from '../api'

type Props = { context: CompanyContext | null; onClose: () => void; onError: (text: string) => void }

// Editable text form of the context: lists are one item per line, rows use " | " between columns.
type Draft = Record<string, string>

const TEXT_FIELDS: [keyof CompanyContext, string, string][] = [
  ['company', 'Company name', ''],
  ['what_we_do', 'What we do', ''],
  ['positioning', 'Positioning', ''],
  ['main_message', 'Main message', ''],
  ['guarantee', 'Guarantee', ''],
  ['cost_formula', 'How to work out what their problem costs', ''],
  ['ideal_customer', 'Ideal customer', ''],
  ['tone', 'Tone', '']
]
const LIST_FIELDS: [keyof CompanyContext, string, string][] = [
  ['usps', 'What makes us different', 'one per line'],
  ['facts', 'Facts the rep may use', 'one per line'],
  ['never_say', 'Never say', 'one per line']
]

function toDraft(c: CompanyContext | null): Draft {
  const d: Draft = {}
  for (const [k] of TEXT_FIELDS) d[k] = c ? String(c[k] ?? '') : ''
  for (const [k] of LIST_FIELDS) d[k] = c ? (c[k] as string[]).join('\n') : ''
  d.offerings = c ? c.offerings.map((o) => [o.name, o.price, o.details].join(' | ')).join('\n') : ''
  d.differentiators_vs = c ? c.differentiators_vs.map((o) => [o.against, o.they_win, o.we_win].join(' | ')).join('\n') : ''
  return d
}

function fromDraft(d: Draft): CompanyContext {
  const lines = (s: string) => s.split('\n').map((l) => l.trim()).filter(Boolean)
  const cols = (s: string) => s.split('|').map((x) => x.trim())
  const ctx: Record<string, unknown> = {}
  for (const [k] of TEXT_FIELDS) ctx[k] = d[k].trim()
  for (const [k] of LIST_FIELDS) ctx[k] = lines(d[k])
  ctx.offerings = lines(d.offerings).map((l) => {
    const [name, price = '', details = ''] = cols(l)
    return { name, price, details }
  })
  ctx.differentiators_vs = lines(d.differentiators_vs).map((l) => {
    const [against, they_win = '', we_win = ''] = cols(l)
    return { against, they_win, we_win }
  })
  return ctx as CompanyContext
}

export function ContextEditor({ context, onClose, onError }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(context))
  const [building, setBuilding] = useState(false)
  const [hover, setHover] = useState(false)
  const set = (k: string, v: string) => setDraft((d) => ({ ...d, [k]: v }))

  const build = async (files: FileList | File[]) => {
    const list = [...files].filter((f) => /\.(pdf|txt|md)$/i.test(f.name))
    if (!list.length) return onError('Drop PDF or text files.')
    setBuilding(true)
    const r = await api.send({
      cmd: 'buildContext',
      files: await Promise.all(list.map(async (f) => ({ name: f.name, data: await f.arrayBuffer() })))
    })
    setBuilding(false)
    if (r.ok) setDraft(toDraft(r.data as CompanyContext))
    else onError(r.error)
  }

  const save = async () => {
    if (!draft.company.trim()) return onError('Give the company a name.')
    const r = await api.send({ cmd: 'saveContext', context: fromDraft(draft) })
    if (r.ok) onClose()
    else onError(r.error)
  }

  const field = 'w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-accent'

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-8 py-10">
        <div className="flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">Company context</h1>
          <div className="flex gap-4 text-sm">
            <button onClick={onClose} className="text-muted hover:text-ink">
              Cancel
            </button>
            <button onClick={() => void save()} className="rounded-lg bg-live px-4 py-1.5 font-semibold text-black">
              Save
            </button>
          </div>
        </div>
        <p className="mt-1 text-sm text-muted">What Girard knows about what you sell. Advice only uses what is here.</p>

        <label
          onDragOver={(e) => {
            e.preventDefault()
            setHover(true)
          }}
          onDragLeave={() => setHover(false)}
          onDrop={(e) => {
            e.preventDefault()
            setHover(false)
            void build(e.dataTransfer.files)
          }}
          className={`mt-8 flex cursor-pointer flex-col items-center rounded-lg border border-dashed px-6 py-8 text-center text-sm ${
            hover ? 'border-accent bg-accent/5' : 'border-line'
          }`}
        >
          <input type="file" multiple accept=".pdf,.txt,.md" className="hidden" onChange={(e) => e.target.files && void build(e.target.files)} />
          {building ? (
            <span className="text-muted">Reading your documents…</span>
          ) : (
            <>
              <span>Drop PDFs about your business here, or click to pick them</span>
              <span className="mt-1 text-xs text-faint">Girard fills in the fields below. Check them before saving.</span>
            </>
          )}
        </label>

        <div className="mt-8 space-y-5">
          {TEXT_FIELDS.map(([k, label]) => (
            <div key={k}>
              <label className="text-xs font-medium tracking-wide text-muted uppercase">{label}</label>
              {k === 'company' || k === 'main_message' ? (
                <input value={draft[k]} onChange={(e) => set(k, e.target.value)} className={`${field} mt-1.5`} />
              ) : (
                <textarea value={draft[k]} onChange={(e) => set(k, e.target.value)} rows={2} className={`${field} mt-1.5 resize-y`} />
              )}
            </div>
          ))}
          {LIST_FIELDS.map(([k, label, hint]) => (
            <Area key={k} label={label} hint={hint} value={draft[k]} onChange={(v) => set(k, v)} className={field} />
          ))}
          <Area label="Offerings" hint="one per line: name | price | details" value={draft.offerings} onChange={(v) => set('offerings', v)} className={field} />
          <Area
            label="Against the alternatives"
            hint="one per line: alternative | where they win | where we win"
            value={draft.differentiators_vs}
            onChange={(v) => set('differentiators_vs', v)}
            className={field}
          />
        </div>
      </div>
    </div>
  )
}

function Area(p: { label: string; hint: string; value: string; onChange: (v: string) => void; className: string }) {
  return (
    <div>
      <label className="text-xs font-medium tracking-wide text-muted uppercase">
        {p.label} <span className="normal-case text-faint">· {p.hint}</span>
      </label>
      <textarea
        value={p.value}
        onChange={(e) => p.onChange(e.target.value)}
        rows={Math.min(10, Math.max(3, p.value.split('\n').length + 1))}
        className={`${p.className} mt-1.5 resize-y`}
      />
    </div>
  )
}
