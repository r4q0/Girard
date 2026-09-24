import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const shared = { '@shared': resolve(__dirname, 'src/shared') }

export default defineConfig({
  main: { resolve: { alias: shared } },
  // Sandboxed preloads cannot require node_modules, so bundle everything into it.
  preload: { resolve: { alias: shared }, build: { externalizeDeps: false } },
  renderer: { resolve: { alias: shared }, plugins: [react(), tailwindcss()] }
})
