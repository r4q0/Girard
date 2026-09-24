@echo off
rem Girard: double-click to run. The first run sets everything up (a few minutes, ~700 MB download).
setlocal
cd /d "%~dp0"

if not exist ".env" (
  echo Missing .env next to this file. Add NEBIUS_API_KEY=... and TAVILY_API_KEY=... and run again.
  pause
  exit /b 1
)

where uv >nul 2>nul || (echo Needs uv: https://docs.astral.sh/uv/ & pause & exit /b 1)
where npm >nul 2>nul || (echo Needs Node.js: https://nodejs.org/ & pause & exit /b 1)

if not exist "audio\.venv" (
  echo Setting up the audio engine...
  pushd audio && uv sync --no-dev && popd || (pause & exit /b 1)
)
pushd audio && .venv\Scripts\python.exe -m girard_audio.prepare && popd || (pause & exit /b 1)

if not exist "emotion\.venv" (
  echo Setting up mood tracking...
  pushd emotion && uv sync && popd || (pause & exit /b 1)
)
pushd emotion && .venv\Scripts\python.exe -m girard_emotion.prepare && popd || (pause & exit /b 1)

if not exist "app\node_modules\electron\dist\electron.exe" (
  echo Setting up the app...
  pushd app && call npm install && popd || (pause & exit /b 1)
)

cd app
call npx electron-vite build >nul || (echo Build failed. & pause & exit /b 1)
start "" /b npx electron-vite preview
