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
