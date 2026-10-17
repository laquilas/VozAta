# Phase 24 — Ask the meeting

## Goal

Ask questions in natural language about one meeting or all meetings ("what did we decide about the
beta?", "who owns the migration?") and get streamed answers with clickable timestamp citations.

## Depends on

09, 22

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §5 (`LanguageModel.stream`), §8 (transcript precedence),
  §10 (answers in `APP_LANGUAGE`), §12 (`LLM_MAX_CHARS`)
- [api-contract.md](../api-contract.md) — `POST /ask`, `answer_chunk`, `answer_done`
- Phase 22 file (search index API)

## Scope

**Engine**

| File | Content |
|------|---------|
| `qa/retriever.py` | single session: whole transcript when it fits `LLM_MAX_CHARS`, else FTS hits ± 2 neighbouring segments; all sessions: FTS hits (terms from the question minus localized stopwords) ranked, grouped per session, trimmed to the budget |
| `qa/answerer.py` | `MeetingAnswerer(llm, retriever, localizer)`: localized prompt requiring citations as `[session_id@hh:mm:ss]`, streams chunks, parses citations into `{session_id, segment_id, start}`; answers "not found in the meetings" when context is empty |
| `locales/*.toml` | prompt texts and stopword lists per language |
| API | `POST /ask` → `answer_id`, background streaming via `answer_chunk` / `answer_done` |

**UI**: chat panel in session detail (scoped) and in History (all sessions); streamed text;
citations rendered as links that open the session at that time.

## Design notes

- Never send more than `LLM_MAX_CHARS` of context.
- The model must answer only from the provided context — tested via prompt content, verified
  manually.

## Acceptance criteria

- [ ] Tests: retriever budget and neighbour expansion (temp index), citation parsing (valid,
      malformed, unknown session ignored), streaming order with `FakeLanguageModel`, empty-context
      answer, API events.
- [ ] UI tests: streamed text accumulation, citation navigation, concurrent questions blocked.
- [ ] Manual: three questions in pt-BR about a recorded meeting return correct answers with working
      citations.
- [ ] Resource parity test passes.

## Tests

`tests/qa/test_retriever.py`, `test_answerer.py`, `tests/api/test_ask.py`, `AskViewModelTests.cs`.

## Out of scope

Embedding-based semantic retrieval, conversation memory across questions (backlog).

## Kickoff prompt

> Execute phase 24 of the roadmap (`docs/roadmap/phases/24-ask-the-meeting.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/24-ask-the-meeting`
- **Status:** in progress
- **Updated:** 2026-10-17 12:00
- **Next step:** UI: `AskViewModel` (+ `AskViewModelTests.cs`), `AskView` in `HistoryView`, routing of answer events in `MainViewModel`

### Steps

- [x] Engine: domain `Citation`, locale prompt texts and stopwords (en, pt-BR, es) — `c8aec7c`
- [x] Engine: `qa/retriever.py` (single-session budget + neighbours, all-sessions ranking) — `c8aec7c`
- [x] Engine: `qa/citations.py` + `qa/answerer.py` (`MeetingAnswerer`, streaming, empty context) — `19a4faa`
- [x] Engine: `POST /ask`, `AskJob` streaming `answer_chunk` / `answer_done`, wiring in `bootstrap.py` — `be4a3d2`
- [x] Docs: api-contract and architecture — `95e75a7`
- [x] UI client: `AskAsync`, `AnswerChunkEvent`, `AnswerDoneEvent` (`VozAta.Client/Ask.cs`)
- [ ] UI: `AskViewModel` + panel (History, scoped to the selected session or all sessions)
- [ ] Acceptance criteria, manual check recipe, PR

### Decisions and notes

- `TranscriptSearch.search` ANDs every word, so the retriever searches each keyword on its own
  and ranks segments by how many keywords they match, then by best rank (port unchanged).
- Context lines use the full segment text from the session's best transcript (§8), not the
  search snippet; sessions/segments indexed but no longer on disk are skipped.
- A long single session without hits gives an empty context, so the answer is "not found".
- Citations: a bracket may hold several items; a bare `[hh:mm:ss]` is accepted when the context
  has one session; a time maps to the last context segment shown at or before it.
- Contract additions: `answer_done.error` (null or a localized message; the UI needs to know the
  answer failed), `409 answer_in_progress`, `503 ask_unavailable`. One question at a time in the
  engine too (VRAM). Before the LLM loads, a kept Whisper is released unless a recording uses it.
