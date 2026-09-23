# Girard

Girard is a live sales copilot that advises the user in real time during a sales call.

## Why Girard?

During a call with prospective client you don't want to be busy making notes and doing research, you want to focus on listening and responding.

Girard lightens that load, doing the research live, and giving advice on how to respond – information about the prospect, what they need, and how you can address those needs.

## How does Girard help?
Girard receives audio from the prospective client (not the user) and provides information on what to know and how to respond.

Additionally, Girard starts by researching the prospective client using Tavily to provide the user with useful info about the prospective client.

During the call, other competitors to your product that the prospective client mentions can also be researched by the model using Tavily.

After the call, Girard provides a debriefing summarizing how the call went, what could have been done better, what was strong, and what the customer needs with actionable points on what to do next. Also, a small summary of the call transcript.

# Project Structure
## TODO

## System overview

```
call playback audio -> [1] audio helper -> [2] agent service -> [3] dashboard (browser)
                        localhost:8766      localhost:8000/ws     localhost:5173
                        HTTP + SSE          WebSocket
```

| Part | Where it lives | Status |
| --- | --- | --- |
| [1] Audio helper: captures the other side of the call, transcribes locally (Moonshine) | Branch `feat/linux-audio-helper` (Linux, Josef). Branch `feat/macos-audio` adds macOS (ScreenCaptureKit). Folder `linux-audio-helper/`, see its README. | Works |
| [2] Agent service: trigger logic, Nebius models, Tavily research, cards, debrief | Not built yet (Bilal). Contract: [dashboard-protocol.md](dashboard-protocol.md) | To do |
| [3] Dashboard: live cards, research, transcript, cost and latency, debrief | `dashboard/` submodule, the Lovable project | Works, demo mode only until [2] exists |

The browser never talks to the audio helper directly. The helper rejects cross-origin requests, so the agent service sits in between and relays start, stop and transcripts.

## Running the dashboard

`dashboard/` is a git submodule of the Lovable project [fragmential/girard-starter-spark](https://github.com/fragmential/girard-starter-spark) (private: you need access to it and a GitHub SSH key). It syncs both ways with Lovable, so make UI changes in Lovable, not here.

```bash
# fresh clone
git clone --recurse-submodules git@github.com:r4q0/girard.git
# or, in an existing clone
git submodule update --init dashboard

cd dashboard
npm install --no-package-lock   # Lovable uses bun; this avoids a stray lockfile
npx vite dev --port 5173
```

- http://localhost:5173/call?demo=1 plays a scripted demo call. It needs no other parts.
- http://localhost:5173/ is the setup screen. It connects to the agent at `ws://localhost:8000/ws` (change it in settings or with `?agent=`).
- To pull the latest Lovable changes: `git submodule update --remote dashboard`, then commit the new submodule pointer.

### As a desktop app

`desktop/` wraps the dashboard in an Electron window. It starts the dashboard dev server itself if it is not running, and stops it on quit. Use View > Always on Top (Cmd/Ctrl+Shift+T) to keep it above the video call, for example right under the webcam.

Double-click a launcher in `launchers/`. The first run installs dependencies (about a minute).

| Platform | Launcher |
| --- | --- |
| macOS | `launchers/Girard.app` (drag it to the Dock, but keep it in `launchers/`; allow access to Documents if asked; log in `~/Library/Logs/Girard.log`) |
| Windows | `launchers/Girard.bat` |
| Linux | `launchers/Girard.sh` (run from a terminal) |

To change what `Girard.app` does, open it in Script Editor. Or run it by hand:

```bash
cd dashboard && npm install --no-package-lock && cd ..   # once
cd desktop && npm install && npm start
```

Run the dashboard locally on the demo machine, so the page and the agent are both on localhost. A hosted https page connecting to `ws://localhost` can be blocked by some browsers.

