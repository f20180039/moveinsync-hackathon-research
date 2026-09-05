import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AskResponse } from './api/types.ts'
import {
  MAX_ARCHIVED_TURNS,
  MAX_SESSIONS,
  MAX_TURNS,
  appendTurn,
  askTurn,
  clearAll,
  loadCurrentTurns,
  loadSessions,
  resumeSession,
  saveCurrentTurns,
  saveSession,
  sessionTitle,
  startNewSession,
  toHistoryMessages,
} from './chat.ts'
import type { ChatTurn } from './chat.ts'

function answer(text: string, overrides: Partial<AskResponse> = {}): AskResponse {
  return {
    runId: 'run-1',
    question: 'q',
    answer: text,
    withheld: false,
    reason: null,
    trace: [{ tool: 'query_findings', arguments: {}, result: {} }],
    ...overrides,
  }
}

function turn(question: string, said: string | null = 'an answer'): ChatTurn {
  return {
    id: `id-${question}`,
    question,
    response: said === null ? null : answer(said),
    error: said === null ? 'Could not reach the assistant -- try again in a moment.' : null,
  }
}

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response)
}

// What the deployed service actually answers when the run id has aged out
// of its in-process store -- a 404 that names the missing RUN.
function staleRunResponse(runId: string) {
  return Promise.resolve({
    ok: false,
    status: 404,
    statusText: 'Not Found',
    text: async () => JSON.stringify({ detail: { error: `no run '${runId}'` } }),
  } as Response)
}

function errorResponse(status: number, statusText: string) {
  return Promise.resolve({ ok: false, status, statusText, text: async () => '' } as Response)
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('the live conversation', () => {
  it('round-trips turns through localStorage', () => {
    saveCurrentTurns([turn('why is on-time low?')])
    expect(loadCurrentTurns()).toHaveLength(1)
    expect(loadCurrentTurns()[0].question).toBe('why is on-time low?')
  })

  it('appendTurn returns the new list and stores it', () => {
    appendTurn(turn('first'))
    const next = appendTurn(turn('second'))
    expect(next.map((t) => t.question)).toEqual(['first', 'second'])
    expect(loadCurrentTurns()).toHaveLength(2)
  })

  it('caps the live conversation, dropping the oldest turn', () => {
    saveCurrentTurns(Array.from({ length: MAX_TURNS }, (_, i) => turn(`q${i}`)))
    const next = appendTurn(turn('one more'))
    expect(next).toHaveLength(MAX_TURNS)
    expect(next[0].question).toBe('q1')
    expect(next.at(-1)?.question).toBe('one more')
  })

  it('reads back an empty conversation from junk, rather than throwing', () => {
    window.localStorage.setItem('signal-desk:assistant-conversation', 'not json at all')
    expect(loadCurrentTurns()).toEqual([])
  })
})

describe('sessions', () => {
  it('archives the live conversation and starts empty', () => {
    saveCurrentTurns([turn('why is on-time low?')])

    expect(startNewSession()).toEqual([])
    expect(loadCurrentTurns()).toEqual([])

    const sessions = loadSessions()
    expect(sessions).toHaveLength(1)
    expect(sessionTitle(sessions[0])).toBe('why is on-time low?')
  })

  it('archives nothing when the live conversation is empty', () => {
    startNewSession()
    expect(loadSessions()).toEqual([])
  })

  it(`keeps at most ${MAX_SESSIONS} sessions, newest first`, () => {
    for (let i = 0; i < MAX_SESSIONS + 3; i += 1) {
      saveCurrentTurns([turn(`session ${i}`)])
      startNewSession()
    }
    const sessions = loadSessions()
    expect(sessions).toHaveLength(MAX_SESSIONS)
    expect(sessionTitle(sessions[0])).toBe(`session ${MAX_SESSIONS + 2}`)
  })

  it('caps the turns kept per archived session', () => {
    saveCurrentTurns(Array.from({ length: MAX_ARCHIVED_TURNS + 6 }, (_, i) => turn(`q${i}`)))
    startNewSession()
    expect(loadSessions()[0].turns).toHaveLength(MAX_ARCHIVED_TURNS)
  })

  it('resuming a session makes it live and archives what was on screen', () => {
    saveCurrentTurns([turn('the older one')])
    startNewSession()
    saveCurrentTurns([turn('the current one')])

    const older = loadSessions()[0]
    const resumed = resumeSession(older.id)

    expect(resumed.map((t) => t.question)).toEqual(['the older one'])
    expect(loadCurrentTurns().map((t) => t.question)).toEqual(['the older one'])
    // The conversation that was on screen is not lost, and the resumed one
    // is no longer also sitting in the archive.
    expect(loadSessions().map(sessionTitle)).toEqual(['the current one'])
  })

  it('resuming an unknown session leaves the live conversation alone', () => {
    saveCurrentTurns([turn('still here')])
    expect(resumeSession('no-such-session').map((t) => t.question)).toEqual(['still here'])
  })

  it('saveSession ignores an empty session', () => {
    saveSession({ id: 'empty', startedAt: '2026-09-05T09:00:00Z', turns: [] })
    expect(loadSessions()).toEqual([])
  })

  it('clearAll removes both the live conversation and the archive', () => {
    saveCurrentTurns([turn('a')])
    startNewSession()
    saveCurrentTurns([turn('b')])

    clearAll()

    expect(loadCurrentTurns()).toEqual([])
    expect(loadSessions()).toEqual([])
  })
})

describe('when localStorage itself throws (private browsing, quota, disabled)', () => {
  function breakStorage() {
    const boom = () => {
      throw new Error('storage is not available')
    }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(boom)
  }

  it('reads degrade to empty rather than crashing a render', () => {
    breakStorage()
    expect(loadCurrentTurns()).toEqual([])
    expect(loadSessions()).toEqual([])
  })

  it('writes are swallowed, and appendTurn still returns a usable list', () => {
    breakStorage()
    expect(() => saveCurrentTurns([turn('a')])).not.toThrow()
    expect(() => saveSession({ id: 's', startedAt: 'now', turns: [turn('a')] })).not.toThrow()
    expect(appendTurn(turn('a')).map((t) => t.question)).toEqual(['a'])
  })

  it('starting and clearing still work without storage', () => {
    breakStorage()
    expect(startNewSession()).toEqual([])
    expect(() => clearAll()).not.toThrow()
  })
})

describe('toHistoryMessages', () => {
  it('pairs each turn as user then assistant, oldest first', () => {
    expect(toHistoryMessages([turn('one', 'first answer'), turn('two', 'second answer')])).toEqual([
      { role: 'user', content: 'one' },
      { role: 'assistant', content: 'first answer' },
      { role: 'user', content: 'two' },
      { role: 'assistant', content: 'second answer' },
    ])
  })

  it('caps the messages sent, keeping the most recent -- prompt size is cost', () => {
    const messages = toHistoryMessages(Array.from({ length: 10 }, (_, i) => turn(`q${i}`, `a${i}`)))
    expect(messages).toHaveLength(6)
    expect(messages[0]).toEqual({ role: 'user', content: 'q7' })
  })

  it('drops a failed turn -- there is no assistant message to remember', () => {
    expect(toHistoryMessages([turn('failed', null), turn('worked', 'yes')])).toEqual([
      { role: 'user', content: 'worked' },
      { role: 'assistant', content: 'yes' },
    ])
  })

  it('carries the plain-language message a withheld turn actually showed', () => {
    const withheld: ChatTurn = {
      id: 't-withheld',
      question: 'what will OTA be next month?',
      response: answer('', {
        answer: null,
        withheld: true,
        reason: 'answer contained a figure no tool returned: 14.8',
        message: 'I held this answer back because one number could not be traced.',
      }),
      error: null,
    }

    expect(toHistoryMessages([withheld])).toEqual([
      { role: 'user', content: 'what will OTA be next month?' },
      { role: 'assistant', content: 'I held this answer back because one number could not be traced.' },
    ])
  })

  it('carries a withheld reason, which is what the assistant actually said', () => {
    const withheld: ChatTurn = {
      id: 'w',
      question: 'what about next month?',
      response: answer('', { answer: null, withheld: true, reason: 'Outside this window.' }),
      error: null,
    }
    expect(toHistoryMessages([withheld])).toEqual([
      { role: 'user', content: 'what about next month?' },
      { role: 'assistant', content: 'Outside this window.' },
    ])
  })
})

describe('askTurn', () => {
  it('posts the prior turns as `history`, oldest first, excluding the question asked', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      jsonResponse(answer('because Vendor C slipped')),
    )
    vi.stubGlobal('fetch', fetchMock)

    const outcome = await askTurn('run-1', 'and the week before?', [turn('why is on-time low?', 'Vendor C')])

    expect(outcome.endpointMissing).toBe(false)
    expect(outcome.turn.response?.answer).toBe('because Vendor C slipped')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      runId: 'run-1',
      question: 'and the week before?',
      history: [
        { role: 'user', content: 'why is on-time low?' },
        { role: 'assistant', content: 'Vendor C' },
      ],
    })
  })

  it('omits `history` entirely on the first question', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse(answer('an answer')))
    vi.stubGlobal('fetch', fetchMock)

    await askTurn('run-1', 'why is on-time low?', [])

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      runId: 'run-1',
      question: 'why is on-time low?',
    })
  })

  it('reports a 404 with no run named as a genuinely missing endpoint', async () => {
    vi.stubGlobal('fetch', vi.fn(() => errorResponse(404, 'Not Found')))
    const outcome = await askTurn('run-1', 'anything', [])
    expect(outcome.endpointMissing).toBe(true)
    expect(outcome.turn.error).toMatch(/does not serve the assistant endpoint/i)
  })

  it('retries against the latest run when the run the console holds has aged out', async () => {
    // The service keeps sweeping (and restarts) while the console holds the
    // run id it loaded at startup, so this 404 is routine -- and it names
    // the missing RUN, not a missing route.
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body))
      if (body.runId === 'latest') return jsonResponse(answer('on-time fell to 88%'))
      return staleRunResponse(body.runId)
    })
    vi.stubGlobal('fetch', fetchMock)

    const outcome = await askTurn('run-1785542400000-b0', 'why did on-time fall?', [])

    expect(outcome.endpointMissing).toBe(false)
    expect(outcome.turn.error).toBeNull()
    expect(outcome.turn.response?.answer).toBe('on-time fell to 88%')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).runId).toBe('latest')
  })

  it('an aged-out run never reports the build as lacking the endpoint', async () => {
    // Even when the retry fails too: the endpoint answered, twice. Claiming
    // the build has no assistant is both false and unrecoverable -- it
    // disabled a working assistant for the rest of the session.
    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
        staleRunResponse(JSON.parse(String(init?.body)).runId),
      ),
    )

    const outcome = await askTurn('run-1785542400000-b0', 'why did on-time fall?', [])

    expect(outcome.endpointMissing).toBe(false)
    expect(outcome.turn.error).toMatch(/sweep has expired/i)
  })

  it('does not retry when the question already asked for the latest run', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      staleRunResponse(JSON.parse(String(init?.body)).runId),
    )
    vi.stubGlobal('fetch', fetchMock)

    const outcome = await askTurn('latest', 'why did on-time fall?', [])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(outcome.endpointMissing).toBe(false)
  })

  it('reports a 500 as one failed question, leaving the endpoint available', async () => {
    vi.stubGlobal('fetch', vi.fn(() => errorResponse(500, 'Internal Server Error')))
    const outcome = await askTurn('run-1', 'anything', [])
    expect(outcome.endpointMissing).toBe(false)
    expect(outcome.turn.error).toMatch(/could not reach the assistant/i)
  })
})
