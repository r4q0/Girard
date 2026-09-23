@echo off
rem Double-click to open the Girard desktop app (Windows).
rem First run installs dependencies, which takes a minute.
cd /d "%~dp0.."

if not exist dashboard\package.json git submodule update --init dashboard
if not exist dashboard\node_modules (
  pushd dashboard & call npm install --no-package-lock & popd
)
if not exist desktop\node_modules (
  pushd desktop & call npm install & popd
)

cd desktop
call npm start
