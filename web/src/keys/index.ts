/**
 * The keyboard map: one listener, and the scopes that decide when it is
 * off (T067).
 *
 * The table itself — the keycaps, their labels and the groups the `?`
 * overlay draws them under — is `lib/keys.ts`, which the footer and that
 * overlay read too.
 */
export {
  answerKeysAt,
  claimKeyboard,
  keyboardOwned,
  registerAnswerKeys,
  useAnswerKeys,
  useKeyOwner,
  type AnswerKeys,
} from './scope'
export {
  capOf,
  handleKey,
  isTyping,
  useKeymap,
  LIST_REGION,
  type KeymapAction,
  type KeymapHandlers,
} from './useKeymap'
