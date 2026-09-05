import { ApiError, ask } from './api/client.ts'
import type { AskHistoryMessage } from './api/client.ts'
import type { AskResponse } from './api/types.ts'

// The conversation the user is in right now. Deliberately the SAME key the
// floating panel has always used: the panel and the full chat page are two
// views of one conversation, so expanding the panel into /chat carries the
// exchange across without a hand-off of its own.
const CURRENT_KEY = 'signal-desk:assistant-conversation'
// Everything the user has finished. Versioned, so a later shape change can
// be recognised and dropped rather than crashing a render on stale JSON.
const SESSIONS_KEY = 'signal-desk:chat-sessions:v1'

// A long demo must not be able to blow the storage quota, so both axes are
// capped: how many finished sessions are kept, and how many turns each one
// keeps. The live conversation keeps more (it is the one being read), the
// archived ones keep only enough to recognise and resume.
export const MAX_TURNS = 50
export const MAX_ARCHIVED_TURNS = 12
export const MAX_SESSIONS = 5
// What we send back to the service as conversational memory. Prompt size is
// cost, and cost is scored -- six messages is three exchanges, which is all
// a follow-up question ("and the week before?") actually needs.
export const MAX_HISTORY_MESSAGES = 6

export interface ChatTurn {
  id: string
  question: string
  // Present on a real reply from the service (including a withheld one --
  // withheld is carried on the response itself, not a separate error).
  response: AskResponse | null
  // Set only when the request itself failed -- distinct from a withheld
  // answer, which is a normal response the assistant chose not to give.
  error: string | null
}

export interface ChatSession {
  id: string
  startedAt: string
  turns: ChatTurn[]
}

export function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

// Every localStorage read and write is guarded (the repo's readHasBeenSeen
// pattern): private browsing, a disabled store and a full quota all throw,
// and none of them may take a render down with them. The safe default in
// each failure case is "this conversation does not persist", never a crash.
function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Nothing to do -- the conversation still works for this render, it
    // just won't survive a reload.
  }
}

function removeKey(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // Same reasoning as writeJson.
  }
}

export function loadCurrentTurns(): ChatTurn[] {
  return readJson<ChatTurn[]>(CURRENT_KEY, [])
}

export function saveCurrentTurns(turns: ChatTurn[]): void {
  writeJson(CURRENT_KEY, turns.slice(-MAX_TURNS))
}

/** Appends one exchange to the live conversation and returns the new list,
 * capped -- callers use the return value as their state so the rendered
 * conversation and the stored one can never disagree. */
export function appendTurn(turn: ChatTurn): ChatTurn[] {
  const next = [...loadCurrentTurns(), turn].slice(-MAX_TURNS)
  saveCurrentTurns(next)
  return next
}

export function loadSessions(): ChatSession[] {
  return readJson<ChatSession[]>(SESSIONS_KEY, []).filter(
    (session) => session && typeof session.id === 'string' && Array.isArray(session.turns),
  )
}

/** Upserts one finished session, newest first, capped on both axes. */
export function saveSession(session: ChatSession): void {
  if (session.turns.length === 0) return
  const trimmed = { ...session, turns: session.turns.slice(-MAX_ARCHIVED_TURNS) }
  const rest = loadSessions().filter((existing) => existing.id !== session.id)
  writeJson(SESSIONS_KEY, [trimmed, ...rest].slice(0, MAX_SESSIONS))
}

/** Archives whatever is on screen and hands back an empty conversation. An
 * empty current conversation archives nothing, so "New chat" on a fresh
 * page is a no-op rather than a list of blank sessions. */
export function startNewSession(): ChatTurn[] {
  const current = loadCurrentTurns()
  if (current.length > 0) {
    saveSession({ id: makeId(), startedAt: new Date().toISOString(), turns: current })
  }
  removeKey(CURRENT_KEY)
  return []
}

/** Switches to an archived session: the live one is archived first so
 * nothing is lost, and the resumed one becomes live. */
export function resumeSession(id: string): ChatTurn[] {
  const target = loadSessions().find((session) => session.id === id)
  if (!target) return loadCurrentTurns()
  startNewSession()
  writeJson(SESSIONS_KEY, loadSessions().filter((session) => session.id !== id))
  saveCurrentTurns(target.turns)
  return target.turns
}

export function clearAll(): void {
  removeKey(CURRENT_KEY)
  removeKey(SESSIONS_KEY)
}

/** The first question asked, which is what a person actually recognises a
 * past conversation by. */
export function sessionTitle(session: ChatSession): string {
  return session.turns[0]?.question ?? 'Empty conversation'
}

/** The optional `history` field of POST /api/ask: chronological, oldest
 * first, EXCLUDING the question being asked. A failed turn contributes
 * nothing (there is no assistant message to remember), and a withheld one
 * contributes its reason, which is genuinely what the assistant said. */
export function toHistoryMessages(turns: ChatTurn[], max = MAX_HISTORY_MESSAGES): AskHistoryMessage[] {
  const messages: AskHistoryMessage[] = []
  for (const turn of turns) {
    const said = turn.response?.answer ?? turn.response?.reason ?? null
    if (!said) continue
    messages.push({ role: 'user', content: turn.question })
    messages.push({ role: 'assistant', content: said })
  }
  return messages.slice(-max)
}

export interface AskOutcome {
  turn: ChatTurn
  /** True only for a 404 -- this build serves no /api/ask, so the feature
   * turns itself off. A 422, a 500 or a timeout is one question that
   * failed and must leave the composer enabled to retry. */
  endpointMissing: boolean
}

/** Asks one question, carrying the capped prior turns as `history`, and
 * maps every failure onto a turn the UI can render. Shared by the floating
 * panel and the full chat page so the two cannot drift on what a withheld
 * answer, a 404 and a 500 each mean. */
export async function askTurn(runId: string, question: string, priorTurns: ChatTurn[]): Promise<AskOutcome> {
  const id = makeId()
  try {
    const response = await ask(runId, question, toHistoryMessages(priorTurns))
    return { turn: { id, question, response, error: null }, endpointMissing: false }
  } catch (err) {
    const missing = err instanceof ApiError && err.status === 404
    return {
      turn: {
        id,
        question,
        response: null,
        error: missing
          ? 'This build does not serve the assistant endpoint.'
          : 'Could not reach the assistant -- try again in a moment.',
      },
      endpointMissing: missing,
    }
  }
}
