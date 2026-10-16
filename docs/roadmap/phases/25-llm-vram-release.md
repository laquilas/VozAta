# Phase 25 — LLM VRAM release

## Goal

Free the GPU as soon as the minutes are written. Ollama keeps a model in VRAM for 5 minutes after
the last request by default, so a recording started in that window loads Whisper next to the LLM
on a 6 GB GPU — the situation the VRAM rule (architecture §6) forbids (risk: CUDA out of memory →
CPU fallback). Origin: [optimizations.md](../optimizations.md) O2.3.

## Depends on

04

## Read first

- `engine/CLAUDE.md`
- [optimizations.md](../optimizations.md) — O2
- [architecture.md](../architecture.md) §6 (VRAM rule), §9 (keys)

## Scope

| File | Content |
|------|---------|
| `llm/ollama.py` | send `keep_alive` with every chat request (`generate` and `stream`) |
| `config.py`, `settings_fields.py`, `.env.example` | `OLLAMA_KEEP_ALIVE` (default `0`: unload right after the reply; any Ollama duration such as `5m` keeps it) |
| `bootstrap.py` | pass the value to `OllamaLanguageModel` |

## Design notes

- Map-reduce minutes call the model several times in a row; `keep_alive: 0` reloads it for every
  part. Send `keep_alive: 0` only with the **last** request of a job (the reduce step or the single
  pass) and the configured value otherwise — `MinutesGenerator` tells the model which call is last
  (`LanguageModel.generate(..., last=True)` or a `release()` call after the job; pick the smaller
  port change and record it in architecture §5).

## Acceptance criteria

- [ ] `MockTransport` tests: request bodies carry `keep_alive`; single pass and map-reduce release
      the model only on the last call.
- [ ] Manual: after `python -m vozata minutes <dir>`, `ollama ps` lists no loaded model.
- [ ] Coverage ≥ 80 %.

## Tests

`tests/llm/test_ollama.py`, `tests/minutes/test_generator.py`, `tests/test_config.py`.

## Out of scope

Keeping Whisper warm between sessions (phase 26).

## Kickoff prompt

> Execute phase 25 of the roadmap (`docs/roadmap/phases/25-llm-vram-release.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/25-llm-vram-release`
- **Status:** in progress
- **Updated:** 2026-10-16 15:20
- **Next step:** add `release()` to the `LanguageModel` port (`ports.py`, `FakeLanguageModel`,
  architecture §5); make `OllamaLanguageModel` send `keep_alive` and implement `release()`;
  pass `settings.ollama_keep_alive` in `bootstrap.py`

### Steps

- [x] Start the phase (README status, Progress section)
- [x] `OLLAMA_KEEP_ALIVE` config key (default `0`, Ollama duration or seconds) — next commit
- [ ] `LanguageModel.release()` port method; Ollama sends `keep_alive` with every chat request and
      `release()` unloads with the configured value; wired in `bootstrap.py`
- [ ] `MinutesGenerator` calls `release()` once after every job (success or failure)
- [ ] Manual check: `ollama ps` empty after `python -m vozata minutes <dir>`; acceptance criteria

### Decisions and notes

- Port change: `LanguageModel.release()` (one new method) instead of `generate(..., last=True)`.
  Chat requests send `keep_alive: "5m"` so map-reduce does not reload the model between parts;
  `release()` posts an empty chat (`messages: []`) with `keep_alive = OLLAMA_KEEP_ALIVE`, which is
  Ollama's documented way to unload. Calling it from a `finally` frees the GPU even when a map
  step fails, which `last=True` would not.
