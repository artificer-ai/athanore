# T031 — Requests service

**Task.** `docs/v1/17-serial-task-plan.md` § `### T031`.
**Specs.** `docs/v1/06-requests.md` §Service (the signatures, verbatim)
and §Lifecycle (pending / stale / answered / consumed).
**Reference.** v0's `tests/test_requests.py` — ported here, ledger row
ticked.

## What this task is

The service that opens a request, accepts exactly one answer, and lets a
waiter block until it arrives. The missed-wake guard is the part to get
right.

## What this task is not

- No `human_input` (T033) and no agent policies (T035+).
- No HTTP. The endpoints arrive in T038.
- Do not re-validate what T030's validators already check.

## Steps

1. `class RequestService(store, bus)` with 06's signatures.
2. `create` → uow insert plus `request.opened {request_id, mode, kind}`.
3. `answer(request_id, *, option_id=None, value=None, author="user")`:
   load the view; `StaleRequest` when neither pending nor answered;
   `AlreadyAnswered` when answered; then the mode checks — `options`:
   the id must be one of the offered options; `text`: a non-empty `str`;
   `form`: a `dict`, run the registered validator if any and **store its
   normalised return**, not the raw input. One uow: `answers.insert`
   plus `request.answered {request_id, author}`. Map `IntegrityError`
   onto `AlreadyAnswered` — the unique constraint is the real race
   guard; the pre-check is just a nicer message.
4. `wait(request_id, timeout)`: **subscribe first, then re-check the
   store.** An answer that lands between the store read and the
   subscription is the classic missed wake-up, and the test for it is
   explicitly in the task. Then loop the queue until the matching id,
   `mark_consumed`, and raise `TimeoutError` on expiry.
5. `poll(request_id, wait_s)`: the same without consuming; returns
   `None` on expiry.
6. `register_validator` / `unregister_validator` on a dict;
   `list_for_run`, `inbox`, `view(id)` delegating to the repo.

## Verification

`tests/requests/test_service.py`, porting v0's file:

- two concurrent waiters on different requests each get their own
  answer (keyed, not broadcast);
- a second answer raises `AlreadyAnswered`;
- a request goes stale once its task finishes;
- validator normalisation is what gets stored;
- **`wait` sees an answer that landed before it subscribed** — the
  missed-wake test;
- `timeout` raises `TimeoutError`.

## Done

- Tests pass; `docs/porting-ledger.md` row for `tests/test_requests.py`
  ticked.
- `**Status.** Done.` on `### T031`, in the same commit.

## Files

```
athanore/requests/service.py
tests/requests/test_service.py
docs/porting-ledger.md
docs/v1/17-serial-task-plan.md
```
