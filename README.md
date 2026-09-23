# Girard

Girard is a live sales copilot that advises you in real time during a sales call.

Built as a hackathon project.

## Why Girard?

On a sales call you want to focus on listening and responding, not on taking notes or doing research.

Girard takes that load off you. It does the research live and tells you how to respond: who the prospect is, what they need, and how you can address those needs.

## How does Girard help?

**Before the call**, Girard researches the prospective client so you start the call already knowing who you are talking to.

**During the call**, Girard listens to the prospect and transcribes what they say as it happens. Your own microphone is never captured. When the prospect raises an objection, asks a question, mentions a competitor, or shows interest, you see a short card, usually within a second of them finishing the sentence. The card gives you two or three sentence openers that you finish in your own words. When the prospect mentions a competitor, Girard looks it up in the background.

**After the call**, Girard gives you a debrief:

- How the call went
- What was strong
- What could have been done better
- What the customer needs
- Actionable next steps
- A short summary of the call transcript
- A draft follow-up email

## How it works

Girard is three programs that run on your computer:

```
 call audio (what the prospect says)
      |
 [1] Audio helper          captures the call's playback audio and transcribes it
     localhost:8766        on your CPU. Streams text as the prospect speaks.
      |  HTTP + live events
 [2] Agent                 decides when to react, picks the card from the salesbook,
     localhost:8000        runs research, the call summary and the debrief.
      |  one WebSocket
 [3] Dashboard             the screen you look at during the call
     localhost:5173
```

- **Advice cards** react only to what the prospect just said. Most of the time Girard stays quiet and shows nothing.
- **Starting early.** The agent starts working on a card while the prospect is still finishing their sentence. If they keep talking, the early guess is thrown away. Most cards are ready the moment the sentence ends.
- **The running summary** keeps track of the call so far, so advice stays relevant late in a long call. It also suggests questions you have not asked yet.
- **Background research** never slows down the advice cards.

### Salesbook

Girard's advice comes from a salesbook. It holds context and information about your business, plus a short list of entries on objections, competitors, common questions, proof points, and buying or risk signals. Cards only use facts from the salesbook. Girard loads [salesbook_koref.txt](salesbook_koref.txt). Any file named `salesbook_*.txt` in this folder works.

## Run it

### What you need

- Windows 10 or 11 (Linux and macOS: see below)
- Python 3.12 and Node.js 20 or newer
- A Nebius Token Factory API key (required) and a Tavily API key (optional, for research)
- Access to the dashboard repository ([fragmential/girard-starter-spark](https://github.com/fragmential/girard-starter-spark), private)

### First time

```bash
git clone https://github.com/r4q0/girard.git
```

```bash
cd girard
```

```bash
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Setup creates `.env` from `.env.example`. Open `.env` and fill in your keys:

```
NEBIUS_API_KEY=...
TAVILY_API_KEY=...
```

Setup also installs everything, downloads the English speech model (about 140 MB, runs locally), and fetches the dashboard. If your GitHub SSH key is not set up, it fetches the dashboard over HTTPS with your normal GitHub login.

### Every time

```bash
powershell -ExecutionPolicy Bypass -File start.ps1
```

This opens three windows (audio helper, agent, dashboard) and then the dashboard at http://localhost:5173 in your browser. The first page load takes a few seconds while the dashboard builds.

### Run a call

1. Start your call. Girard listens to your default playback output (your speakers or headset), so it hears the prospect. Close music and videos, and make sure that output is not muted: Windows gives muted outputs no sound to capture.
2. Press **Start call**. Cards appear at the top of the screen, close to your camera.
3. Press **End call** for the debrief.

### Linux and macOS

The audio helper was built for Linux (PipeWire or PulseAudio). See [linux-audio-helper/README.md](linux-audio-helper/README.md). With the helper set up, the agent and dashboard install the same way:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
cd dashboard && npm install --no-package-lock && cd ..
```

```bash
./start.sh
```

## Other tools

- **Dev portal**, http://localhost:8000 while the agent runs. Type prospect lines by hand and watch the card stream in, with latency per request and switches for early start, hedged requests and the time limit.
- **Card accuracy test**. [eval/testset.jsonl](eval/testset.jsonl) holds 60 prospect lines, each labelled with the right card. The last run picked the right card for 57 of 60.

  ```bash
  .venv/Scripts/python eval/run_eval.py --concurrency 1
  ```

- **Prompt caching test**. [cache_test.py](cache_test.py) measures how much faster a repeated prompt is.

## Configuration

API keys live in `.env` only, never in code or the repo. Optional settings are listed in [.env.example](.env.example).

| Setting | Default |
|---|---|
| Card model (fast) | `Qwen/Qwen3-30B-A3B-Instruct-2507` |
| Summary and debrief model (slow) | `Qwen/Qwen3-235B-A22B-Instruct-2507` |
| Audio helper address | `http://127.0.0.1:8766` |

## Project structure

```
agent.py                 Agent: WebSocket for the dashboard, audio helper link, research,
                         call summary, debrief, metrics
server.py                Fast lane: prompt, card requests, early start, hedging, cache warm-up;
                         also the dev portal
static/index.html        Dev portal page
dashboard/               Dashboard (git submodule of the Lovable project)
dashboard-protocol.md    Messages between the agent and the dashboard
linux-audio-helper/      Audio helper: call audio capture and local speech-to-text
                         (Linux, and Windows via speaker loopback)
salesbook_koref.txt      Salesbook Girard loads
salesbook_example.txt    Smaller example salesbook
eval/                    Card accuracy test set, runner and results
setup.ps1, start.ps1     Windows setup and start
start.sh                 Linux and macOS start
cache_test.py            Prompt caching and latency test
CLAUDEcontext.md         Full project context and design decisions
```

## Status

Hackathon project. Runs end to end on Windows. Live capture needs an unmuted playback output.
