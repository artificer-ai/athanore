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
  parser: {
    filters: {
      // Naming a filter at all turns on the parser's orphan pruning;
      // keeping orphans is what the generated tree looked like before,
      // and the event payload schemas of 18 are reachable only through
      // the envelope union, which this generator leaves opaque.
      orphans: true,
      operations: {
        // `GET /api/events` is the SSE feed (08 §Events). The SPA reads
        // it with `EventSource` and never with the fetch client — a
        // stream that does not end is not a request/response — and the
        // generator's cursor heuristic reads its `after` parameter as
        // pagination, emitting infinite-query options that cannot type
        // an `ServerSentEventsResult`. It stays in the OpenAPI document,
        // which is the contract; it is simply not something this client
        // can call.
        exclude: ['GET /api/events'],
      },
    },
  },
  output: {
    path: 'src/api/gen',
    // No formatter or linter pass over generated output: the freshness
    // check compares bytes, and a post-pass is one more tool that can
    // differ between a laptop and CI.
    postProcess: [],
  },
  plugins: ['@hey-api/client-fetch', '@tanstack/react-query'],
})
