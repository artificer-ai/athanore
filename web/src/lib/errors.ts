/**
 * Reading a refusal the API sent.
 *
 * The generated client throws the parsed error body — `{error, code}`,
 * the API's one error shape (`docs/v1/08-api.md` §Conventions) — rather
 * than an `Error`, so every surface that prints what a request was
 * refused with reads the same two shapes and assumes neither.
 */

/** What a refused request said, or `fallback` when it said nothing. */
export function actionError(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null) {
    const message = (error as { error?: unknown }).error
    if (typeof message === 'string' && message !== '') return message
    if (error instanceof Error && error.message !== '') return error.message
  }
  if (typeof error === 'string' && error.trim() !== '') return error
  return fallback
}
