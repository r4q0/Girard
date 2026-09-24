// Starts a Python engine (audio or mood) and talks to it in JSON lines; see each engine's __main__.py.
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { createInterface } from 'node:readline'
import { EventEmitter } from 'node:events'

export type SidecarEvent =
  | { type: 'ready'; load_ms: number }
  | { type: 'devices'; devices: { id: string; name: string; default: boolean }[] }
  | { type: 'started'; device: string }
  | { type: 'stopped' }
  | { type: 'level'; rms: number }
  | { type: 'speech' }
  | { type: 'heard'; text: string; audio_end: number }
  | { type: 'line'; text: string; rule: string; audio_end: number; stt_ms: number; filter_us: number }
  | { type: 'mood'; mood: Mood; intensity: number; valence: number; engagement: number; face: boolean; changed: boolean }
  | { type: 'error'; message: string; fatal?: boolean }
  | { type: 'exit'; code: number | null }

export type Mood = 'positive' | 'interested' | 'neutral' | 'skeptical' | 'worried' | 'annoyed'

export class Sidecar extends EventEmitter {
  private proc: ChildProcessWithoutNullStreams | null = null
  private stopping = false
  private restarts = 0

  constructor(
    private dir: string,
    private module: string,
    private label: string
  ) {
    super()
  }

  start(): void {
    this.stopping = false
    const python = join(this.dir, '.venv', 'Scripts', 'python.exe')
    const [cmd, args] = existsSync(python)
      ? [python, ['-m', this.module]]
      : ['uv', ['run', 'python', '-m', this.module]]
    const proc = spawn(cmd, args, { cwd: this.dir, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    this.proc = proc
    createInterface({ input: proc.stdout }).on('line', (line) => {
      try {
        const event = JSON.parse(line) as SidecarEvent
        if (event.type === 'ready') this.restarts = 0
        this.emit('event', event)
      } catch {
        console.warn(`[${this.label}] not JSON:`, line)
      }
    })
    createInterface({ input: proc.stderr }).on('line', (line) => console.warn(`[${this.label}]`, line))
    proc.on('error', (err) => this.emit('event', { type: 'error', message: `The ${this.label} engine failed to start: ${err.message}` }))
    proc.on('exit', (code) => {
      this.proc = null
      this.emit('event', { type: 'exit', code })
      if (this.stopping) return
      // Restart the engine so the next call works; the running call carries on without audio.
      if (this.restarts < 3) {
        this.restarts++
        setTimeout(() => this.start(), 1000 * this.restarts)
      }
    })
  }

  send(cmd: Record<string, unknown>): void {
    if (!this.proc) {
      this.emit('event', { type: 'error', message: `The ${this.label} engine is not running.` })
      return
    }
    this.proc.stdin.write(JSON.stringify(cmd) + '\n')
  }

  shutdown(): void {
    this.stopping = true
    if (!this.proc) return
    try {
      // The engine exits on "quit" and also when its input closes, so it never outlives the app.
      this.proc.stdin.end(JSON.stringify({ cmd: 'quit' }) + '\n')
    } catch {
      // already gone
    }
  }
}
