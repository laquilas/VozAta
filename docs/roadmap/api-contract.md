# Engine API contract

Single source of truth for the engine (Python, FastAPI) and the UI (`VozAta.Client`).
Every endpoint and event is tagged with the phase that implements it; a phase implements only its
own rows. Changing a row requires updating both sides.

## Conventions

- Base URL `http://{API_HOST}:{API_PORT}` — default `http://127.0.0.1:8765`. **Never bind to
  `0.0.0.0`.**
- JSON with `snake_case` fields (the C# client maps them with `JsonNamingPolicy.SnakeCaseLower`).
- Times in segments are seconds since session start (float); timestamps are ISO 8601 with offset.
- Errors: HTTP status + `{"error": {"code": "session_not_found", "message": "<localized>"}}`.
  Codes are stable English identifiers; `message` is localized with `APP_LANGUAGE`.
- Only one recording session can be active at a time (`409 session_already_active`).
- OpenAPI is served at `/docs` (Swagger UI) and `/redoc`, both showing the VozAta favicon, and must
  match this document.

## HTTP endpoints

| Method | Path | Phase | Request | Response |
|--------|------|-------|---------|----------|
| GET | `/health` | 06 | — | `{engine: "ok", version, gpu: {available, name, vram_total_mb}, stt: {provider, model, device}, llm: {provider, model, reachable}, storage: {backend: "sqlite"\|"files", database, warning}}`; `storage` (31): `database` is the absolute path of `vozata.db` (null for `files`), `warning` a localized message when it is in a OneDrive-synced folder, else null; `size_bytes` (38): the database plus its `-wal` / `-shm` files (null for `files`), `audio_cache_bytes` (38): everything under `OUTPUT_DIR/cache/` (0 when missing) |
| GET | `/favicon.ico` | — | — | the VozAta logo (`image/x-icon`, package data copied from `assets/web/favicon.ico`); not in the OpenAPI schema |
| GET | `/devices` | 06 | — | `{inputs: [Device], loopbacks: [Device], default_input_id, default_loopback_id}`; `Device = {id, name, sample_rate, channels}` |
| POST | `/sessions` | 06 | `{mic_device_id?, system_device_id?, language?: "en"\|"pt"\|"es"\|"auto", template?, vocabulary?: [str], translate_to?: "off"\|"en"\|"pt"\|"es", title?: str}` | `201 SessionSummary`; `title` (35): the meeting title, trimmed (whitespace runs, new lines too, become one space), at most 200 characters (`422 title_too_long`), blank = untitled, stored as `session.json.title`; `template` (20): minutes template id, stored in `session.json` (default `MINUTES_TEMPLATE`), `422 unknown_template`; `vocabulary` (19): this meeting's terms, put before the glossary in `session.json.vocabulary`; `translate_to` (29): live translation language of this session (omitted = `TRANSLATE_TO`, `off` = none) |
| POST | `/sessions/current/pause` | 06 | — | `SessionSummary` |
| POST | `/sessions/current/resume` | 06 | — | `SessionSummary` |
| POST | `/sessions/current/stop` | 06 | — | `202 SessionSummary` (finalization continues in background; watch `status` events) |
| GET | `/sessions` | 06 | `?limit=&offset=` | `{items: [SessionSummary], total}` newest first |
| GET | `/sessions` | 36 | `?from=YYYY-MM-DD&to=YYYY-MM-DD` (local dates, both included; both required) | `{days: [{date, total_seconds, items: [SessionSummary]}], total_seconds, has_earlier, storage}`: the meetings that started in those local days, grouped by local start day (a meeting crossing midnight stays on its start day), days and items newest first; empty days are left out; totals add `duration_seconds` (the live one for the session being recorded); `has_earlier` = a session started before `from` exists (the UI stops loading older weeks); `storage` = `sqlite` \| `files` (what `DELETE` does). `422 invalid_date_range` when one date is missing or `from` > `to`. Without `from` / `to` the paged form above answers |
| GET | `/sessions/{id}` | 06 | — | `SessionDetail` |
| DELETE | `/sessions/{id}` | 36 | — | `204`; deletes the meeting: its metadata, transcripts, speakers, translations, minutes, action items and audio, and its search hits. SQLite backend: permanent. File backend: the session folder goes to the Recycle Bin (`send2trash`), never deleted permanently. `409 session_still_active` while it is being recorded, paused, finalized or recovered; `404 session_not_found`; `500 session_delete_failed` when the folder cannot be moved (e.g. a file is open), nothing is deleted then |
| PATCH | `/sessions/{id}` | 35 | `{title: str \| null}` (no other keys) | `SessionSummary`; renames the meeting, also while it is recording, paused or finalizing (the live session updates its own `session.json`); `null` or blank clears the title; same trimming and `422 title_too_long` as `POST /sessions`; `404 session_not_found`, `409 session_being_recovered` |
| GET | `/sessions/{id}/transcript` | 06 | — | `{source: "raw"\|"diarized"\|"edited", segments: [Segment]}` (precedence rule in architecture §8); each `Segment` has `translation` (29) from `transcript.translated.jsonl`, `null` when the segment was not translated |
| GET | `/sessions/{id}/minutes` | 06 | — | `{markdown}` or `404 minutes_not_found` |
| POST | `/sessions/{id}/minutes` | 06 | `{template?}` | `202`; result via `minutes_ready`. `template` (20): omitted = the one in `session.json`, else `MINUTES_TEMPLATE`; the template used is saved to `session.json`; `422 unknown_template` |
| GET | `/sessions/{id}/export` | 11 | `?format=md\|docx\|pdf` (default `md`) | file download, `Content-Disposition: attachment; filename="<id>-minutes.<ext>"`; `400 unsupported_format`, `404 session_not_found` |
| GET | `/settings` | 06 | — | `{values: {KEY: value}, schema: [{key, type, default, choices?, secret, group, applies, options_source}]}` (secrets masked; `group` = settings page section, `applies` = `next_session` \| `restart`, phase 10; `options_source` (38) = the `GET /settings/options` list offered for the key, else null) |
| GET | `/settings/options` | 38 | — | `{options: {source: [{value, label, available}]}, reachable: {source: bool}}`; sources: `stt_providers`, `llm_providers`, `diarization_providers`, `translation_providers` (registry keys), `whisper_models` (known faster-whisper names, `available` = in the Hugging Face cache, plus other cached Whisper repositories), `ollama_models` (`/api/tags` of `OLLAMA_URL`, 2 s timeout), `compute_types`, `devices` (`cuda` unavailable without a GPU). An unreachable Ollama gives `[]` and `reachable.ollama_models: false`, never an error |
| POST | `/settings/test/{target}` | 38 | — (`target`: `ollama` \| `stt_api` \| `hf_token` \| `azure_devops` \| `github`) | `{ok, message}`; checks the service with the **saved** settings (one read-only request each: Ollama `/api/tags` and the model, `{OPENAI_STT_URL}/models`, HEAD on the gated pyannote models — 403 = terms not accepted, the Azure DevOps project, the GitHub repository); `message` is localized and never contains a secret; unknown target = `422 invalid_request` |
| DELETE | `/storage/cache` | 38 | — | `{freed_bytes}`: deletes everything under `OUTPUT_DIR/cache/` (the folder stays; files in use are skipped) |
| PUT | `/settings` | 10 | `{values: {KEY: value}}` (`null` clears a key; the secret mask `********` means unchanged) | `{values, restart_required: [KEY]}` — validated by `config.py`, persisted to `.env` key by key (comments kept); `422 invalid_setting` with `error.key` |
| POST | `/sessions/{id}/recover` | 17 | — | `202`; finalizes an `interrupted` session in the background: repairs both WAVs, pads them to one length, then runs the stop steps from the mix on (architecture §6). Progress: `status` events (`finalizing` → `done`) with that `session_id`; a failed repair sends `error` `recovery_failed` and the session stays `interrupted` (`recovery_error` in `session.json`). `409 session_not_interrupted`, `409 session_already_active` (a recording or another recovery is running; while a recovery runs `POST /sessions` also answers it), `404 session_not_found` |
| GET | `/sessions/{id}/speakers` | 16 | — | `{speakers: {"<speaker_id>": {name, default_label}}}` — every speaker of the transcript (`mic`, `system`, `system:<n>`) in order of first appearance; `name` is `null` when unset, `default_label` is the label without the name |
| PUT | `/sessions/{id}/speakers` | 16 | `{speakers: {"system:1": {"name": "Alice"}}}` (name trimmed, max 200 chars; empty or `null` = back to the default label; ids left out are unchanged) | `{speakers}` as in `GET`; writes only `speakers.json`; `422 unknown_speaker` when an id is not in the transcript (nothing saved) |
| PUT | `/sessions/{id}/transcript` | 21 | `{segments: [{segment_id, text}]}` (a full `Segment` is accepted; only `segment_id` and `text` are read; send only the changed segments) | `{source: "edited"}`: applies the texts to the current best transcript and writes the full copy to `transcript.edited.jsonl` (atomic); a segment whose text changed gets `edited: true` and `words: []`; the search index (22) is refreshed. `422 unknown_segment` (id not in the current best transcript), `422 empty_segment_text`, `409 transcript_still_recording`, `404 session_not_found` |
| DELETE | `/sessions/{id}/transcript/edits` | 21 | — | `204` removes `transcript.edited.jsonl` (also when there was none) and reverts to the diarized or raw source; reindexes search; `409 transcript_still_recording`, `404 session_not_found` |
| GET | `/templates` | 20 | — | `[{id, name}]` in display order, `name` in `APP_LANGUAGE` (ids: `general`, `daily`, `one_on_one`, `client`, `retrospective`) |
| GET | `/vocabulary` | 19 | — | `{terms: [str]}` from `VOCABULARY_FILE` (missing file = `[]`); `503 vocabulary_failed` when unreadable |
| PUT | `/vocabulary` | 19 | `{terms: [str]}` | `{terms}` as saved: trimmed, blanks, `#` lines and case-insensitive duplicates dropped; comment lines at the top of the file are kept; `503 vocabulary_failed` when it cannot be written |
| GET | `/search` | 22 | `?q=&limit=` (limit 1–200, default 50) | `{hits: [{session_id, segment_id, start, speaker_id, label, snippet}]}` best match first; `snippet` wraps each match in `\u0002` … `\u0003`; a query without words returns no hits |
| POST | `/sessions/{id}/action-items` | 23 | — | `202`; extract again in the background (items already exported are kept); result via `action_items_ready`, failure via `error` (`action_items_failed`, `empty_transcript`); `404 session_not_found`, `409 action_items_still_recording`, `503 action_items_unavailable` |
| GET | `/sessions/{id}/action-items` | 23 | — | `{items: [ActionItem], targets: [str]}`; `targets` = the configured export targets (`azure_devops`, `github`), empty when none |
| PUT | `/sessions/{id}/action-items` | 23 | `{items: [{id, description, owner?, due?}]}` (other keys ignored) | `{items, targets}` as saved: trimmed, blank owner/due = null; exported items are left unchanged; `422 unknown_action_item`, `422 empty_action_item` |
| POST | `/sessions/{id}/action-items/export` | 23 | `{target: "azure_devops"\|"github", item_ids: [str]}` (at least one) | `{created: [{item_id, url}], failed: [{item_id, error}]}`; `error` is localized; already exported or unknown items fail (never exported twice); `422 unknown_task_target` when the target is not configured |
| POST | `/ask` | 24 | `{question, session_id?}` (no id = all sessions; `question` 1–2000 chars, not blank) | `202 {answer_id}`; answer streamed via `answer_chunk` / `answer_done`; `404 session_not_found`, `409 answer_in_progress` (one question at a time), `422 invalid_request`, `503 ask_unavailable` |

### Shapes

```jsonc
// SessionSummary
{"id": "20261015_202358", "status": "recording", "started_at": "...", "ended_at": null,
 "duration_seconds": 83.4, "language": "pt", "has_minutes": false,
 "title": "Weekly sync",  // title (35): null = untitled
 "speaker_count": 2, "has_action_items": true, "template": "daily"}
// speaker_count / has_action_items / template (36): speakers found by diarization (0 before),
//   whether the session has action items, the minutes template id in session.json (null = none)
// SessionDetail = SessionSummary + full session.json fields + files: ["mic.wav", ...]
//   + folder: absolute path of the session folder (the UI opens WAVs/folder locally — engine is local)
//   files / folder: null for a backend without folders (30). With STORAGE_BACKEND=sqlite (31) they
//   are the audio folder and its WAVs (no JSON / Markdown there) until phase 32 moves the audio
//   + storage: "sqlite" | "files" (31)
// Segment (labels resolved for display; raw files store only speaker_id; `edited` from phase 21:
//   true when the user changed the text, then `words` is empty)
//   `translation` from phase 29: {language, text} in GET /sessions/{id}/transcript, null when
//   absent; never in `segment` events (the translation arrives later as a `translation` event)
{"segment_id": "system-000013", "channel": "system", "speaker_id": "system:2", "label": "User 2",
 "start": 83.12, "end": 87.9, "text": "...", "edited": false,
 "words": [{"text": "...", "start": 83.12, "end": 83.3, "probability": 0.98}],
 "translation": {"language": "pt", "text": "..."}}
// ActionItem
{"id": "a1", "description": "...", "owner": "Alice", "due": "2026-10-20", "source_segment_ids": ["mic-000042"], "exported_url": null}
// owner / due may be null; due is YYYY-MM-DD when the model could tell, else free text
```

## WebSocket `/ws`

One connection per UI. Server → client messages only (commands go through HTTP). Envelope:

```json
{"type": "segment", "session_id": "20261015_202358", "data": { }}
```

| Type | Phase | `data` | When |
|------|-------|--------|------|
| `status` | 06 | `{status, duration_seconds}` | on every status change and every 1 s while recording |
| `level` | 06 | `{channel, rms_db}` | ~10 Hz per channel while recording (UI meters, 08) |
| `segment` | 06 | `Segment` | each committed transcript segment |
| `language_detected` | 06 | `{language}` | once, when `auto` locks the language |
| `minutes_ready` | 06 | `{session_id}` | minutes written |
| `error` | 06 | `{code, message}` | non-fatal engine errors (e.g. LLM unreachable; `diarization_failed` (14) when speaker identification fails at stop; `live_diarization_failed` (15) when the live speaker embedder cannot load: recording goes on and system lines keep `system`; `translation_failed` (29) once when live translation stops, transcription continues; `recovery_failed` (17) when an interrupted session's files cannot be repaired) |
| `speakers_relabeled` | 15 | `{session_id}` | sent during finalization (stop step 5, before `minutes_ready`) once post-session speaker identification wrote `transcript.diarized.jsonl`; its speakers replace the live `system:<n>` labels of the `segment` events, so the UI reloads the session transcript |
| `recovery_available` | 17 | `{session_ids: [str]}` (newest first; envelope `session_id` null) | on connect, right after the first `status`, when interrupted sessions exist (sessions still `recording` / `paused` / `finalizing` that this engine is not running are marked `interrupted` first) |
| `action_items_ready` | 23 | `{session_id, count}` | extraction finished (at stop or after `POST .../action-items`); `count` = items stored, exported ones included |
| `answer_chunk` | 24 | `{answer_id, text}` | streamed answer token(s), in order; envelope `session_id` = the question's scope (null = all sessions) |
| `model_loading` | 26 | `{loading}` | the speech model started / finished loading while the session already records |
| `partial` | 28 | `{channel, speaker_id, label, start, text}` | interim text of a channel; replaced by the next `segment`, empty `text` clears it |
| `translation` | 29 | `{segment_id, language, text}` | translation of a committed segment, after its `segment` event (CPU worker, usually < 0.2 s later); segments already in the target language get none |
| `answer_done` | 24 | `{answer_id, citations: [{session_id, segment_id, start}], error}` | answer complete; `error` is null, or a localized message when the LLM failed (then `citations` is empty). Citations appear in the text as `[session_id@hh:mm:ss]` |

On connect the server sends one `status` message describing the current session (or
`{"status": "idle"}`).
