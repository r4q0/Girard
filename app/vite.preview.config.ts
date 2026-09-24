// Screen-only dev server with demo data, for checking layouts in a browser: /?demo=start|call|debrief
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  root: resolve(__dirname, 'src/renderer'),
  resolve: { alias: { '@shared': resolve(__dirname, 'src/shared') } },
  plugins: [react(), tailwindcss()],
  server: { port: 5174, strictPort: true }
})
