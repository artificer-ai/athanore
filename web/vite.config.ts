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
    /**
     * Every asset is a file under `/assets`, never a `data:` URL inlined
     * into the CSS. The server serves the build under the policy of 12
     * §Plugins, whose `font-src 'self'` does not permit `data:`: Vite's
     * default 4096-byte limit inlines the smallest JetBrains Mono subset
     * (cyrillic-ext), and the browser then refuses to load it. Inlining
     * saves one request for the smallest of six subsets; 10 §Design
     * system says the fonts are bundled and `font-src 'self'` holds, so
     * the limit goes to zero rather than the policy gaining `data:`.
     */
    assetsInlineLimit: 0,
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
