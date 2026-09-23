#!/bin/bash
# Double-click to open the Girard desktop app (macOS and Linux).
# First run installs dependencies, which takes a minute.
cd "$(dirname "$0")/.." || exit 1
set -e

if [ ! -f dashboard/package.json ]; then
  git submodule update --init dashboard
fi
if [ ! -d dashboard/node_modules ]; then
  (cd dashboard && npm install --no-package-lock)
fi
if [ ! -d desktop/node_modules ]; then
  (cd desktop && npm install)
fi

cd desktop
npm start
