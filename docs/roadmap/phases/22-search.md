# Phase 22 — Cross-session search

## Goal

Full-text search across every meeting's transcript, from the history screen.

## Depends on

09

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §6 (stop step 6), §8 (`index.db`, transcript precedence)
- [api-contract.md](../api-contract.md) — `GET /search`

## Scope

**Engine**

| File | Content |
|------|---------|
| `storage/search_index.py` | `SearchIndex(db_path)`: SQLite FTS5 table `segments(session_id UNINDEXED, segment_id UNINDEXED, start UNINDEXED, speaker_id UNINDEXED, text)` with tokenizer `unicode61 remove_diacritics 2` (accent-insensitive for pt/es); `index_session(id, segments)` (replace), `search(query, limit) -> hits with snippet()`, `rebuild(store)` |
| `session.py` | index at stop step 6 (and after recovery, 17) |
| `__main__.py` | `reindex` (rebuild from all sessions using `load_transcript`) |
| API | `GET /search?q=&limit=`; user input escaped into a safe FTS query (quoted terms, prefix `*` on the last term) |

**UI**: search box in History; results grouped by session (date, snippet with highlighted match,
time); clicking opens the session detail scrolled to the segment.

## Acceptance criteria

- [ ] Tests (temp db): index/search, accent-insensitive match (`decisao` finds `decisão`), replace on
      reindex, FTS syntax injection (`"`, `*`, `OR`) handled safely, snippet markers.
- [ ] UI tests: debounce, grouping, navigation to segment.
- [ ] Manual: search a word said in an old meeting and jump to it.
- [ ] Resource parity test passes.

## Tests

`tests/storage/test_search_index.py`, `tests/api/test_search.py`, `SearchViewModelTests.cs`.

## Out of scope

Semantic (embedding) search — backlog, could reuse phase 24 retrieval.

## Kickoff prompt

> Execute phase 22 of the roadmap (`docs/roadmap/phases/22-search.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/22-search`
- **Status:** in progress
- **Updated:** 2026-10-17 12:00
- **Next step:** add `routes/search.py` (`GET /search`) with `ApiContainer.search_index`, wire it in `bootstrap.build_api_container` (rebuild in the background when `index.db` is missing) and document it in api-contract/architecture

### Steps

- [x] Start the phase (README status, Progress section)
- [x] Engine: `SearchIndex` (FTS5, accent-insensitive, safe query, snippet markers) behind the `TranscriptSearch` port
- [x] Engine: index at stop step 6; `python -m vozata reindex`
- [ ] Engine: `GET /search`; first-run rebuild when `index.db` is missing; contract docs
- [ ] UI: `IEngineClient.SearchAsync`, `SearchViewModel` (debounce, grouping), search box in History, open the session scrolled to the segment
- [ ] Acceptance criteria, README status `done`, PR

### Decisions and notes

- FTS5 is available in the stdlib `sqlite3` of the venv Python 3.13 (SQLite 3.50.4) and of the
  CI `actions/setup-python` 3.13 build (both bundle a SQLite compiled with FTS5).
- Port `ports.TranscriptSearch` (`index_session(session_id, segments)`, `search(query, limit)`);
  `storage/search_index.SearchIndex` implements it plus `rebuild(store)` and `exists()`. Phases 21
  and 24 should depend on the port. Each call opens its own SQLite connection (thread-safe).
- Snippet markers are the control characters `\u0002` (start of match) and `\u0003` (end), as
  `domain.SNIPPET_START` / `SNIPPET_END`: they never occur in transcript text, unlike brackets.
- Safe query: every `\w+` word of the user text is quoted (implicit AND) and the last one gets a
  prefix `*`; operators such as `OR` become plain words; text without words returns no hits.
- Stop step 6 indexes after the minutes, whether or not minutes are enabled
  (`RecordingSession._index_transcript`, `SessionComponents.search_index`). A failure is
  non-fatal: logged and reported as `error` code `index_failed` (hint: `python -m vozata reindex`).
  Phase 17 (recovery) should reuse the same step; there is no recovery code yet.
