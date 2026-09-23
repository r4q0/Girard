# Girard

Girard is a live sales copilot that advises you in real time during a sales call.

Built as a hackathon project.

## Why Girard?

On a sales call you want to focus on listening and responding, not on taking notes or doing research.

Girard takes that load off you. It does the research live and tells you how to respond: who the prospect is, what they need, and how you can address those needs.

## How does Girard help?

**Before the call**, Girard researches the prospective client so you start the call already knowing who you are talking to.

**During the call**, Girard listens and transcribes the conversation as it happens. When the customer raises an objection, asks a question, mentions a competitor, or shows interest, you see a short card within about a second. The card gives you two or three sentence openers that you finish in your own words. When the customer mentions a competitor, Girard looks it up in the background.

**After the call**, Girard gives you a debrief:

- How the call went
- What was strong
- What could have been done better
- What the customer needs
- Actionable next steps
- A short summary of the call transcript

## How it works

```
 Call audio
     |
 Live transcription, sentence by sentence
     |
 Decide when the customer said something worth reacting to
     |
   +-------------------+--------------------+
   |                   |                    |
 Advice cards       Running summary      Background research
 (fast, per         (every 30 to 45 s)   (prospect and
 customer line)                           competitors)
   |                   |                    |
   +-------------------+--------------------+
     |
 Screen: advice cards and research panel
     |
 Post-call debrief
```

- **Advice cards** react only to what the customer just said. Most of the time Girard stays quiet and shows nothing.
- **The running summary** keeps track of the call so far, so advice stays relevant late in a long call.
- **Background research** never slows down the advice cards. but

### Salesbook

Girard's advice comes from a salesbook. It holds context and information about your business, plus a short list of entries on objections, competitors, common questions, proof points, and buying or risk signals.

## Run the demo portal

The portal lets you type transcript lines as the customer or the rep and see the advice cards, latency and cost live.

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Windows; use .venv/bin/pip on macOS/Linux
# put NEBIUS_API_KEY=... in a .env file (it is gitignored)
.venv/Scripts/python server.py
```

Open http://localhost:8000. Click "Play demo call" to run the scripted call in `demo_call.txt`.

You can also send lines without the page:

```bash
curl -X POST localhost:8000/api/line -H "Content-Type: application/json" -d '{"speaker":"CUSTOMER","text":"What is your hourly rate?"}'
```

## Configuration

API keys live in environment variables or a local `.env` file only, never in code or the repo.

## Project structure

```
server.py                Demo portal backend: prompt, fast lane, metrics
static/index.html        Demo portal page
demo_call.txt            Scripted demo call
salesbook_koref.txt      Salesbook used by the demo
salesbook_example.txt    Smaller example salesbook
requirements.txt         Python dependencies
cache_test.py            Prompt caching and latency test
cache_test_results.csv   Raw results from the last test run
context-spec.txt         Early notes on prompt structure
```

## Status

Work in progress.
