# Phase 52 — Two-PC end-to-end check

## Goal

Check by hand, with two real PCs, the worker parts that phases 44–47 and 51 could only check on
one PC or through view-model tests: discovery and pairing across the network, a real opus-mt
translation on the worker, a diarization job on the worker cancelled when a recording takes
priority, and the Config → Worker switches and sidebar line in the running app. A script runs the
API parts so the check is repeatable after every worker change.

## Depends on

51

## Read first

- [phase 45](45-worker-speakers.md), [phase 46](46-worker-translation.md),
  [phase 47](47-worker-app.md), [phase 51](51-worker-every-task.md)
- `docs/roadmap/worker-api.md`, `docs/roadmap/api-contract.md` (`/worker/discover`,
  `/worker/pair`, `/settings/test/worker`, `/health`, `/sessions`), `docs/remote-worker.md`

## Scope

**Script `scripts/two_pc_check.py`** (developer tool, run on the client PC with the repo's
`.venv`; English console output like `build.ps1`):

| Step | What it does | Pass when |
|------|--------------|-----------|
| discover | `GET /worker/discover` on the client engine | the worker (by name or id) is listed with a LAN address, not loopback |
| pair | `POST /worker/pair {url, code}` with the code typed from the GPU PC | 200; `WORKER_URL` / `WORKER_TOKEN` saved in the client engine's scratch `.env` |
| health | `GET /health` on the worker with the token | `capabilities` has speech, translation (and speakers on the speakers edition) |
| translate | `POST /translate` a known Portuguese sentence → English | non-empty English text, not equal to the input |
| diarize + cancel | `POST /diarize` a generated two-voice WAV, then `DELETE` after it is `running` | state `cancelled` within 5 s |
| pre-emption | a client recording session (`POST /sessions`) while the queue's diarize step runs on the worker | the worker job ends `cancelled`, the meeting finishes after Stop |

It talks to a **scratch client engine** it starts on a free port with its own `OUTPUT_DIR`,
`DATABASE_PATH` and `.env` (never the user's), and prints a pass / fail table. The pure parts
(step logic, result table, WAV generation) are importable and tested with `httpx.MockTransport`.

**Checklist `docs/two-pc-check.md`**: prerequisites (both PCs on one Private network, firewall
rules from the worker app, speakers edition and `HF_TOKEN` on the GPU PC), how to run the script,
and the UI steps it cannot do: Config → Worker "Find workers" and pairing in the app, the three
"use the worker for …" switches saved and reloaded, the sidebar line "Worker: host" during a
recording and "This PC (worker off)" after the worker app is closed, the fallback notification.

**Results**: the run of 2026-10-xx is recorded in this file (what passed, what was found and fixed).

## Design notes

- Only the reference machine is available to the session that builds this phase: it runs the
  script against a worker on this PC on another port (loopback discovery is skipped by the
  worker, so the script also accepts `--worker-url` to skip discovery and pairing). The real
  two-PC run is the user's, following the checklist; its result goes into this file afterwards.
- The script must not need GPU on the client PC: the client engine uses `STT_PROVIDER=vozata_worker`.

## Acceptance criteria

- [ ] `scripts/two_pc_check.py` runs every API step against a worker and prints a pass / fail
      table; its pure parts have unit tests.
- [ ] `docs/two-pc-check.md` lists the manual UI steps with the expected result of each.
- [ ] One run recorded here (on one PC at least; two PCs when available).

## Tests

Step logic with `httpx.MockTransport` (pass, fail, timeout), WAV generation, table rendering,
scratch environment never pointing at the real `.env` / database.

## Out of scope

Automating the UI steps (UI Automation across two PCs), CI for the script.

## Kickoff prompt

> Start phase 52 (`docs/roadmap/phases/52-two-pc-check.md`) once phase 51 is merged: read its
> *Read first* files, write `plans/52-two-pc-check.md`, then implement it task by task.

## Progress

- **Branch:** `feature/52-two-pc-check`
- **Status:** in progress
- **Updated:** 2026-10-23
- **Next step:** the runtime part: `scripts/two_pc_runtime.py` (start / stop the scratch client
  engine, play a WAV) and the command line `main()` of `two_pc_check.py`.

### Steps

- [x] Implementation plan (`plans/52-two-pc-check.md`)
- [x] Script core: scratch `.env`, synthetic WAV, results table, discover / pair / health
- [x] Script: translate, diarize + cancel, pre-emption
- [ ] Script runtime: scratch engine process, playback, command line
- [ ] Checklist `docs/two-pc-check.md`
- [ ] Full suites, one recorded run, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- A diarize step that runs on the worker is pre-empted by a recording only when the client PC has
  CUDA (`gpu_gate.speakers_fallback`: its fallback would run pyannote on this GPU); the script
  expects `paused` with CUDA and `running` without it.
- The step logic has 93 % coverage (`pytest tests/scripts --cov=two_pc_check`); `scripts/` sits
  outside the engine package, so the engine coverage gate does not count it.
