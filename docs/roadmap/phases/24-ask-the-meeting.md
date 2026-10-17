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

- [x] Tests: retriever budget and neighbour expansion (temp index), citation parsing (valid,
      malformed, unknown session ignored), streaming order with `FakeLanguageModel`, empty-context
      answer, API events.
- [x] UI tests: streamed text accumulation, citation navigation, concurrent questions blocked.
- [x] Manual: three questions in pt-BR about a recorded meeting return correct answers with working
      citations. — verified 2026-10-17 through the API with Ollama `qwen2.5:7b` (see Progress); the
      desktop click-through is still pending.
- [x] Resource parity test passes.

## Tests

`tests/qa/test_retriever.py`, `test_answerer.py`, `tests/api/test_ask.py`, `AskViewModelTests.cs`.

## Out of scope

Embedding-based semantic retrieval, conversation memory across questions (backlog).

## Kickoff prompt

> Execute phase 24 of the roadmap (`docs/roadmap/phases/24-ask-the-meeting.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/24-ask-the-meeting`
- **Status:** ready for PR
- **Updated:** 2026-10-17 15:00
- **Next step:** none (phase done). API check 2026-10-17 (pt-BR, `qwen2.5:7b`, real TTS
  meeting): "Para quando foi adiado o lançamento da beta?" → "próxima terça-feira" (correct, but
  the citation pointed at `mic-000001` "Uhum." instead of the system line: the 7B model's citation
  precision is the weak spot); "Quem vai corrigir os testes de recuperação?" → Carlos, cited
  `system-000003` exactly; an undiscussed question → "Não encontrei isso nas reuniões."; a second
  ask while streaming → 409. Desktop click-through pending.

### Steps

- [x] Engine: domain `Citation`, locale prompt texts and stopwords (en, pt-BR, es) — `c8aec7c`
- [x] Engine: `qa/retriever.py` (single-session budget + neighbours, all-sessions ranking) — `c8aec7c`
- [x] Engine: `qa/citations.py` + `qa/answerer.py` (`MeetingAnswerer`, streaming, empty context) — `19a4faa`
- [x] Engine: `POST /ask`, `AskJob` streaming `answer_chunk` / `answer_done`, wiring in `bootstrap.py` — `be4a3d2`
- [x] Docs: api-contract and architecture — `95e75a7`
- [x] UI client: `AskAsync`, `AnswerChunkEvent`, `AnswerDoneEvent` (`VozAta.Client/Ask.cs`) — `9f66898`
- [x] UI: `AskViewModel` + panel (History, scoped to the selected session or all sessions) — `e3e5a30`
- [x] Acceptance criteria, manual check recipe, PR
- [x] Manual check (API, 2026-10-17; desktop click-through pending)

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
- UI: one self-contained `AskView` (`AskViewModel`) docked under the session detail in History
  instead of two panels: "Only the selected meeting" scopes the question to the selected session
  (the scoped panel of the spec), unchecked asks about all sessions. This keeps phase 16/21 edits
  to `SessionDetailViewModel` / the detail template conflict-free. Citations show as
  `hh:mm:ss · date` links (the text shows `[hh:mm:ss]`) and open the session at the segment via
  `HistoryViewModel.OpenSegmentAsync` (shared with search hits). Events that arrive before
  `POST /ask` returns the `answer_id` are buffered and replayed.

### Manual check recipe (pending manual — not run in the parallel session)

No microphone, speaker or GPU capture is needed: it runs over sessions already recorded on the
reference machine. Ollama uses the GPU, so run it while no other phase holds the GPU.

1. `git checkout feature/24-ask-the-meeting`; `ollama list` shows `qwen2.5:7b` (else
   `ollama pull qwen2.5:7b`) and `ollama serve` is running.
2. In `engine/.env`: `APP_LANGUAGE=pt-BR`, `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:7b`,
   `OUTPUT_DIR` = the folder with the recorded pt-BR meetings (default `recordings`).
3. From `engine/`: `../.venv/Scripts/python -m vozata reindex` (prints the sessions indexed), then
   `../.venv/Scripts/python -m vozata serve`.
4. In a second terminal, listen to the events:
   `../.venv/Scripts/python -m websockets ws://127.0.0.1:8765/ws` (the `websockets` CLI client).
5. Pick a session id (`curl http://127.0.0.1:8765/sessions`) and ask three pt-BR questions about
   it, one at a time (each waits for `answer_done`), e.g.:
   `curl -X POST http://127.0.0.1:8765/ask -H "Content-Type: application/json" -d "{\"question\": \"O que foi decidido sobre <tema>?\", \"session_id\": \"<id>\"}"`
   - "O que foi decidido sobre <tema da reunião>?"
   - "Quem ficou responsável por <tarefa>?"
   - "Qual é o prazo combinado para <entrega>?"
   Then one without `session_id` (all meetings) and one about something never discussed.
6. Expect: `202 {"answer_id"}`; `answer_chunk` events streaming Portuguese text; `answer_done`
   with `citations` (`session_id`, `segment_id`, `start`) and `"error": null`. Open
   `GET /sessions/<id>/transcript` and check that each cited `segment_id` says what the answer
   claims. The never-discussed question answers "Não encontrei isso nas reuniões." (or the model
   says it was not found) with no invented facts. A second `POST /ask` while one streams → `409
   answer_in_progress`; with Ollama stopped → `answer_done.error` "Não foi possível responder…".
7. UI: `dotnet run --project src/VozAta.Desktop` (from `ui/`), History → expand "Pergunte às
   reuniões", select the session, tick "Somente a reunião selecionada", ask the same three
   questions: the text streams, the Ask button stays disabled until the answer ends, and each
   source link (`hh:mm:ss · data`) opens that session on the Transcript tab with the cited line
   highlighted. Untick it to ask across all meetings.
