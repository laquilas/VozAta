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

- [x] Three `CLAUDE.md` files exist and match `standards.md`.
- [x] `pip install -e "engine[dev]"` succeeds in `.venv`.
- [x] `pytest`, `ruff check`, `ruff format --check` pass from `engine/`.
- [x] `python -m vozata` prints the version.
- [x] Repository initialized as approved by the user; `__legacy__/` is tracked, `.env` and
      `recordings/` are ignored (`git check-ignore` confirms). *Revised by the user: the repo
      already existed, and `__legacy__/` is kept local and ignored instead of tracked.*
- [x] CI workflow green (if a remote was created).
- [x] README status for 00 set to `done`.

## Tests

`test_smoke.py` only.

## Out of scope

Any engine logic (phase 01+), the UI solution (phase 07).

## Kickoff prompt

> Execute phase 00 of the roadmap: read `docs/roadmap/README.md` and
> `docs/roadmap/phases/00-foundation.md` and follow them. Ask me before initializing git.

## Progress

- **Branch:** `feature/00-foundation`
- **Status:** ready for PR
- **Updated:** 2026-10-15 23:40
- **Next step:** none; open the PR (`pr-ready` → `pr-open` → `pr-review`) and merge after CI on the PR is green.

### Steps

- [x] Start phase: status `in progress`, Progress section — `18d4413`
- [x] Rename package to `vozata` across docs (architecture, standards, api-contract, phases, CLAUDE.md) — `4f9dc00`
- [x] Copy `__legacy__/` prototypes locally (ignored, not published); add the remaining ignore entries — `ea76488`, `01a4fb8`
- [x] Create `.venv` junction to the existing prototype venv (local only, not committed)
- [x] Write `engine/CLAUDE.md` and `ui/CLAUDE.md` from `standards.md`; drop the bootstrap note from root `CLAUDE.md` — `54af17a`
- [x] TDD: `engine/tests/test_smoke.py`, then `pyproject.toml`, `__init__.py`, `__main__.py` — `27a69c3`
- [x] `engine/.env.example` with phase 01–05 keys — `b6ba0a4`
- [x] `.github/workflows/ci.yml` and green CI — `6c9883a`, `04c1c80` ([run](https://github.com/laquilas/VozAta/actions/runs/38835791812))
- [x] Update architecture §1 environment facts; tick acceptance criteria; set phase `done`

### Decisions and notes

- **Git bootstrap skipped**: the repository already exists with a public remote `laquilas/VozAta` on `main`; the phase uses the normal feature-branch flow.
- **Package name `vozata`** (user decision): product and repo are VozAta and `meeting-minutes` is generic. Docs renamed `meeting_minutes`/`meeting-minutes` → `vozata` and `MeetingMinutes` → `VozAta`. UI projects become `VozAta.*`.
- **`.venv`** (user decision): the repo lives in OneDrive and had no venv. `.venv` is a directory junction to `<local-venv>` (a virtualenv outside OneDrive) (Python 3.13.12 with faster-whisper 1.2.1, ctranslate2, cuBLAS/cuDNN 9, PyAudioWPatch, soxr, numpy 2) so OneDrive does not sync 2.3 GB. Recreate with `New-Item -ItemType Junction -Path .venv -Target <venv>` on a fresh clone.
- **`__legacy__/`** (user decision, revised): kept locally (copied from `<prototype-workspace>/__legacy__`) but **not published**; it stays ignored by `__*__/`. On a fresh clone, copy it from there. The acceptance criterion "`__legacy__/` is tracked" no longer applies.
- `pyproject.toml` has no `readme` field: setuptools refuses files outside the package root (`../README.md`).
- `test_running_as_module_prints_version` covers `python -m vozata` through `runpy`, so the `__main__` guard counts toward coverage (100 %).
- **CI triggers** (user decision): only `pull_request` into `main` and `push` to `main`; pushes to `feature/*` do not run CI. The first run (on `feature/**` before this change) installed and passed lint, format and tests.
- **History rewrite** (user decision): `__legacy__/` was stripped from every commit of this branch with `git filter-branch` and the branch was force-pushed, so the prototypes never reach the public history. SHAs above are post-rewrite.
