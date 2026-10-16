# Meeting Minutes

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

1. Read `docs/roadmap/README.md`; pick the phase (first `todo` with all dependencies `done`, or the
   one the user names).
2. Read only that phase file and the documents in its *Read first* section.
3. Branch `feature/<NN-slug>`; implement with TDD; one logical change per commit.
4. Tick the phase acceptance criteria and update its status in the README table.
5. Shared contract changes (config keys, endpoints, events, data model) go into
   `docs/roadmap/architecture.md` / `docs/roadmap/api-contract.md` in the same branch.

## Global rules

- **English only** for code, comments, docs, commits, branch names, defaults and log messages.
- Diagrams in Markdown docs use **Mermaid** code blocks (` ```mermaid `), never ASCII art or images.
- User-facing text and LLM prompts are **never hard-coded**: they come from locale resources in
  `en` (default), `pt-BR` and `es`. Every new key is added to all three.
- **SOLID**: depend on ports (interfaces), not concrete classes; concrete classes are wired only in
  the composition root (`engine/src/meeting_minutes/bootstrap.py`, `ui/.../App.axaml.cs`); new
  providers are added through registries, not by editing orchestrators.
- Every new class, branch and bug fix gets unit tests; diff coverage ≥ 80 %.
- Unit tests never touch audio hardware, GPU, network or real LLMs — use fakes.
- Secrets live only in `.env` (git-ignored); never log them; mask them in API responses.
- Recording consent is the user's responsibility; the UI must make recording state obvious.
