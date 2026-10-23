# Phase 50 — Voice commands

## Goal

While recording, the user speaks to VozAta: "VozAta, gere a ata" writes minutes so far (phase 48);
"VozAta, o que foi decidido?" asks the language model about everything said until now and shows
the answer in the recorder. The commands and their phrases are set on the Config page. Only the
**microphone** is listened to: a remote participant saying "VozAta" through the speakers triggers
nothing (user decision, 2026-10-22).

## Depends on

48

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`, [phase 48](48-minutes-so-far.md),
  [phase 18](18-echo-dedupe.md), [phase 19](19-custom-vocabulary.md), [phase 29](29-live-translation.md)
- `session.py`, `session_pipeline.py`, `session_live.py` (sink chain, `extra_sinks`),
  `translation/worker.py` (model for a threaded sink), `vocabulary.py` (`build_hints`, the list
  file and `GET|PUT /vocabulary` as a model), `qa/answerer.py`, `qa/retriever.py`,
  `api/ask_job.py`, `settings_fields.py`, `config.py`, `locales/*.toml`
- UI: `ConfigPageViewModel.cs` + `ConfigPage.axaml` (vocabulary card), `VocabularyViewModel.cs`,
  `RecorderPageViewModel.cs`, `MainViewModel.cs`

## Scope

**Settings and the command list**

- `VOICE_COMMANDS_ENABLED` (bool, default on), `WAKE_WORD` (default `VozAta`),
  `VOICE_COMMANDS_FILE` (JSON list `[{phrase, action, question?}]`), `GET|PUT /voice-commands`.
- Actions: `minutes` (minutes so far, origin `voice`) and `ask` (a fixed question).
- Default list from the locale of `APP_LANGUAGE`, e.g. pt-BR: "gere a ata" → minutes; "o que foi
  decidido" → ask "O que foi decidido até agora?"; "quais são os próximos passos" → ask.
- Config page: a **Voice commands** card (like the vocabulary card): toggle, wake word, rows
  phrase + action + question, add / remove, restore defaults.

**Detection (engine)**

| File | Content |
|------|---------|
| `commands/matcher.py` (new) | normalize (casefold, no accents or punctuation); wake word possibly split ("voz ata"), `difflib` ratio ≥ 0.8; phrase after it in the same segment or the next mic segment within 5 s, ratio ≥ 0.75 |
| `commands/detector.py` (new) | `VoiceCommandSink`: a `TranscriptSink` in `extra_sinks` with its own thread; mic channel only; cooldown 15 s per action; a command while a job runs answers "busy" |
| `vocabulary.py` | the wake word first in the Whisper hints when enabled |
| `minutes/*`, `qa/*` | lines addressed to VozAta stay in the transcript but are dropped from the text sent to the minutes, action items and Ask prompts |

**Actions**

- `minutes` → the phase 48 job.
- `ask` → a question over the meeting so far: the whole transcript when it fits `LLM_MAX_CHARS`,
  otherwise notes per part (map) and one answer over the notes — not keyword hits. Streamed with
  `answer_chunk` / `answer_done` plus `origin: "voice"`.
- Event `voice_command {action, phrase}`.

**UI**: notification "Heard: …"; a recorder **VozAta** panel showing the streamed answer or the new
partial minutes.

**Docs**: `api-contract.md` (`/voice-commands`, `voice_command`, `origin`), `architecture.md` §9
keys, user guide (phrases, mic only, the delay below).

## Design notes

- Committed mic segments are used after the echo filter, so speech played by the speakers and
  picked up by the mic is dropped before detection. The echo hold delays mic segments by up to
  `CHUNK_SECONDS + 3` s: a command acts a few seconds after it is said.
- Interim text (`partial`) is not used for commands: it can change and would fire twice.
- No speech synthesis: answers are shown, not spoken.

## Acceptance criteria

- [ ] Saying "VozAta, gere a ata" into the mic while recording writes partial minutes and shows
      them; "VozAta, o que foi decidido?" shows the answer in the recorder.
- [ ] The same phrases played through the speakers do nothing.
- [ ] The command list, wake word and on/off switch are edited on the Config page.
- [ ] Command lines do not appear in the minutes.

## Tests

Matcher (variants, accents, split wake word, near misses, two-segment command), detector (system
channel ignored, cooldown, busy, only while recording with live transcription), hints, prompt
filtering, map + answer with a fake LLM, events, `/voice-commands` endpoints, Config card view
model, recorder panel, resource parity.

## Out of scope

Free-form questions after the wake word, speech synthesis, commands that control the recording
(pause, stop), commands from the system audio.

## Kickoff prompt

> Start phase 50 (`docs/roadmap/phases/50-voice-commands.md`) once phase 48 is merged: read its
> *Read first* files, write `plans/50-voice-commands.md`, then implement it task by task.

## Progress

- **Branch:** `feature/50-voice-commands`
- **Status:** in progress
- **Updated:** 2026-10-22
- **Next step:** Task 4 of `plans/50-voice-commands.md` (desktop: client and events, Config voice
  block, recorder panels, texts, renders).

### Steps

- [x] Implementation plan (`plans/50-voice-commands.md`)
- [x] Matcher, command list, settings, `/voice-commands`
- [x] Detector, session wiring, dispatch, minutes action, hints, prompt filtering
- [x] Voice question over the meeting so far
- [ ] Desktop: Config block, recorder panels
- [ ] Docs, full suites, manual check, phase done

### Decisions and notes

- Commits stay local until the PR; GitHub Actions is disabled, every check runs locally; the user
  asked to go on without stopping (2026-10-22).
- Detection runs in the sink's `emit` (string comparisons of short texts), no extra thread.
- Tasks 2 and 3 landed in one commit: the dispatcher needs the voice question job.
