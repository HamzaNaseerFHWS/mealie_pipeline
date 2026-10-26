# Dot-source before working in this repo so the project-local tools are used:
#   . .\scripts\env.ps1
# Puts .tools\bin (claude, ffmpeg) on PATH for this terminal only and points NLTK at .tools\nltk_data.
$root = Split-Path -Parent $PSScriptRoot
$env:PATH = "$root\.tools\bin;$env:PATH"
$env:NLTK_DATA = "$root\.tools\nltk_data"
