# Phase 29 — Live translation (optional)

## Goal

Translate each committed segment into a chosen language while the meeting runs (e.g. an English
meeting followed in Portuguese). Origin: [optimizations.md](../optimizations.md) O5.

## Depends on

06, 07

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [optimizations.md](../optimizations.md) — O5 (providers and licenses)
- [architecture.md](../architecture.md) §5 (ports), §6 (VRAM rule), §8 (session files)
- [api-contract.md](../api-contract.md) — `translation` event

## Scope

| Item | Content |
|------|---------|
| `ports.py` | `Translator` port: `translate(text, source, target) -> str` |
| `translation/` | first provider chosen at the start of the phase (record the choice): MarianMT/Opus-MT via CTranslate2 (permissive licenses) is preferred; NLLB-200 is CC-BY-NC (non-commercial); Ollama competes for VRAM |
| `translation/worker.py` | own thread and queue of committed segments; never blocks transcription; runs on CPU during recording (VRAM rule) |
| Storage | `transcript.translated.jsonl` (`segment_id`, `language`, `text`) |
| API | `translation` event `{segment_id, language, text}`; `GET /sessions/{id}/transcript` adds `translation` per segment when present |
| `config.py`, `.env.example` | `TRANSLATE_TO` (empty = off), `TRANSLATION_PROVIDER` |
| UI | translated text under each line (smaller, muted); a "Translate to" picker next to the meeting language |

## Design notes

- Skip segments already in the target language.
- A failing translator emits `error` once and disables translation for the session; transcription
  continues.

## Acceptance criteria

- [ ] Tests with a fake translator: queue order, same-language skip, failure handling, file and
      event output, API transcript merge.
- [ ] ViewModel test: translation attached to the right line.
- [ ] Manual: English TTS meeting translated to Portuguese live; record latency per segment.
- [ ] Coverage ≥ 80 % (engine and UI).

## Tests

`tests/translation/`, `tests/api/test_sessions.py`, `MainViewModelTests.cs`.

## Out of scope

Text-to-speech of the translation; translating the minutes (they are already written in
`APP_LANGUAGE`).

## Kickoff prompt

> Execute phase 29 of the roadmap (`docs/roadmap/phases/29-live-translation.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/29-live-translation`
- **Status:** in progress
- **Updated:** 2026-10-17 14:30
- **Next step:** docs — architecture (§5 port, §6 data flow, §8 `transcript.translated.jsonl`,
  §9 keys, new §14 provider choice), tick acceptance criteria, write the manual check recipe.

### Steps

- [x] `Translator` port + `TranslationWorker` (own thread, queue, skip, error once) + translations file
- [x] Opus-MT (CTranslate2) provider, `TRANSLATORS` registry, `TRANSLATE_TO` / `TRANSLATION_PROVIDER`
      / `TRANSLATION_MODEL_DIR`, optional extra `translation`
- [x] Session wiring: extra sink in `session_pipeline.py`, `on_translation` observer, `translation`
      event, `translation_failed` error
- [x] API: `translate_to` in `POST /sessions`, `translation` per segment in `GET .../transcript`
- [x] UI client: `TranslationEvent`, `Segment.Translation`, `StartSessionRequest.TranslateTo`
- [x] UI: translated text under each live line, "Translate to" picker, strings en/pt-BR/es
- [ ] Docs (architecture, api-contract), acceptance criteria, manual check recipe

### Decisions and notes

- Provider: MarianMT / Opus-MT models converted to CTranslate2 (see architecture §14).
  Two pre-converted models cover all six pairs of en/pt/es: `michaelfeil/ct2fast-opus-mt-ROMANCE-en`
  (pt/es → en) and `michaelfeil/ct2fast-opus-mt-en-ROMANCE` (en → pt/es via `>>pt_br<<` / `>>es<<`);
  pt ↔ es pivots through English. ~155 MB each, CPU int8, 2 intra-op threads.
- `ctranslate2` already ships with faster-whisper; the extra `translation` adds `sentencepiece`
  (+ `huggingface_hub`, also already present). Both are imported lazily; `require_extra()` fails
  fast with a clear reason that becomes the `translation_failed` error.
- `TRANSLATE_TO` is a choice `off | en | pt | es` (empty = off) so the settings page can switch it
  off; `TRANSLATION_MODEL_DIR` empty = Hugging Face cache download on first use.
- Quick real check on the reference machine (offline, no audio): en → pt and en → es, warm median
  ~80 ms per sentence (max ~140 ms), first call ~0.7–0.8 s including the model load.
- Marian translates only the first sentence of a multi-sentence input (found with a real pt
  transcript: "Eu te dou um ping, né? Tipo assim, …" lost everything after the "?"). The provider
  now splits each segment after `.`, `!`, `?`, `…` and translates the sentences in one batch.
  Real transcript `20261016_095109` (32 pt segments) → en: warm median 91 ms, max 221 ms per
  segment; first call 3.8 s with the model load.
