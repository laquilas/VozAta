# VozAta

Near-real-time meeting transcription (microphone + system audio) and LLM-generated meeting
minutes. Python engine (`engine/`) + Avalonia desktop UI (`ui/`) over a local HTTP/WebSocket API.

## Layout

- `engine/` — Python engine (see `engine/CLAUDE.md`).
- `ui/` — Avalonia desktop app (see `ui/CLAUDE.md`).
- `docs/roadmap/` — roadmap, architecture, API contract. **Start every session at
  `docs/roadmap/README.md`.**
- `__legacy__/` — old prototypes. Read-only reference: never edit, never import from it.
- `.venv/` — shared Python virtualenv at the repo root.

Until `engine/CLAUDE.md` and `ui/CLAUDE.md` exist (roadmap phase 00), follow the matching sections
of `docs/roadmap/standards.md`.

## Session workflow

1. **Resume first**: `git fetch`, then look for unmerged `feature/*` branches (local, remote, open
   PRs). If one exists, check it out, check `git status` for uncommitted work, read the phase
   file's **Progress** section and continue from its *Next step*.
2. Otherwise read `docs/roadmap/README.md`; pick the phase (first `todo` with all dependencies
   `done`, or the one the user names).
3. Read only that phase file and the documents in its *Read first* section.
4. Branch `feature/<NN-slug>`. The first commit sets the phase to `in progress` in the README table
   and adds the **Progress** section to the phase file (template in `docs/roadmap/README.md`).
5. Implement with TDD; one logical change per commit. Every commit also updates **Progress** (tick
   the step, set *Next step*) and is pushed, so a session cut short can be resumed.
6. Tick the phase acceptance criteria and set its status to `done` in the README table.
7. Shared contract changes (config keys, endpoints, events, data model) go into
   `docs/roadmap/architecture.md` / `docs/roadmap/api-contract.md` in the same branch.

## Global rules

- **English only** for code, comments, docs, commits, branch names, defaults and log messages.
- Diagrams in Markdown docs use **Mermaid** code blocks (` ```mermaid `), never ASCII art or images.
- User-facing text and LLM prompts are **never hard-coded**: they come from locale resources in
  `en` (default), `pt-BR` and `es`. Every new key is added to all three.
- **SOLID**: depend on ports (interfaces), not concrete classes; concrete classes are wired only in
  the composition root (`engine/src/vozata/bootstrap.py`, `ui/.../App.axaml.cs`); new
  providers are added through registries, not by editing orchestrators.
- Every new class, branch and bug fix gets unit tests; diff coverage ≥ 80 %.
- Unit tests never touch audio hardware, GPU, network or real LLMs — use fakes.
- Secrets live only in `.env` (git-ignored); never log them; mask them in API responses.
- Recording consent is the user's responsibility; the UI must make recording state obvious.
