<#
.SYNOPSIS
  Make benchmarks/tts-meeting/audio.wav from reference.txt with a Windows voice (phase 55).

.EXAMPLE
  powershell -NoProfile -File scripts/make_tts_reference.ps1        # Windows PowerShell 5
  powershell -NoProfile -File scripts/make_tts_reference.ps1 -Voice "Microsoft Maria Desktop"

  One sentence per line of reference.txt, spoken at 16 kHz mono 16-bit with -PauseMs of silence
  between them. Windows PowerShell 5 is needed for System.Speech (PowerShell 7 lacks it).
#>
param(
    [string] $Folder = (Join-Path (Split-Path $PSScriptRoot -Parent) "benchmarks/tts-meeting"),
    [string] $Voice = "Microsoft Maria Desktop",
    [int] $PauseMs = 800
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$lines = Get-Content (Join-Path $Folder "reference.txt") -Encoding UTF8 | Where-Object { $_.Trim() }
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo 16000, ([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen), ([System.Speech.AudioFormat.AudioChannel]::Mono)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice($Voice)
$pcm = New-Object System.IO.MemoryStream
$silence = New-Object byte[] (16000 * 2 * $PauseMs / 1000)
foreach ($line in $lines) {
    $part = New-Object System.IO.MemoryStream
    $synth.SetOutputToAudioStream($part, $format)
    $synth.Speak($line)
    $synth.SetOutputToNull()
    $bytes = $part.ToArray()
    $pcm.Write($bytes, 0, $bytes.Length)
    $pcm.Write($silence, 0, $silence.Length)
}
$synth.Dispose()
$data = $pcm.ToArray()
$out = Join-Path $Folder "audio.wav"
$writer = New-Object System.IO.BinaryWriter ([System.IO.File]::Create($out))
$writer.Write([Text.Encoding]::ASCII.GetBytes("RIFF")); $writer.Write([int](36 + $data.Length))
$writer.Write([Text.Encoding]::ASCII.GetBytes("WAVEfmt ")); $writer.Write([int]16); $writer.Write([int16]1); $writer.Write([int16]1)
$writer.Write([int]16000); $writer.Write([int]32000); $writer.Write([int16]2); $writer.Write([int16]16)
$writer.Write([Text.Encoding]::ASCII.GetBytes("data")); $writer.Write([int]$data.Length); $writer.Write($data)
$writer.Close()
"{0}: {1:N1} s, {2} sentences, voice {3}" -f $out, ($data.Length / 32000), $lines.Count, $Voice
