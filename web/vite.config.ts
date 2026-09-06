import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vitest/config'

const here = dirname(fileURLToPath(import.meta.url))

/** Where `pnpm build` writes, and what the wheel ships as package data. */
const OUT_DIR = resolve(here, '../athanore/web/dist')

/**
 * `emptyOutDir` deletes everything in the output directory except `.git`,
 * and the output directory is a tracked, git-ignored-except-`.gitkeep`
 * directory in this repository. Without this the first build leaves the
 * checkout dirty with a deleted `.gitkeep`, which the build gate reads as
 * uncommitted work.
 */
function keepOutDirTracked(): Plugin {
  return {
    name: 'athanore:keep-out-dir-tracked',
    apply: 'build',
    writeBundle() {
      mkdirSync(OUT_DIR, { recursive: true })
      writeFileSync(resolve(OUT_DIR, '.gitkeep'), '')
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), keepOutDirTracked()],
  resolve: {
    alias: { '@': resolve(here, 'src') },
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
  },
  server: {
    // The SPA talks to the Athanore server and nothing else (02 §One wire
    // contract). Loopback needs no operator token (12 §Auth).
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:4002',
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test-setup.ts'],
  },
})
