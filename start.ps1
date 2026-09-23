# Start Girard on Windows: audio helper (:8766), agent (:8000), dashboard (:5173).
# Each part opens in its own window; close a window (or Ctrl+C) to stop that part.
#   powershell -ExecutionPolicy Bypass -File start.ps1
$root = $PSScriptRoot

function Start-Part($title, $dir, $command) {
    Start-Process powershell -WorkingDirectory $dir -ArgumentList @(
        "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$title'; $command")
}

Start-Part "Girard audio helper :8766" "$root\linux-audio-helper" ".\.venv\Scripts\call-audio.exe serve --port 8766"
Start-Part "Girard agent :8000" $root ".\.venv\Scripts\python.exe agent.py"
Start-Part "Girard dashboard :5173" "$root\dashboard" "npx vite dev --port 5173 --strictPort"

Write-Host "Starting... the dashboard opens in your browser in a few seconds."
Start-Sleep -Seconds 8
Start-Process "http://localhost:5173/"
