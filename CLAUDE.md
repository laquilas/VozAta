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

## Session workflow

1. **Resume first**: `git fetch`, then look for unmerged `feature/*` branches (local, remote, open
   PRs). If one exists, check it out, check `git status` for uncommitted work, read the phase
   file's **Progress** section and continue from its *Next step*.
2. Otherwise read `docs/roadmap/README.md`; pick the phase (first `todo` with all dependencies
   `done`, or the one the user names).
3. Read only that phase file and the documents in its *Read first* section.
4. Branch `feature/<NN-slug>`. The first commit sets the phase to in progress (`feature/<NN-slug>`)
   in the README table and adds the **Progress** section to the phase file (template in
   `docs/roadmap/README.md`). Never delete a branch whose phase is in progress: its work is not in
   `main` yet.
5. Implement with TDD; one logical change per commit. Every commit also updates **Progress** (tick
   the step, set *Next step*) and is pushed, so a session cut short can be resumed.
   Pull-request CI only lints, format-checks and compiles (`ci.yml`); run the full engine and UI
   test suites locally before opening the PR. The full suites run on `v*` tags and on demand
   (`full-ci.yml`).
6. Tick the phase acceptance criteria and set its status to `done` in the README table.
7. Shared contract changes (config keys, endpoints, events, data model) go into
   `docs/roadmap/architecture.md` / `docs/roadmap/api-contract.md` in the same branch.

## Global rules

- **English only** for code, comments, docs, commits, branch names, defaults and log messages.
- **Line endings**: LF everywhere, enforced by `.gitattributes` (`* text=auto eol=lf`; only `.sln`,
  `.bat` and `.cmd` use CRLF). It overrides the machine-level `core.autocrlf=true`; never commit CRLF.
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
