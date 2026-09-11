/**
 * `ActionForm`: a JSON Schema in, a value out, and a server's refusal
 * landing on the field that caused it (`components/ActionForm.tsx`).
 *
 * Two things this suite is deliberately strict about:
 *
 * - **the round trip is nested.** A flat form would pass a test written
 *   over a flat schema and lose the object inside the object; the schema
 *   here has an object and an array under it, which is exactly what 10
 *   §Stack says RJSF is chosen for over a hand-written walker.
 * - **the 422 lands on the field.** `loc` is a path
 *   (`athanore/requests/validators.py`) and the assertion is on the
 *   element RJSF associates with that field — `<id>__error` — not merely
 *   on the message being somewhere on screen.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { RJSFSchema } from '@rjsf/utils'

import { ActionForm } from '../ActionForm'

/** An object with an object and an array inside it. */
const NESTED: RJSFSchema = {
  type: 'object',
  required: ['branch'],
  properties: {
    branch: { type: 'string', title: 'branch' },
    reviewer: {
      type: 'object',
      title: 'reviewer',
      properties: {
        name: { type: 'string', title: 'name' },
        blocking: { type: 'boolean', title: 'blocking' },
      },
    },
    labels: { type: 'array', title: 'labels', items: { type: 'string' } },
  },
}

const PREFIX = 'request-14'

/** The input RJSF gave the field at `path`, by the id it built. */
function field(path: string): HTMLElement {
  const id = `${PREFIX}_${path}`
  const element = document.getElementById(id)
  if (element === null) throw new Error(`no field ${id}`)
  return element
}

/** The errors RJSF drew beside the field at `path`. */
function fieldErrors(path: string): HTMLElement | null {
  return document.getElementById(`${PREFIX}_${path}__error`)
}

describe('a nested schema', () => {
  it('round-trips through the form', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ActionForm schema={NESTED} idPrefix={PREFIX} onSubmit={onSubmit} />)

    await user.type(field('branch'), 'feat/T064')
    await user.type(field('reviewer_name'), 'scott')
    await user.click(field('reviewer_blocking'))

    // An array is a control and not a text box: RJSF adds the entry, and
    // the entry is a field of its own, keyed by its index.
    await user.click(screen.getByRole('button', { name: /add item/i }))
    await user.type(field('labels_0'), 'gate')

    await user.click(screen.getByTestId('action-form-submit'))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit.mock.calls[0]?.[0]).toEqual({
      branch: 'feat/T064',
      reviewer: { name: 'scott', blocking: true },
      labels: ['gate'],
    })
  })

  it('refuses to submit a value the schema does not accept', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ActionForm schema={NESTED} idPrefix={PREFIX} onSubmit={onSubmit} />)

    // `branch` is required and empty: ajv8 refuses it before the POST.
    await user.click(screen.getByTestId('action-form-submit'))

    expect(onSubmit).not.toHaveBeenCalled()
    expect(fieldErrors('branch')).toHaveTextContent(/required/i)
  })

  it('clears the form when the operator cancels', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()

    render(
      <ActionForm
        schema={NESTED}
        idPrefix={PREFIX}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    )

    await user.type(field('branch'), 'feat/T064')
    await user.click(screen.getByTestId('action-form-cancel'))

    expect(field('branch')).toHaveValue('')
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})

describe('a refusal from the server', () => {
  const REFUSED = [
    { loc: ['branch'], msg: 'branch does not exist', type: 'value_error' },
    { loc: ['reviewer', 'name'], msg: 'unknown reviewer', type: 'value_error' },
  ]

  it('maps a 422 onto the fields its `loc` paths name', () => {
    // Rendered without a refusal and then with one, which is the order
    // it happens in: the operator submits, the server validates where
    // the answer lands (06 §Service), and the refusal comes back to a
    // form that is already on screen.
    const { rerender } = render(
      <ActionForm schema={NESTED} idPrefix={PREFIX} onSubmit={vi.fn()} />,
    )

    rerender(
      <ActionForm
        schema={NESTED}
        idPrefix={PREFIX}
        message="answer does not match the requested schema"
        errors={REFUSED}
        onSubmit={vi.fn()}
      />,
    )

    expect(fieldErrors('branch')).toHaveTextContent('branch does not exist')
    expect(fieldErrors('reviewer_name')).toHaveTextContent('unknown reviewer')
    expect(screen.getByTestId('action-form-message')).toHaveTextContent(
      'answer does not match the requested schema',
    )
  })

  it('drops the refusal as soon as the operator edits the value it was about', async () => {
    const user = userEvent.setup()

    const { rerender } = render(
      <ActionForm schema={NESTED} idPrefix={PREFIX} onSubmit={vi.fn()} />,
    )
    rerender(
      <ActionForm
        schema={NESTED}
        idPrefix={PREFIX}
        message="answer does not match the requested schema"
        errors={REFUSED}
        onSubmit={vi.fn()}
      />,
    )

    await user.type(field('branch'), 'x')

    expect(fieldErrors('branch')).toBeNull()
    expect(fieldErrors('reviewer_name')).toBeNull()
    expect(screen.queryByTestId('action-form-message')).not.toBeInTheDocument()
  })

  it('comes back when the server refuses the corrected value too', async () => {
    const user = userEvent.setup()

    const { rerender } = render(
      <ActionForm schema={NESTED} idPrefix={PREFIX} onSubmit={vi.fn()} />,
    )
    rerender(
      <ActionForm
        schema={NESTED}
        idPrefix={PREFIX}
        message="first refusal"
        errors={REFUSED}
        onSubmit={vi.fn()}
      />,
    )

    await user.type(field('branch'), 'x')
    expect(screen.queryByTestId('action-form-message')).not.toBeInTheDocument()

    // A new refusal is a new object, which is how the form tells it from
    // a re-render of the one it has already dismissed.
    rerender(
      <ActionForm
        schema={NESTED}
        idPrefix={PREFIX}
        message="second refusal"
        errors={[{ loc: ['branch'], msg: 'still no such branch', type: 'value_error' }]}
        onSubmit={vi.fn()}
      />,
    )

    expect(screen.getByTestId('action-form-message')).toHaveTextContent('second refusal')
    expect(fieldErrors('branch')).toHaveTextContent('still no such branch')
  })

  it('waits while a submission is in flight', () => {
    render(<ActionForm schema={NESTED} idPrefix={PREFIX} busy onSubmit={vi.fn()} />)

    expect(screen.getByTestId('action-form-submit')).toBeDisabled()
    expect(screen.getByTestId('action-form-cancel')).toBeDisabled()
    expect(screen.getByTestId('action-form-submit')).toHaveTextContent('sending…')
  })
})

/**
 * Arrays, which is where an RJSF theme usually breaks: the entry
 * controls are the theme's own buttons, and a theme that renders the
 * field but not its toolbar leaves an operator able to add a row and
 * never able to remove one.
 */
describe('an array', () => {
  /** An array of objects, and one of strings, under one root. */
  const ARRAYS: RJSFSchema = {
    type: 'object',
    properties: {
      labels: { type: 'array', title: 'labels', items: { type: 'string' } },
      reviewers: {
        type: 'array',
        title: 'reviewers',
        items: {
          type: 'object',
          properties: {
            name: { type: 'string', title: 'name' },
            blocking: { type: 'boolean', title: 'blocking' },
          },
        },
      },
    },
  }

  /** The `add item` control of the array whose fields start with `path`. */
  function addTo(path: string): HTMLElement {
    const controls = screen.getAllByRole('button', { name: /add item/i })
    const found = controls.find((control) =>
      control.closest('[id]')?.id.startsWith(`${PREFIX}_${path}`),
    )
    return found ?? controls[0]!
  }

  it('round-trips an array of objects, entry by entry', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ActionForm schema={ARRAYS} idPrefix={PREFIX} onSubmit={onSubmit} />)

    await user.click(addTo('reviewers'))
    await user.type(field('reviewers_0_name'), 'scott')
    await user.click(field('reviewers_0_blocking'))
    await user.click(addTo('reviewers'))
    await user.type(field('reviewers_1_name'), 'ana')

    await user.click(screen.getByTestId('action-form-submit'))

    expect(onSubmit.mock.calls[0]?.[0]).toEqual({
      reviewers: [
        { name: 'scott', blocking: true },
        { name: 'ana' },
      ],
    })
  })

  it('drops the entry the operator removes, and keeps the rest in order', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ActionForm schema={ARRAYS} idPrefix={PREFIX} onSubmit={onSubmit} />)

    for (const [index, label] of ['gate', 'review', 'merge'].entries()) {
      await user.click(addTo('labels'))
      await user.type(field(`labels_${String(index)}`), label)
    }

    const remove = screen.getAllByRole('button', { name: /remove/i })
    await user.click(remove[1]!)
    await user.click(screen.getByTestId('action-form-submit'))

    expect(onSubmit.mock.calls[0]?.[0]).toEqual({ labels: ['gate', 'merge'] })
  })

  it('reorders an entry without losing what is in it', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<ActionForm schema={ARRAYS} idPrefix={PREFIX} onSubmit={onSubmit} />)

    for (const [index, label] of ['gate', 'review'].entries()) {
      await user.click(addTo('labels'))
      await user.type(field(`labels_${String(index)}`), label)
    }

    await user.click(screen.getAllByRole('button', { name: /move up/i })[1]!)
    await user.click(screen.getByTestId('action-form-submit'))

    expect(onSubmit.mock.calls[0]?.[0]).toEqual({ labels: ['review', 'gate'] })
  })

  it('lands a 422 on the entry its `loc` index names', async () => {
    const user = userEvent.setup()

    const { rerender } = render(
      <ActionForm schema={ARRAYS} idPrefix={PREFIX} onSubmit={vi.fn()} />,
    )
    await user.click(addTo('reviewers'))
    await user.click(addTo('reviewers'))

    rerender(
      <ActionForm
        schema={ARRAYS}
        idPrefix={PREFIX}
        message="one reviewer is not on this project"
        errors={[
          { loc: ['reviewers', 1, 'name'], msg: 'unknown reviewer', type: 'value_error' },
        ]}
        onSubmit={vi.fn()}
      />,
    )

    // The index is a step of the path like any other: a validator that
    // raised on the second element must not mark the first
    // (`athanore/requests/validators.py`).
    expect(fieldErrors('reviewers_1_name')).toHaveTextContent('unknown reviewer')
    expect(fieldErrors('reviewers_0_name')).toBeNull()
  })
})

/**
 * A refusal whose `loc` the schema draws no field for. The summary line
 * exists so that a validator which knows more than the schema says is
 * still read: dropping it would leave the form silently refusing.
 */
describe('a refusal the schema has no field for', () => {
  it('keeps the whole of it in the line above the form', () => {
    // Mounted clean and then refused, which is the order it happens in:
    // the operator submits and the refusal comes back to a form that is
    // already on screen.
    const { rerender } = render(
      <ActionForm schema={NESTED} idPrefix={PREFIX} onSubmit={vi.fn()} />,
    )

    rerender(
      <ActionForm
        schema={NESTED}
        idPrefix={PREFIX}
        message="the branch is already merged"
        errors={[
          { loc: ['merge_base'], msg: 'no such ref', type: 'value_error' },
          { loc: [], msg: 'this answer contradicts itself', type: 'value_error' },
        ]}
        onSubmit={vi.fn()}
      />,
    )

    expect(screen.getByTestId('action-form-message')).toHaveTextContent(
      'the branch is already merged',
    )
    // Nothing was dropped on the floor and nothing crashed on a path
    // with no field at the end of it.
    expect(screen.getByTestId('action-form')).toBeInTheDocument()
  })
})
