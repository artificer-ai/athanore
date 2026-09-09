import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'

import { RouterProvider } from '@tanstack/react-router'

import './index.css'
import { AppGate } from './app/AppGate'
import { Providers } from './app/providers'
import { router } from './routes/router'
import { syncFontSize } from './store/prefs'

const container = document.getElementById('root')
if (!container) throw new Error('index.html is missing <div id="root">')

/**
 * The operator's type scale, on `<html>` before anything renders
 * (21 §Type scale, D196).
 *
 * `usePrefs` hydrates from `localStorage` synchronously as its module is
 * evaluated — the import above has already done it — so the base is set
 * before the first paint rather than after one at the wrong size. Both
 * branches below are under it, `/__tokens` included: the token page
 * renders the same ramp.
 */
syncFontSize()

const root = createRoot(container)
const mount = (node: ReactNode) => root.render(<StrictMode>{node}</StrictMode>)

/**
 * The token page of T057 (`src/dev/Tokens.tsx`), on its own path because
 * the app's router owns exactly one route, `/` (T058).
 * `import.meta.env.DEV` is replaced with `false` at build time, so the
 * branch — and with it the dynamic import — is dropped from the
 * production bundle: `/__tokens` is a dev-server address and nothing the
 * app ships.
 */
if (import.meta.env.DEV && window.location.pathname === '/__tokens') {
  void import('./dev/Tokens.tsx').then(({ Tokens }) => mount(<Tokens />))
} else {
  mount(
    <Providers>
      <AppGate>
        <RouterProvider router={router} />
      </AppGate>
    </Providers>,
  )
}
