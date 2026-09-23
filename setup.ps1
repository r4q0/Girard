# One-time setup for Girard on Windows. Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "1/5 API keys (.env)"
if (-not (Test-Path "$root\.env")) {
    Copy-Item "$root\.env.example" "$root\.env"
    Write-Host "    Created .env from .env.example. Open it and fill in NEBIUS_API_KEY (and TAVILY_API_KEY for research)."
}

Write-Host "2/5 Agent (Python venv in .venv)"
if (-not (Test-Path "$root\.venv")) { python -m venv "$root\.venv" }
& "$root\.venv\Scripts\python.exe" -m pip install -q -r "$root\requirements.txt"

Write-Host "3/5 Audio helper (Python venv in linux-audio-helper\.venv)"
$helper = "$root\linux-audio-helper"
if (-not (Test-Path "$helper\.venv")) { python -m venv "$helper\.venv" }
& "$helper\.venv\Scripts\python.exe" -m pip install -q -e "$helper"

Write-Host "4/5 Speech model (Moonshine, English, runs on your CPU)"
& "$helper\.venv\Scripts\call-audio.exe" prepare | Out-Null

Write-Host "5/5 Dashboard (git submodule + npm)"
if (-not (Test-Path "$root\dashboard\package.json")) {
    # The submodule URL uses SSH; fall back to HTTPS with your GitHub login if SSH is not set up.
    git -C $root submodule update --init dashboard
    if (-not (Test-Path "$root\dashboard\package.json")) {
        git -C $root config --local submodule.dashboard.url https://github.com/fragmential/girard-starter-spark.git
        git -C $root submodule update --init dashboard
    }
}
Push-Location "$root\dashboard"
npm install --no-package-lock
Pop-Location

Write-Host ""
Write-Host "Done. Start everything with:  powershell -ExecutionPolicy Bypass -File start.ps1"
