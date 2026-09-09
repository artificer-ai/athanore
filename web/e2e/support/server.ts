/**
 * One `athanore serve` per test, and the handle the specs drive it by
 * (`docs/v1/17-serial-task-plan.md` § T068a).
 *
 * The suite runs against the real thing: the built SPA served by the
 * server that serves the API, the engine dispatching behind it, and
 * `FakeACPAgent` in place of every agent façade — which is what
 * `ATHANORE_AGENT_COMMAND` is for (13 §Running examples on the fake).
 * Nothing is stubbed in the browser, and no model is ever in the loop.
 *
 * **A server per test, on an ephemeral port, over a temporary root.**
 * `ATHANORE_ROOT_PATH` is a fresh directory, so the SQLite file, the
 * `athanore.toml` that binds the pools and the operator token are that
 * test's alone and two specs can never read each other's runs. `--port
 * 0` means they can also run at the same time; the port a server got is
 * knowable only from the line it prints once the socket exists (11
 * §Server), so that line is what is waited for.
 *
 * **The port is remembered, because one spec needs it twice.** The
 * server-down spec kills the process and starts it again, and the SPA in
 * the browser has to find the same origin when it does — otherwise the
 * banner is testing a page that was pointed at nothing. {@link
 * AthanoreServer.start} therefore re-binds the port the first start was
 * given.
 *
 * **The child is its own process group.** `uv run` is a parent of the
 * server, so a signal sent to the pid it returns is not necessarily one
 * the server sees; `detached` plus a kill of `-pid` reaches both, which
 * is what makes "kill the server" mean it.
 */
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

/** The checkout: `web/e2e/support` is three directories down from it. */
const ROOT = resolve(here, '../../..')

/** The fixture workflows, as `athanore serve` targets (11 §Server). */
const WORKFLOWS = join(ROOT, 'web', 'e2e', 'workflows.py')

/** One scenario file per node, picked by the fake off the prompt (13). */
const SCENARIOS = join(ROOT, 'web', 'e2e', 'scenarios')

/** The workflows this server runs, as `path.py:attr` (11 §Server). */
const TARGETS = ['probe', 'spread', 'hold'].map(
  (name) => `${WORKFLOWS}:${name}`,
)

/** The line `announce` prints once the socket exists (11 §Server). */
const SERVING = /Athanore is serving on (http:\/\/\S+)/

/** How long a server gets to bind and answer before the test fails. */
const START_TIMEOUT_MS = 60_000

/** How long a stopped server gets to exit before it is killed outright. */
const STOP_TIMEOUT_MS = 5_000

/** How often {@link waitFor} looks again. */
const POLL_MS = 100

/**
 * `uv run --no-sync`, which is how everything in this repository reaches
 * the project's environment: the `athanore` console script is in the
 * managed venv rather than on `PATH`, and `--no-sync` keeps a test from
 * resolving dependencies on the way past.
 */
const UV = 'uv'
const UV_ARGS = ['run', '--no-sync', '--project', ROOT]

let fakeAgent: string[] | null = null

/**
 * `FakeACPAgent`, as the argv `ATHANORE_AGENT_COMMAND` is set to.
 *
 * Asked of the interpreter rather than assembled here: the fake is
 * `[sys.executable, athanore/testing/fake_acp.py]`
 * (`athanore.testing.scenarios.FAKE_ACP`), and the interpreter that runs
 * the server is the only thing that knows which python that is. Memoised
 * per worker process, so the cost is one subprocess for a whole file of
 * specs.
 */
function fakeAgentCommand(): string[] {
  if (fakeAgent !== null) return fakeAgent
  const probe = spawnSync(
    UV,
    [
      ...UV_ARGS,
      'python',
      '-c',
      'import json; from athanore.testing import FAKE_ACP; print(json.dumps(FAKE_ACP))',
    ],
    { cwd: ROOT, encoding: 'utf8' },
  )
  if (probe.status !== 0) {
    throw new Error(
      `could not read athanore.testing.FAKE_ACP (exit ${String(probe.status)}):\n` +
        `${probe.stderr}`,
    )
  }
  fakeAgent = JSON.parse(probe.stdout.trim()) as string[]
  return fakeAgent
}

/** Poll `check` until it is true, or fail saying what was waited for. */
async function waitFor(
  what: string,
  check: () => boolean | Promise<boolean>,
  timeoutMs: number,
): Promise<void> {
  const endsAt = Date.now() + timeoutMs
  for (;;) {
    if (await check()) return
    if (Date.now() > endsAt) {
      throw new Error(`timed out after ${String(timeoutMs)}ms waiting for ${what}`)
    }
    await new Promise((done) => setTimeout(done, POLL_MS))
  }
}

/** Whether a server is answering at `url`. */
async function answering(url: string): Promise<boolean> {
  try {
    const response = await fetch(`${url}/api/health`)
    return response.ok
  } catch {
    return false
  }
}

export class AthanoreServer {
  /** The base URL the SPA and the API are both served on. */
  url = ''

  /** The temporary `ATHANORE_ROOT_PATH`: database, token, config. */
  private readonly root = mkdtempSync(join(tmpdir(), 'athanore-e2e-'))

  private child: ChildProcess | null = null

  /** Everything the child has written, for a failure to be readable. */
  private output = ''

  /** The port the first bind was given, and every later one asks for. */
  private port = 0

  /** Start the server and return once it answers `GET /api/health`. */
  async start(): Promise<void> {
    if (this.child !== null) throw new Error('the server is already running')
    this.output = ''
    const child = spawn(UV, [...UV_ARGS, 'athanore', 'serve', ...TARGETS], {
      cwd: ROOT,
      detached: true,
      env: {
        ...process.env,
        // The one setting that puts the fake behind every façade (05, 13).
        ATHANORE_AGENT_COMMAND: JSON.stringify(fakeAgentCommand()),
        ATHANORE_FAKE_SCENARIOS: SCENARIOS,
        ATHANORE_ROOT_PATH: this.root,
        ATHANORE_HOST: '127.0.0.1',
        ATHANORE_PORT: String(this.port),
        // One worker. It is the default, and it is said out loud
        // because three specs depend on it: `hold` fills the pool and
        // everything submitted behind it stays `queued` (`workflows.py`).
        ATHANORE_WORKERS: '1',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    this.child = child
    const collect = (chunk: Buffer | string) => {
      this.output += String(chunk)
    }
    child.stdout?.on('data', collect)
    child.stderr?.on('data', collect)
    child.on('exit', () => {
      this.child = null
    })

    // Every failure below reports what the child printed, because that
    // is where the reason is: a target that is not a workflow, a port
    // already taken, an environment that was never synced.
    await this.expect(
      'the server to announce its port',
      () => SERVING.test(this.output) || this.child === null,
    )
    const announced = SERVING.exec(this.output)
    if (announced?.[1] === undefined) {
      throw new Error(`the server exited before it served:\n${this.dump()}`)
    }
    this.url = announced[1]
    this.port = Number(new URL(this.url).port)
    await this.expect(`${this.url}/api/health to answer`, () => answering(this.url))
  }

  /** {@link waitFor} with the child's output on the failure. */
  private async expect(
    what: string,
    check: () => boolean | Promise<boolean>,
  ): Promise<void> {
    try {
      await waitFor(what, check, START_TIMEOUT_MS)
    } catch (cause) {
      throw new Error(`waiting for ${what}; the server said:\n${this.dump()}`, {
        cause,
      })
    }
  }

  /**
   * Kill the server and wait until nothing answers on its port.
   *
   * `SIGKILL` rather than the graceful stop of 04 §Shutdown: this is the
   * spec's "the server went away", and a server that drained first would
   * be testing something else. Waiting for the port to go quiet is what
   * keeps the restart from binding under a socket that is still open.
   */
  async kill(): Promise<void> {
    const child = this.child
    if (child === null) return
    this.signal(child, 'SIGKILL')
    await waitFor(
      'the server process to exit',
      () => this.child === null,
      STOP_TIMEOUT_MS,
    )
    await waitFor(
      'the port to go quiet',
      async () => !(await answering(this.url)),
      STOP_TIMEOUT_MS,
    )
  }

  /**
   * Stop the server and remove its root.
   *
   * `SIGTERM` first, which is the graceful stop `serve` installs a
   * handler for, and `SIGKILL` after the budget: `hold`'s node sleeps
   * for an hour and a test must not.
   */
  async stop(): Promise<void> {
    const child = this.child
    if (child !== null) {
      this.signal(child, 'SIGTERM')
      try {
        await waitFor('the server to stop', () => this.child === null, STOP_TIMEOUT_MS)
      } catch {
        // The graceful stop of 04 §Shutdown did not finish inside the
        // budget. Nothing here is worth draining — the database is about
        // to be deleted — so the process goes, and it is waited for so
        // that no test leaves one behind.
        this.signal(child, 'SIGKILL')
        await waitFor(
          'the server process to exit',
          () => this.child === null,
          STOP_TIMEOUT_MS,
        ).catch(() => undefined)
      }
    }
    rmSync(this.root, { recursive: true, force: true })
  }

  /** Signal the whole process group: `uv run` is a parent, not the server. */
  private signal(child: ChildProcess, signal: NodeJS.Signals): void {
    if (child.pid === undefined) return
    try {
      process.kill(-child.pid, signal)
    } catch {
      // Already gone, or never a group leader: the direct signal is
      // still worth sending, and a dead pid throws here too.
      try {
        child.kill(signal)
      } catch {
        /* it is gone */
      }
    }
  }

  /** What the child said, for an assertion failure to be diagnosable. */
  private dump(): string {
    return this.output === '' ? '(the server printed nothing)' : this.output
  }
}
