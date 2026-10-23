# Transcription benchmark (WER)

`scripts/wer_benchmark.py` measures how well and how fast VozAta transcribes, so the chunking and
the Whisper model can be tuned on numbers. It runs the engine's own offline transcription (the
one that finishes a meeting after Stop: the same chunkers, stitching and context prompt as live)
on reference recordings and compares the result with what was really said.

## Benchmarks

Each folder of `benchmarks/` is one benchmark:

| File | Content | In git |
|------|---------|--------|
| `reference.txt` | the exact words said, one sentence per line | yes |
| `audio.wav` | the recording, 16 kHz mono 16-bit | no (`*.wav` is ignored) |

The first one, `benchmarks/tts-meeting/`, is a short Portuguese planning meeting. Make its audio
on Windows with a built-in voice:

```powershell
powershell -NoProfile -File scripts/make_tts_reference.ps1   # Windows PowerShell 5 (System.Speech)
```

Synthetic speech is very clean, so it mostly shows speed and chunking accidents. For decisions
about real meetings, add folders with real recordings and their hand-checked transcripts (the
mic track of a meeting exported from VozAta, converted to 16 kHz mono).

## Running it

From the repository root, with the repository's `.venv`:

```powershell
$env:HF_HUB_OFFLINE = "1"             # use the models already downloaded
$env:TRANSCRIPTION_LANGUAGE = "pt"    # the language of the benchmarks
.venv\Scripts\python scripts\wer_benchmark.py --grid CHUNK_MODE=vad,fixed CHUNK_SECONDS=4,6,8
```

`--grid` takes `KEY=value[,value…]` per setting (any key of `engine/.env.example`) and runs every
combination; without it the current settings run once. `--benchmarks tts-meeting` limits the
folders. The settings come from the shell environment plus the grid, never from a `.env` file;
echo dedupe is off (there is no system track).

The table, best first, is printed and saved to `benchmarks/results/<date-time>.md`:

| Column | Meaning |
|--------|---------|
| WER | word error rate: (S + I + D) / words of the reference |
| S, I, D | substituted, inserted and deleted words |
| RTF | real-time factor: processing time / audio length (below 1 keeps up with a live meeting) |

Words are compared in lower case without punctuation; accents, hyphens and the separators inside
numbers (10:30, 2,5) are kept, so "sexta feira" against "sexta-feira" counts as an error.
