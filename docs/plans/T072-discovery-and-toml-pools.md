# T072 — Entry-point discovery and `athanore.toml` pools

**Task.** `docs/v1/17-serial-task-plan.md` § `### T072`.
**Specs.** `docs/v1/09-plugins.md` §Discovery; `docs/v1/11-cli.md`
§serve; `docs/v1/02-architecture.md` §Configuration.

## What this task is

How a workflow gets found without being named on the command line, and
how pools are configured without code.

## What this task is not

- No implicit imports beyond the declared entry-point group.
- No silent fallback for a misconfigured pool: an unknown pool name in
  `athanore.toml` **exits 2**, it does not quietly use the default.

## Steps

1. `athanore/plugins/discovery.py`: `discover() -> list[Workflow]` from
   `importlib.metadata.entry_points(group="athanore.workflows")`,
   accepting `module:attr` or a callable.
2. `serve`: a `--no-discover` flag; read `[pools]` and `[workflows]`
   from `athanore.toml` (`Pool(name, n)`); an unknown pool name → exit
   2; **explicit targets override discovery for the same name**; the
   default pool is `Pool("default", workers)` for unbound workflows.
3. Document the precedence in 09 and 11 — it is the kind of rule people
   only learn when it surprises them.

## Verification

`tests/cli/test_discovery.py`, with a fake distribution registered
through a temporary `entry_points` shim:

- discovery finds it;
- `--no-discover` does not;
- an explicit target of the same name wins;
- an unknown pool name exits 2 with a message naming the pool.

## Done

- Tests pass; precedence documented in 09 and 11.
- `**Status.** Done.` on `### T072`, in the same commit.

## Files

```
athanore/plugins/discovery.py
athanore/cli/serve.py
docs/v1/{09-plugins.md,11-cli.md}
tests/cli/test_discovery.py
docs/v1/17-serial-task-plan.md
```
