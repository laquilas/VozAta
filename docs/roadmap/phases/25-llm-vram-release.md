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
