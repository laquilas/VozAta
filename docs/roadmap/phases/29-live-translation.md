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

- [x] Tests with a fake translator: queue order, same-language skip, failure handling, file and
      event output, API transcript merge.
- [x] ViewModel test: translation attached to the right line.
- [x] Manual: English TTS meeting translated to Portuguese live; record latency per segment.
      *Offline part done with the real models (en → pt median ~80–140 ms per segment, pt → en on a
      real transcript median 91 ms, max 221 ms); the live audio run is pending on the reference
      machine (recipe in Progress).*
- [x] Coverage ≥ 80 % (engine and UI).

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
- **Status:** ready for PR
- **Updated:** 2026-10-17 15:10
- **Next step:** open the PR; before merge run the live part of the manual check recipe below on
  the reference machine (audio hardware, one phase at a time).

### Steps

- [x] `Translator` port + `TranslationWorker` (own thread, queue, skip, error once) + translations file
- [x] Opus-MT (CTranslate2) provider, `TRANSLATORS` registry, `TRANSLATE_TO` / `TRANSLATION_PROVIDER`
      / `TRANSLATION_MODEL_DIR`, optional extra `translation`
- [x] Session wiring: extra sink in `session_pipeline.py`, `on_translation` observer, `translation`
      event, `translation_failed` error
- [x] API: `translate_to` in `POST /sessions`, `translation` per segment in `GET .../transcript`
- [x] UI client: `TranslationEvent`, `Segment.Translation`, `StartSessionRequest.TranslateTo`
- [x] UI: translated text under each live line, "Translate to" picker, strings en/pt-BR/es
- [x] Docs (architecture, api-contract), acceptance criteria, manual check recipe

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
- Merged with phase 15 (live speakers): the translation sink sits inside the composite, after
  `EchoFilter` → `LiveSpeakerSink`. When `speakers_relabeled` reloads the live lines, the UI keeps
  the translations from `GET /sessions/{id}/transcript`. Segments that diarization split into
  `<id>-1`, `<id>-2` have no translation there (they are looked up by `segment_id`).

### Manual check recipe (live part pending: run on the reference machine, one phase at a time)

**1. Offline, no audio (done 2026-10-17, repeatable).** From `engine/` in PowerShell:

```powershell
..\.venv\Scripts\python -m pip install -e ".[translation]"   # adds sentencepiece
$env:PYTHONPATH = "src"
..\.venv\Scripts\python -c "import json,sys,time; from vozata.translation.opus_mt import from_settings; t=from_settings(None); lines=[json.loads(l)['text'] for l in open(sys.argv[1],encoding='utf-8') if l.strip()]; [print(f'{(time.perf_counter()-s)*1000:6.0f} ms | {x} -> {y}') for x in lines for s in [time.perf_counter()] for y in [t.translate(x,sys.argv[2],sys.argv[3])]]" recordings\20261016_095109\transcript.jsonl pt en
```

The first run downloads both models (~155 MB each) into the Hugging Face cache (or set
`TRANSLATION_MODEL_DIR` to a folder holding `opus-mt-ROMANCE-en/` and `opus-mt-en-ROMANCE/`).
Expected: every line translated, all sentences kept, warm lines well under 0.5 s (measured: median
91 ms, max 221 ms; en → pt median ~80–140 ms).

**2. Live (pending, needs the speakers).**

1. Start the app; on the Start screen choose meeting language *English* and **Translate to:
   Portuguese** (or set `TRANSLATE_TO=pt` in Settings).
2. In a second PowerShell, log the latency of every translation from the WebSocket (from `engine/`):

   ```powershell
   @'
   import asyncio, json, time, websockets
   async def main():
       seen = {}
       async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:
           async for raw in ws:
               m = json.loads(raw); d = m["data"]
               if m["type"] == "segment":
                   seen[d["segment_id"]] = time.perf_counter()
               elif m["type"] == "translation":
                   ms = (time.perf_counter() - seen.get(d["segment_id"], time.perf_counter())) * 1000
                   print(f"{d['segment_id']}  {ms:5.0f} ms  {d['text']}", flush=True)
               elif m["type"] == "error":
                   print("ERROR", d)
   asyncio.run(main())
   '@ | Set-Content -Encoding utf8 $env:TEMP\vozata29_ws.py
   ..\.venv\Scripts\python $env:TEMP\vozata29_ws.py
   ```

3. Click Start, then play an English TTS meeting through the speakers:

   ```powershell
   Add-Type -AssemblyName System.Speech
   $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
   $s.SelectVoice("Microsoft Zira Desktop")
   $s.Speak("Good morning everyone, thanks for joining the weekly sync. Let's start with the budget review for the next quarter. I think we should postpone the launch until the tests pass. Can you send me the report by Friday? Great, see you next week.")
   $s.Dispose()
   ```

4. Expected: a smaller grey Portuguese line appears under each English line within ~0.5 s
   (the first one later: model load); the latency per segment is printed by the WebSocket
   script — paste it in the PR. Transcription timing is unchanged.
5. Stop. The session folder has `transcript.translated.jsonl` with one line per segment, and the
   History → transcript API (`GET /sessions/{id}/transcript`) shows `translation` per segment.
6. Failure path: uninstall the extra (`pip uninstall sentencepiece`), record again: one
   `translation_failed` notification, transcription continues.

