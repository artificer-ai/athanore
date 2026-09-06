import { defineConfig } from '@hey-api/openapi-ts'

/**
 * The SPA's API client is generated, never written (02 §One wire
 * contract). The input is the committed snapshot rather than a running
 * server, so `pnpm gen` needs nothing but the checkout, and the two
 * halves of the contract move in one commit.
 *
 * Output lands in `src/api/gen`, which is committed as generated: CI's
 * `contract` job regenerates it and fails if the tree is stale.
 */
export default defineConfig({
  input: '../tests/snapshots/openapi.json',
  output: {
    path: 'src/api/gen',
    // No formatter or linter pass over generated output: the freshness
    // check compares bytes, and a post-pass is one more tool that can
    // differ between a laptop and CI.
    postProcess: [],
  },
  plugins: ['@hey-api/client-fetch', '@tanstack/react-query'],
})
