import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import type { AppState, Command, CommandResult, Toast } from '@shared/schema'
import { CallEngine } from './call'
import { buildContext, loadContext, saveContext } from './context'
import { saveCallDocx } from './export'
import { initLlm } from './llm'
import { Researcher, ResearchStore } from './research'
import { Sidecar } from './sidecar'

const ROOT = resolve(app.getAppPath(), '..') // repo root: holds .env and audio/

function readEnv(): Record<string, string> {
  const file = join(ROOT, '.env')
  if (!existsSync(file)) return {}
  const env: Record<string, string> = {}
  for (const line of readFileSync(file, 'utf-8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/)
    if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '')
  }
  return env
}

let win: BrowserWindow | null = null
const env = { ...readEnv(), ...process.env }
const data = app.getPath('userData')
const contextFile = join(data, 'company-context.json')
const sampleContext = join(app.getAppPath(), 'resources', 'sample-context.json')

const sidecar = new Sidecar(join(ROOT, 'audio'), 'girard_audio', 'audio')
const emotion = new Sidecar(join(ROOT, 'emotion'), 'girard_emotion', 'mood')
const store = new ResearchStore(join(data, 'research-store.json'))
const engine = new CallEngine(
  sidecar,
  emotion,
  new Researcher(store, env.TAVILY_API_KEY),
  store,
  (state: AppState) => win?.webContents.send('girard:state', state),
  (toast: Toast) => {
    console.warn(`[${toast.kind}]`, toast.text)
    win?.webContents.send('girard:toast', toast)
  }
)

async function handle(c: Command): Promise<CommandResult> {
  try {
    switch (c.cmd) {
      case 'refreshDevices':
        sidecar.send({ cmd: 'devices' })
        win?.webContents.send('girard:state', engine.state)
        return { ok: true }
      case 'start':
        engine.start(c.device)
        return { ok: true }
      case 'stop':
        await engine.stop()
        return { ok: true }
      case 'backToMenu':
        engine.backToMenu()
        return { ok: true }
      case 'saveCall': {
        const file = await saveCallDocx(engine.state, c.prospect, app.getPath('documents'))
        shell.showItemInFolder(file)
        return { ok: true, data: file }
      }
      case 'saveContext':
        engine.setContext(saveContext(contextFile, c.context))
        return { ok: true }
      case 'buildContext':
        return { ok: true, data: await buildContext(c.files) }
    }
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 820,
    minHeight: 560,
    backgroundColor: '#0e0f11',
    title: 'Girard',
    autoHideMenuBar: true,
    webPreferences: { preload: join(__dirname, '../preload/index.js'), contextIsolation: true, sandbox: true }
  })
  win.webContents.on('did-finish-load', () => win?.webContents.send('girard:state', engine.state))
  // Research source links open in the normal browser, never inside the app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) void shell.openExternal(url)
    return { action: 'deny' }
  })
  if (process.env.ELECTRON_RENDERER_URL) void win.loadURL(process.env.ELECTRON_RENDERER_URL)
  else void win.loadFile(join(__dirname, '../renderer/index.html'))
}

app.whenReady().then(() => {
  ipcMain.handle('girard:cmd', (_e, c: Command) => handle(c))
  if (!env.NEBIUS_API_KEY) engine.notify('error', 'NEBIUS_API_KEY is missing from .env: advice is off.')
  else initLlm(env.NEBIUS_API_KEY)
  try {
    engine.setContext(loadContext(contextFile, sampleContext))
  } catch (e) {
    engine.notify('error', (e as Error).message)
  }
  sidecar.start()
  emotion.start()
  createWindow()
  if (env.GIRARD_SELFTEST) void selfTest(Number(env.GIRARD_SELFTEST))
})

/** GIRARD_SELFTEST=<seconds>: run one call on the default output, then log the result, save it and quit. */
async function selfTest(seconds: number): Promise<void> {
  const log = (...a: unknown[]) => console.log('[selftest]', ...a)
  while (!engine.state.audioReady || !engine.state.devices.length) await new Promise((r) => setTimeout(r, 300))
  const device = engine.state.devices.find((d) => d.default) ?? engine.state.devices[0]
  log('start on', device.name)
  engine.start(device.id)
  const moodLog: string[] = []
  emotion.on('event', (e) => e.type === 'mood' && e.changed && moodLog.push(`${e.mood}${e.face ? '+face' : ''}`))
  await new Promise((r) => setTimeout(r, seconds * 1000))
  log('stop')
  await engine.stop()
  const s = engine.state
  for (const a of s.advice) log('ADVICE', JSON.stringify(a.heard), '->', a.advice)
  for (const r of s.research) log('RESEARCH', r.name, r.status, r.origin ?? '', JSON.stringify(r.bullets))
  log('MOOD', JSON.stringify(moodLog))
  log('STATS', JSON.stringify(s.stats))
  log('DEBRIEF', JSON.stringify(s.debrief))
  log('SAVED', await saveCallDocx(s, 'Selftest', app.getPath('temp')))
  app.quit()
}

app.on('window-all-closed', () => app.quit())
app.on('will-quit', () => {
  sidecar.shutdown()
  emotion.shutdown()
})
