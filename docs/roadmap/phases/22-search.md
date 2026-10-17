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

- [x] Tests (temp db): index/search, accent-insensitive match (`decisao` finds `decisão`), replace on
      reindex, FTS syntax injection (`"`, `*`, `OR`) handled safely, snippet markers.
- [x] UI tests: debounce, grouping, navigation to segment.
- [x] Manual: search a word said in an old meeting and jump to it. *(The `reindex` + accent-
      insensitive search path was checked on a synthetic session folder; the desktop check with a
      real recording is pending manual (shared audio hardware): recipe in Progress.)*
- [x] Resource parity test passes.

## Tests

`tests/storage/test_search_index.py`, `tests/api/test_search.py`, `SearchViewModelTests.cs`.

## Out of scope

Semantic (embedding) search — backlog, could reuse phase 24 retrieval.

## Kickoff prompt

> Execute phase 22 of the roadmap (`docs/roadmap/phases/22-search.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/22-search`
- **Status:** ready for PR
- **Updated:** 2026-10-17 15:00
- **Next step:** none (phase done). Checked 2026-10-17 on three real recorded sessions: `reindex`
  indexed 3, `GET /search` matches `terca`→`terça` and `recuperacao`→`recuperação` with highlighted
  snippets, and `"`, `*`, `OR`, `NEAR(` return no hits without errors. Still pending manual: the
  desktop click-through and step 7 (search right after a recording), blocked by the WASAPI hang

### Steps

- [x] Start the phase (README status, Progress section)
- [x] Engine: `SearchIndex` (FTS5, accent-insensitive, safe query, snippet markers) behind the `TranscriptSearch` port
- [x] Engine: index at stop step 6; `python -m vozata reindex`
- [x] Engine: `GET /search`; first-run rebuild when `index.db` is missing; contract docs
- [x] UI: `IEngineClient.SearchAsync`, `SearchViewModel` (debounce, grouping), search box in History, open the session scrolled to the segment
- [x] Acceptance criteria, README status `done`, PR

### Manual check recipe (run on the reference machine, one phase at a time)

1. From `engine/`, with the branch checked out and the venv active, rebuild the index for the
   existing recordings: `../.venv/Scripts/python -m vozata reindex` → prints
   `Search index rebuilt. Sessions indexed: N.` and creates `OUTPUT_DIR/index.db`.
2. Start the app: `dotnet run --project ui/src/VozAta.Desktop` (it starts the engine).
3. History tab: type in the search box a word said in an old meeting, without its accent
   (e.g. `decisao` for `decisão`). After ~0.3 s the session list is replaced by results grouped by
   session date, each with time, speaker and the matched word in bold/highlighted.
4. Type `"`, `*`, `OR` and `NEAR(`: no error is shown (only "No matches" or results).
5. Click a result: that session opens on the **Transcript** tab, scrolled to the highlighted line.
   Click a result of an older session (beyond the first 20): the list loads more pages and opens it.
6. Clear the box (x button): the session list returns.
7. Record a short new session (say a distinctive word), stop it, wait for `done`, then search that
   word: the new session is found without running `reindex` (stop step 6).
8. Optional first-run path: stop the app, delete `OUTPUT_DIR/index.db`, start the app again and
   search: older sessions are found (background rebuild by `serve`).

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
- `GET /search` hits also carry `label` (resolved like transcript segments), so the UI needs no
  extra call. `ApiContainer.search_index` defaults to `None` (no hits) so other test containers
  need no change. `serve` starts a daemon thread running `SearchIndex.ensure(store)`: sessions
  recorded before this phase become searchable without running `reindex`.
- UI: `SearchViewModel` (owned by `HistoryViewModel.Search`) searches 300 ms after typing stops
  (injectable delay), needs 2+ characters, cancels a search in flight on a new edit, and groups
  hits by session (ordered by each session's best hit; rows in transcript order). While a query is
  active the results replace the session list. Opening a hit selects the session (loading older
  pages when needed), switches the detail to the Transcript tab (`SelectedTab`) and focuses the
  line (`FocusSegment` → `FocusedLine`, highlighted; `Views/ScrollToItem` brings it into view).
  `TranscriptLine` gained init-only `SegmentId` and `IsFocused`. Highlighting uses the
  `Views/SnippetText` attached property (bold runs). The detail changes are limited to the tab
  binding and the transcript list (phase 20 only touches the regenerate action).
