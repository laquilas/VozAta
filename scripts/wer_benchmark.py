"""WER benchmark of the VozAta transcription (phase 55, `docs/benchmark.md`).

    .venv/Scripts/python scripts/wer_benchmark.py --grid CHUNK_MODE=vad,fixed CHUNK_SECONDS=4,6,8

Each folder of `benchmarks/` with a `reference.txt` (the exact words said) and an `audio.wav`
(16 kHz mono 16-bit) is transcribed by the engine's offline transcription once per configuration
of the grid; the word error rate (substitutions, insertions, deletions) and the real-time factor
are printed as a Markdown table and saved to `benchmarks/results/`. A developer tool: English
console output, like `packaging/build.ps1`.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_WORD = re.compile(r"\w+(?:[-'’:.,]\w+)*")


@dataclass(frozen=True)
class Counts:
    substitutions: int
    insertions: int
    deletions: int
    words: int  # in the reference


@dataclass(frozen=True)
class Row:
    benchmark: str
    overrides: dict[str, str]
    counts: Counts
    seconds: float  # processing time
    audio_seconds: float


@dataclass(frozen=True)
class Benchmark:
    name: str
    audio: Path
    reference: list[str] = field(default_factory=list)


def normalize(text: str) -> list[str]:
    """Lower-case words; punctuation and symbols out, accents, hyphens, apostrophes and the
    separators inside numbers (10:30, 2,5, 3.000) kept."""
    return _WORD.findall(text.lower())


def align(reference: list[str], hypothesis: list[str]) -> Counts:
    """Word-level Levenshtein alignment: the fewest substitutions + insertions + deletions."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    cost = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        cost[i][0] = i
    for j in range(cols):
        cost[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            same = reference[i - 1] == hypothesis[j - 1]
            cost[i][j] = min(
                cost[i - 1][j - 1] + (0 if same else 1),
                cost[i - 1][j] + 1,  # deletion
                cost[i][j - 1] + 1,  # insertion
            )
    substitutions = insertions = deletions = 0
    i, j = len(reference), len(hypothesis)
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            same = reference[i - 1] == hypothesis[j - 1]
            if cost[i][j] == cost[i - 1][j - 1] + (0 if same else 1):
                substitutions += 0 if same else 1
                i, j = i - 1, j - 1
                continue
        if i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return Counts(substitutions, insertions, deletions, len(reference))


def wer(counts: Counts) -> float:
    errors = counts.substitutions + counts.insertions + counts.deletions
    if counts.words == 0:
        return 1.0 if errors else 0.0
    return errors / counts.words


def parse_grid(items: list[str]) -> list[dict[str, str]]:
    """`["CHUNK_MODE=vad,fixed", "CHUNK_SECONDS=4,6"]` → every combination, in order."""
    axes: list[tuple[str, list[str]]] = []
    for item in items:
        key, _, values = item.partition("=")
        options = [value.strip() for value in values.split(",")]
        if not key.strip() or not values.strip() or not all(options):
            raise ValueError(f"grid items are KEY=value[,value...], got {item!r}")
        axes.append((key.strip(), options))
    return [
        dict(zip([key for key, _ in axes], combination, strict=True))
        for combination in itertools.product(*[options for _, options in axes])
    ]


def render(rows: list[Row]) -> str:
    """A Markdown table, best WER first (then the fastest)."""
    lines = [
        "| Benchmark | Configuration | WER | S | I | D | RTF |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda row: (wer(row.counts), row.seconds / row.audio_seconds)):
        config = " ".join(f"{key}={value}" for key, value in row.overrides.items())
        c = row.counts
        lines.append(
            f"| {row.benchmark} | {config or '(settings defaults)'} | {wer(c) * 100:.1f} % "
            f"| {c.substitutions} | {c.insertions} | {c.deletions} "
            f"| {row.seconds / row.audio_seconds:.2f} |"
        )
    return "\n".join(lines)


def find_benchmarks(root: Path, only: list[str] | None = None) -> list[Benchmark]:
    found = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        reference, audio = folder / "reference.txt", folder / "audio.wav"
        if not (reference.exists() and audio.exists()) or (only and folder.name not in only):
            continue
        found.append(
            Benchmark(folder.name, audio, normalize(reference.read_text(encoding="utf-8")))
        )
    return found


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - runs Whisper
    import argparse
    import time

    import wer_runtime

    parser = argparse.ArgumentParser(description="WER benchmark of the VozAta transcription.")
    parser.add_argument("--grid", nargs="*", default=[], help="KEY=value[,value...] per setting")
    parser.add_argument("--benchmarks", nargs="*", help="only these benchmark folders")
    parser.add_argument("--root", type=Path, default=ROOT / "benchmarks")
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    args = parser.parse_args(argv)
    benchmarks = find_benchmarks(args.root, args.benchmarks)
    if not benchmarks:
        parser.error(f"no benchmark with reference.txt and audio.wav in {args.root}")
    rows = []
    for benchmark in benchmarks:
        for overrides in parse_grid(args.grid):
            text, seconds, audio_seconds = wer_runtime.transcribe(benchmark.audio, overrides)
            counts = align(benchmark.reference, normalize(text))
            rows.append(Row(benchmark.name, overrides, counts, seconds, audio_seconds))
            print(f"{benchmark.name} {overrides or '(defaults)'}: WER {wer(counts) * 100:.1f} %")
    table = render(rows)
    print(table)
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / f"{time.strftime('%Y%m%d-%H%M%S')}.md"
    report.write_text(table + "\n", encoding="utf-8")
    print(f"Saved to {report}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
