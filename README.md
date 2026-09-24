# Girard

A live sales copilot. During a call Girard hears only the prospect (whatever your computer plays), transcribes it on your laptop and shows one short piece of advice tailored to what they just said. It looks up companies they mention, shows the prospect's mood from their face and words, and when the call ends it saves a debrief as a Word file.

## Run

1. Put your keys in `.env` (see `.env.example`).
2. Double-click `Girard.bat`.

The first run installs everything and downloads the models (about 850 MB). Needs [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/).

## Using it

- **Menu:** pick the output your call plays through and check the company you sell for (**Edit** to change it, or drop in PDFs about your business and Girard fills it in).
- **Call:** the latest advice in the middle, earlier advice on the left (arrow keys step through it), the prospect's words below, company research along the bottom, and the prospect's mood as a pop-up top right. The header shows the timer, audio level, running AI cost and speed.
- **End:** name the call, **Save file** (Word: debrief, stats, advice and transcript), **Back to menu**. Nothing about a call is kept unless you save it.

## How it works

| Part | What | Where |
| --- | --- | --- |
| Audio | Loopback capture of one output device (never the mic), silero voice detection that cuts at each pause or at 5 s, Parakeet 0.6B speech-to-text on the CPU, and a plain-code line filter | `audio/` (Python, sherpa-onnx) |
| Mood | Screenshots of the whole screen 3 times a second; YuNet finds the largest face and HSEmotion reads it; a local RoBERTa model reads the prospect's words. Blended into one mood. Below-normal priority, one thread per model | `emotion/` (Python, onnxruntime, OpenCV) |
| App | Electron shell that starts both engines; advice, call memory, research and debrief with GLM-5.2 on Nebius Token Factory; Tavily research with a local JSON store; Word export | `app/src/main/` (TypeScript) |
| Screen | Menu, company context, live call, end screen | `app/src/renderer/` (React, Tailwind) |
| Benchmarks | Model bake-off, speech-to-text benchmark, advice style examples, filter check | `bench/` |

The filter drops backchannel ("yeah", "mm-hmm"), strips filler words, collapses stutters, holds fragments under 3 words, lets lines with a signal (question, no/not, numbers, company names) through at once, and fixes misheard company names ("Zap here" becomes Zapier). It takes about 0.35 ms per line.

Every AI answer passes through one cleaner before it is shown or saved, which removes em dashes (`app/src/shared/text.ts`).

Mood from a face or voice counts as emotion recognition under the EU AI Act: since 2 August 2026 the person being analysed must be told.

## Develop

```
cd app && npm run dev                 # app with hot reload
cd audio && uv run check_filter.py    # filter on sample lines
cd audio && uv run live_check.py      # audio engine on a test call played through your speakers
```

`GIRARD_SELFTEST=<seconds>` runs one call on the default output, logs advice, research, mood, stats and the debrief, saves a Word file to the temp folder and quits.

Screen layouts can be checked in a browser with demo data: `node app/node_modules/vite/bin/vite.js --config app/vite.preview.config.ts`, then open `http://localhost:5174/?demo=call` (or `start`, `debrief`).

The previous version is tagged `legacy`.
