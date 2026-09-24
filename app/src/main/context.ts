// The company context: what the advice model knows about the seller. Stored as JSON in the app's data folder.
import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { extractText, getDocumentProxy } from 'unpdf'
import { CompanyContext } from '@shared/schema'
import { askJson } from './llm'
import { CONTEXT_SYSTEM } from './prompts'

const MAX_CHARS = 120_000 // plenty for a few brochures; keeps the request fast

export function loadContext(file: string, sampleFile: string): CompanyContext {
  for (const f of [file, sampleFile]) {
    try {
      if (existsSync(f)) return CompanyContext.parse(JSON.parse(readFileSync(f, 'utf-8')))
    } catch (e) {
      console.warn(`company context ${f} unreadable`, e)
    }
  }
  throw new Error('No company context found.')
}

export function saveContext(file: string, ctx: CompanyContext): CompanyContext {
  const valid = CompanyContext.parse(ctx)
  writeFileSync(`${file}.tmp`, JSON.stringify(valid, null, 2))
  renameSync(`${file}.tmp`, file)
  return valid
}

/** PDFs (or text files) in, a draft company context out. The user reviews it before saving. */
export async function buildContext(files: { name: string; data: ArrayBuffer }[]): Promise<CompanyContext> {
  const parts: string[] = []
  for (const f of files) {
    if (f.name.toLowerCase().endsWith('.pdf')) {
      const pdf = await getDocumentProxy(new Uint8Array(f.data))
      const { text } = await extractText(pdf, { mergePages: true })
      parts.push(`=== ${f.name} ===\n${text}`)
    } else {
      parts.push(`=== ${f.name} ===\n${new TextDecoder().decode(f.data)}`)
    }
  }
  const docs = parts.join('\n\n').slice(0, MAX_CHARS)
  if (!docs.trim()) throw new Error('No text found in those files.')
  const r = await askJson(CompanyContext, CONTEXT_SYSTEM, `DOCUMENTS:\n${docs}`, { maxTokens: 4000 })
  return r.data
}
