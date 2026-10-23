# Phase 50 — Voice Commands Implementation Plan

**Goal:** While recording, "VozAta, gere a ata" writes minutes so far (phase 48) and "VozAta, o que foi decidido?" answers a fixed question over the meeting so far; commands are heard from the microphone only and configured on the Config page.

**Spec:** `docs/roadmap/phases/50-voice-commands.md`.

## Rulings

- **Settings** (group `voice`): `VOICE_COMMANDS_ENABLED` (bool, default true), `WAKE_WORD` (default `VozAta`), `VOICE_COMMANDS_FILE` (path; empty = `voice_commands.json` next to `.env`, like the vocabulary).
- **Command list** (`commands/store.py`): JSON `{schema_version, commands: [{phrase, action, question}]}`; `action` `minutes` | `ask` (`question` required for `ask`); at most 30, phrases up to 80 characters. Without a file: the defaults of the `APP_LANGUAGE` locale (`[voice_commands]`: "gere a ata" → minutes; "o que foi decidido" → ask; "quais são os próximos passos" → ask). `GET /voice-commands` → `{commands, defaults}`; `PUT /voice-commands {commands}` (422 `invalid_voice_commands`).
- **Matcher** (`commands/matcher.py`): text normalized (casefold, no accents, words only); the wake word matches one word or two joined ("voz ata") with `difflib` ratio ≥ 0.8; a command phrase matches the words after it (window of its length ± 1) with ratio ≥ 0.75, best match wins. `addressed(text)`: wake word + a command.
- **Detector** (`commands/detector.py`): `VoiceCommandSink`, an extra sink of the live pipeline (after echo dedupe): mic segments only; a wake word alone waits for the next mic segment starting within 5 s; 15 s cooldown per action; `on_command(command)` returns quickly.
- **Dispatch** (`api/voice_commands.py`): event `voice_command {action, phrase, question, answer_id}`; `minutes` → `PartialMinutesJob` (`origin` `voice`, live); `ask` → a second `AskJob` (`origin` `voice`, answer ids `voice-…`) over `MeetingSoFarAnswerer`; a busy job → `error` `voice_command_busy`.
- **MeetingSoFarAnswerer** (`qa/meeting_so_far.py`): the whole stored transcript when it fits `LLM_MAX_CHARS`, else notes per part (map) then the streamed answer over the notes; commands excluded.
- **Prompts**: `MinutesGenerator` and `ActionItemExtractor` take an optional `exclude(segment)`; bootstrap passes `matcher.addressed` when commands are on. The wake word goes first into the session vocabulary (Whisper hints).
- **UI**: client + events (`voice_command`, `origin` on answers); Config group `voice` gets a commands block (rows phrase / action / question, add, remove, restore defaults, save); recorder: a notification "Heard: …", `minutes` opens the Minutes so far panel when ready, `ask` streams into a VozAta answer panel.

## Tasks

- [ ] Task 1: matcher, command store, settings, `/voice-commands`; commit `feat(engine): voice command list and matcher`.
- [ ] Task 2: detector, session wiring, dispatch, minutes action, hints, prompt filtering; commit `feat(engine): act on voice commands while recording`.
- [ ] Task 3: `MeetingSoFarAnswerer`, voice Ask; commit `feat(engine): answer a voice question over the meeting so far`.
- [ ] Task 4: desktop (client, Config block, recorder panels), texts, tests, renders; commit `feat(ui): voice commands`.
- [ ] Task 5: docs, suites, manual check (Whisper on TTS "VozAta, gere a ata" through the real detector), PR, merge.
