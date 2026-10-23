# Plan — Phase 57: a separate VozAta Worker installer; version 0.2.1

Phase file: `docs/roadmap/phases/57-worker-installer.md`. Branch `feature/57-worker-installer`.

1. `packaging/speakers.iss` (task, `[Run]`, `[Code]` uninstall of the runtime unless the other
   AppId is installed); `installer.iss` includes it and drops the worker (+ `[InstallDelete]` of
   the 0.1.0 worker files); `installer-worker.iss` (new AppId `{2BA26749-…}`).
2. `build.ps1`: `ui/` and `worker-ui/`, cleaned, `-p:Version`; both `iscc` runs.
3. `install-test.ps1 -Worker`; `release.yml` runs both tests.
4. `__version__` 0.2.1 and the tests that pin it.
5. Docs; build; worker install test; copy both to `F:\VozAta`.
