# Plan — Phase 58: GPU support (CUDA) downloaded on the PC

Phase file: `docs/roadmap/phases/58-cuda-on-demand.md`. Branch `feature/58-cuda-on-demand`.

1. `transcription/cuda_runtime.py`: `CudaRuntime(root)` (`is_ready`, `marker`); `WHEELS`;
   `install(runtime, client, say)` — PyPI JSON → win_amd64 wheel + sha256 → stream to `.part`
   with progress → digest check → extract `nvidia/*/bin/*.dll` → `ready.json`; httpx injected
   (MockTransport in tests).
2. `cuda.register_cuda_dlls(extra_roots)` returns the folders found; `FasterWhisperTranscriber`
   passes `settings.cuda_runtime_dir`, and `auto` skips the GPU when frozen with none found.
3. `cli/cuda.py` + `__main__` + locales.
4. Spec / build.ps1 without CUDA; `packaging/gpu.iss` (Check: `{sys}\nvidia-smi.exe`).
5. Docs, suites, build, manual GPU check, copy to `F:\VozAta`.
