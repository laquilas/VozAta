# Phase 00 — Foundation

## Goal

Turn the folder into a repository with the project standards, an installable (empty) engine
package, configuration template, lint/test tooling and CI.

## Depends on

Nothing.

## Read first

- [README](../README.md)
- [standards.md](../standards.md)
- [architecture.md](../architecture.md) §1 (environment), §2 (layout), §9 (config keys)

## Scope

| File | Content |
|------|---------|
| `CLAUDE.md` | copy of "Root CLAUDE.md" from `standards.md` |
| `engine/CLAUDE.md` | copy of "engine/CLAUDE.md" from `standards.md` |
| `ui/CLAUDE.md` | copy of "ui/CLAUDE.md" from `standards.md` |
| `.gitignore` | add `.env`, `recordings/`, `.coverage`, `htmlcov/`, `ui/**/bin/`, `ui/**/obj/`, `*.user`, `.ruff_cache/` (keep the existing `!__legacy__/` exception) |
| `engine/pyproject.toml` | project `vozata`, `requires-python >= 3.13`, src layout, deps below, ruff + pytest + coverage config |
| `engine/.env.example` | keys owned by phases 01–05 (architecture §9), each with a one-line comment |
| `engine/src/vozata/__init__.py` | `__version__ = "0.1.0"` |
| `engine/src/vozata/__main__.py` | prints the version (replaced in phase 05) |
| `engine/tests/test_smoke.py` | imports the package, checks `__version__` |
| `.github/workflows/ci.yml` | `engine` job on `windows-latest`: setup Python 3.13, `pip install -e "engine[dev]"`, ruff check, ruff format --check, pytest |

Dependencies:
- runtime: `numpy>=2`, `soxr`, `PyAudioWPatch; sys_platform == "win32"`, `faster-whisper>=1.2`,
  `python-dotenv`, `httpx`
- extra `cuda`: `nvidia-cublas-cu12`, `nvidia-cudnn-cu12>=9,<10` (already in `.venv`; CI does not
  install it)
- extra `dev`: `pytest`, `pytest-cov`, `ruff`

## Design notes

- **Git bootstrap — ask the user before running anything.** The folder is not a repository and the
  user's rule forbids committing to `main` directly. Propose: `git init -b main`, one initial commit
  on `main` with `docs/`, `__legacy__/`, `.gitignore` (bootstrap exception, user must approve),
  then `feature/00-foundation` for this phase's files. Ask whether to create a private GitHub
  remote (`gh repo create`) — CI only runs if a remote exists.
- Ruff: `line-length = 100`, `target-version = "py313"`, rules `E, F, I, UP, B, SIM`.
- Pytest: `testpaths = ["tests"]`; coverage `fail_under = 80` (tiny package now, enforced from
  phase 01 on).
- Install into the existing root `.venv`: `.venv/Scripts/python -m pip install -e "engine[dev]"`.
  Do not reinstall the CUDA wheels.

## Acceptance criteria

- [ ] Three `CLAUDE.md` files exist and match `standards.md`.
- [ ] `pip install -e "engine[dev]"` succeeds in `.venv`.
- [ ] `pytest`, `ruff check`, `ruff format --check` pass from `engine/`.
- [ ] `python -m vozata` prints the version.
- [ ] Repository initialized as approved by the user; `__legacy__/` is tracked, `.env` and
      `recordings/` are ignored (`git check-ignore` confirms).
- [ ] CI workflow green (if a remote was created).
- [ ] README status for 00 set to `done`.

## Tests

`test_smoke.py` only.

## Out of scope

Any engine logic (phase 01+), the UI solution (phase 07).

## Kickoff prompt

> Execute phase 00 of the roadmap: read `docs/roadmap/README.md` and
> `docs/roadmap/phases/00-foundation.md` and follow them. Ask me before initializing git.

## Progress

- **Branch:** `feature/00-foundation`
- **Status:** in progress
- **Updated:** 2026-10-15 22:10
- **Next step:** copy `__legacy__/` from the prototype workspace and extend `.gitignore` (step 2 of the plan).

### Steps

- [x] Start phase: status `in progress`, Progress section
- [x] Rename package to `vozata` across docs (architecture, standards, api-contract, phases, CLAUDE.md)
- [ ] Copy `__legacy__/` prototypes and add the `!__legacy__/` gitignore exception; add the remaining ignore entries
- [ ] Create `.venv` junction to the existing prototype venv (local only, not committed)
- [ ] Write `engine/CLAUDE.md` and `ui/CLAUDE.md` from `standards.md`; drop the bootstrap note from root `CLAUDE.md`
- [ ] TDD: `engine/tests/test_smoke.py`, then `pyproject.toml`, `__init__.py`, `__main__.py`
- [ ] `engine/.env.example` with phase 01–05 keys
- [ ] `.github/workflows/ci.yml` and green CI
- [ ] Update architecture §1 environment facts; tick acceptance criteria; set phase `done`

### Decisions and notes

- **Git bootstrap skipped**: the repository already exists with a public remote `laquilas/VozAta` on `main`; the phase uses the normal feature-branch flow.
- **Package name `vozata`** (user decision): product and repo are VozAta and `meeting-minutes` is generic. Docs renamed `meeting_minutes`/`meeting-minutes` → `vozata` and `MeetingMinutes` → `VozAta`. UI projects become `VozAta.*`.
- **`.venv`** (user decision): the repo lives in OneDrive and had no venv. `.venv` is a directory junction to `<local-venv>` (a virtualenv outside OneDrive) (Python 3.13.12 with faster-whisper 1.2.1, ctranslate2, cuBLAS/cuDNN 9, PyAudioWPatch, soxr, numpy 2) so OneDrive does not sync 2.3 GB. Recreate with `New-Item -ItemType Junction -Path .venv -Target <venv>` on a fresh clone.
- **`__legacy__/`** (user decision): copied from `<prototype-workspace>/__legacy__` (4 files, no recordings, no secrets) and tracked in the public repo.
