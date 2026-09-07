import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.tsx'
import './index.css'

const container = document.getElementById('root')
if (!container) throw new Error('index.html is missing <div id="root">')

const root = createRoot(container)
const mount = (node: ReactNode) => root.render(<StrictMode>{node}</StrictMode>)

/**
 * The token page of T057 (`src/dev/Tokens.tsx`), on its own path because
 * the router arrives with the app shell in T058. `import.meta.env.DEV` is
 * replaced with `false` at build time, so the branch — and with it the
 * dynamic import — is dropped from the production bundle: `/__tokens` is
 * a dev-server address and nothing the app ships.
 */
if (import.meta.env.DEV && window.location.pathname === '/__tokens') {
  void import('./dev/Tokens.tsx').then(({ Tokens }) => mount(<Tokens />))
} else {
  mount(<App />)
}
