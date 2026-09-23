# Girard: hackathon strategy chat export

Date: 2026-09-23 · Project: Girard (Nebius Token Factory hackathon)

---

## 1. What Girard is

Girard is a **live sales copilot** that gives a sales rep advice in real time during a sales call.

**The problem:** On a sales call you want to focus on listening and responding, not on taking notes or looking things up. When a prospect asks "what's your hourly rate?" or names a competitor, you have about a second to answer. The right answer usually sits in a sales playbook that nobody can read in the middle of a call.

**What Girard does:**

- **During the call:** Girard listens to the prospect, line by line. When the prospect raises an objection, asks a question, mentions a competitor or shows a buying signal, a card appears within about half a second. The card holds 2 or 3 short sentence openers that the rep finishes in their own words. Most of the time Girard stays quiet: small talk, fillers like "yeah" and "right", and plain facts don't trigger a card.
- **The salesbook:** All advice comes from a salesbook. It holds the company's context (services, pricing, guarantee, positioning) plus entries for objections, competitors, common questions, proof points, and buying and risk signals. Facts marked INTERNAL ONLY, such as margins and pricing rules, are never shown to the rep as something to say. The demo uses the salesbook for Koref, an Amsterdam software and automation firm.
- **Planned (in the README, not built yet):** pre-call research on the prospect, background lookups on competitors, a running call summary, and a post-call debrief covering how the call went, strengths, improvements, customer needs, next steps and a summary.

**How it's built (what exists in the code):**

- `server.py`: a FastAPI demo portal. Every prospect line goes to **Qwen3-30B-A3B-Instruct-2507 on Nebius Token Factory** as one streaming request.
  - A strict JSON schema whose `id` enum only allows salesbook entries that haven't been shown yet, so the model can't invent a card or repeat one.
  - Backchannel lines ("yeah", "ok") are filtered out before any model call.
  - A newer line cancels any request still in flight. Optional hedged (duplicate) requests, plus a hard 3-second timeout.
  - A stable system prompt, so Token Factory can reuse its prefix cache.
  - Metrics for every request: time to first token, time until the card is decided, tokens, cached tokens, cost.
- `static/index.html`: the portal. You type lines or play the scripted demo call (`demo_call.txt`) and watch cards, latency and cost update live.
- `eval/`: a labelled test set of 60 cases, a runner and the results.
- `cache_test.py`: a test that measures latency with and without prefix caching.

**Measured so far:**

| Metric | Result |
|---|---|
| Eval accuracy (60 labelled cases) | **56/60 (93%)**, up from 50/60 (83%) over prompt iterations |
| Card decided (best run) | **p50 485 ms / p95 887 ms** |
| Time to first token, prefix cache hit vs miss | **156 ms vs 260 ms p50** (p95 849 vs 1131 ms) |
| Prompt size | ~4,730 tokens, almost all cached on repeat requests |
| Price (Token Factory) | $0.10 / 1M input tokens, $0.30 / 1M output tokens |
| Cost per card | ≈ $0.0005 |
| Cost per call-hour (~600 lines reaching the model) | ≈ **$0.30**, less after backchannel filtering |

The 4 remaining eval errors:

- `sig-12` gives the wrong card: "open vacancy for a planner" triggered the manual-docs signal instead of the vacancy signal.
- `null-08`, `null-09` and `null-10` show a card where Girard should have stayed quiet (follow-up questions on topics already covered).

---

## 2. What the hackathon asks for

**What to submit:**

- A live product link (any hosted URL)
- What you built and the problem it solves (user, pain, how often it happens, what they do today, whether they'd pay, why it could become a company)
- Models and Token Factory use (which open models, the role each plays, any closed model and what for)
- Measurable model advantage (the baseline, numbers on quality, cost, latency and control, and a link to proof)
- Responsible design (1 or 2 sentences)
- Pitch slides as a public link, opened on the stage computer. Test it in incognito. 5 minutes including the live demo, and the slides must cover all six criteria.

**Judging:**

- Product and user value: 25%
- Problem and company potential: 20%
- Measurable model advantage: 20%
- Technical execution and Token Factory use: 20%
- Demo clarity: 10%
- Responsible design: 5%

---

## 3. Question: "Give me more insight and a strategy for the presentation and face-to-face explanation, to be hand-picked for the top 8"

### Scorecard: where Girard stands

| Criterion (weight) | What we have | Gap |
|---|---|---|
| Product & user value (25%) | The live advice cards work well: streaming, backchannel filter, no repeat cards, internal-only facts protected. | **No hosted URL** yet (localhost only). The README promises pre-call research, running summary, competitor lookup, debrief and live transcription, but only the card lane exists. |
| Problem & company (20%) | A real user (Koref's own sales calls) and a clear pain. | No numbers on market size or willingness to pay. |
| Model advantage (20%) | A real eval: 56/60 (93%), card decided in p50 485 ms / p95 887 ms, caching 156 vs 260 ms. | **No baseline.** Nothing has been compared against another model yet. This is the biggest and cheapest gap to close. |
| Tech & Token Factory (20%) | Strict schema with an id enum, hedging, hard timeout, a cache-friendly prompt, cost tracking. | Only one model is used. |
| Demo clarity (10%) | A scripted demo call with live latency and cost counters. | Lines are typed, not live audio. Say so up front. |
| Responsible (5%) | Only the prospect is transcribed, internal facts are guarded, the rep finishes every sentence. | Not written down anywhere yet. |

### Fix these first (most points per hour)

1. **Baseline eval (~30 min).** `eval/run_eval.py` already reads `GIRARD_MODEL`. Run it on 2 or 3 other Token Factory models (for example Llama 3.3 70B and a larger Qwen or DeepSeek) and on one closed model (GPT-4o-mini or a Claude model). Put accuracy, p50/p95 latency and cost per call-hour in one table. That table is the Model advantage answer and the proof link. Check exact model ids at `/v1/models`.
   ```bash
   GIRARD_MODEL="meta-llama/Llama-3.3-70B-Instruct" .venv/Scripts/python eval/run_eval.py
   ```
2. **Deploy (~30 min).** Railway, Render or Fly.io, with the API key as an environment variable. There's one global session, so add a reset button for judges.
3. **Make the README match the code.** Either cut the claims or build the **post-call debrief**: one call on a bigger Token Factory model over the transcript, about 40 lines. It adds a second model with a clear job (a fast MoE for cards, a large model for the debrief), which helps the Technical score.
4. **Show the eval in the demo:** the latest accuracy and the comparison table, in the portal or on a slide.

### The cost story

~4,728 prompt tokens × $0.10/M + ~50 output tokens × $0.30/M ≈ **$0.0005 per card**. At ~600 lines/hour that's ≈ **$0.30 per call-hour**. A frontier closed model at $2–3/M input would cost roughly 20–30× more. Check current list prices before putting a number on a slide.

> "Real-time copilots are usually priced for enterprise contact centres. At 30 cents an hour we can sell it to a 5-person consultancy."

### The 5-minute pitch

| Time | Slide | Say / show |
|---|---|---|
| 0:00–0:30 | Hook | "On a sales call, the prospect asks 'what's your hourly rate?' and you have one second. Most reps fumble it. The answer is in a playbook nobody reads mid-call." |
| 0:30–1:00 | User & pain | B2B service firms (consultancies, agencies, IT shops). Several calls a week; every lost deal is worth €5–50k. Today: memory, a PDF playbook, or expensive enterprise tools. "We built it for our own sales calls at Koref." |
| 1:00–2:45 | **Live demo** | Play the demo call. Stop on 3 moments: **hourly rate** (card in under a second, internal pricing never leaks), **Flowbase** (unknown competitor gets a card), **"Yeah" / "Right"** (nothing shows; Girard stays quiet by default). Point at the latency and cost counters. |
| 2:45–3:30 | Model advantage | The comparison table: "Qwen3-30B-A3B on Token Factory: 93% correct, first card in 485 ms, $0.30 per call-hour, vs [closed model]: X%, Y ms, $Z." Caching: "A stable prompt prefix cut time to first token by about 40%." |
| 3:30–4:10 | Architecture | Simplified diagram. Schema with an id enum makes invented cards impossible. Hedging plus a 3 s timeout means a late card is never shown. |
| 4:10–4:40 | Company | Price per seat per month; our cost is cents per hour. Wedge: EU B2B service SMBs with EU-hosted open models. Next: salesbook onboarding from existing sales docs, CRM sync. |
| 4:40–5:00 | Responsible + close | "Only the prospect is transcribed, nothing is stored after the call, internal facts are fenced off, and the rep always speaks in their own words." Repeat the hook. |

**Demo safety:** record a backup video of the full demo and keep it as a hidden slide. The stage computer and Wi-Fi are out of your control.

### Face-to-face Q&A prep

- **"How is this different from Gong or Cresta?"** Those are post-call analytics or enterprise contact-centre tools. Girard is live, grounded in your own salesbook, and cheap enough for a 5-person firm.
- **"What if the model is wrong?"** It gives sentence openers, not a script. Strict schema, timeout, silent by default. Know the 4 failure cases (3 unwanted cards, 1 wrong card).
- **"Why Qwen3-30B-A3B?"** A MoE with ~3B active parameters: fast and cheap. A short structured-output task doesn't need a frontier model. Back it up with the table.
- **"Consent and recording laws?"** Only the prospect is transcribed and nothing is stored, but the rep still has to tell the prospect. A consent step is on the roadmap.
- **"Is there live audio?"** Be upfront: the demo uses a scripted transcript, and speech recognition is the next integration. Don't overclaim.
- **"Why would anyone pay?"** One saved deal pays for years of seats, and we are user #1.

### Draft form answers (edit the brackets)

**What did you build, and what problem does it solve?**
Sales reps at small B2B service firms lose deals in the seconds after a prospect asks "what's your rate?" or names a competitor. The answer exists in a playbook, but nobody can read one mid-call. Girard listens to the prospect and, within about half a second, shows a card with 2–3 sentence openers grounded in the company's own salesbook. It stays silent the rest of the time. Reps at consultancies and agencies take several discovery calls a week, and today they rely on memory or pay for enterprise tools built for call centres. We run cards at about $0.30 per call-hour, so a per-seat product for firms with 2–50 people is viable. That's a market the enterprise players don't serve.

**Models and Token Factory use**
Qwen3-30B-A3B-Instruct-2507 on Nebius Token Factory runs the live lane. It classifies each prospect line against the salesbook and writes the openers in one streaming JSON call, with a strict schema whose id enum only allows salesbook entries that haven't been shown yet. We chose a MoE with ~3B active parameters for latency and cost. [Debrief: model X, if built.] [Closed model used only as an eval baseline.]

**Measurable model advantage**
Same 60-case labelled test set, same prompt: [comparison table]. Qwen3-30B-A3B: 93% accuracy (up from 83% after prompt iterations), card decided in p50 485 ms / p95 887 ms, ~$0.0005 per line. Token Factory prefix caching: time to first token 156 vs 260 ms p50. [Link to eval sheet.]

**Responsible design**
Only the prospect's side is transcribed, and the transcript lives in memory for the length of the call. Salesbook facts marked internal (margins, pricing rules) are banned from output, and the schema makes invented playbook entries impossible. Girard gives openers, not scripts, so the rep always decides what's said.

---

## 4. Question: "Commit that stuff in a new branch, call it nebius"

- Created branch `nebius` and committed all work as `05e4c61` ("Add Token Factory fast lane, demo portal and eval harness").
- Included: `server.py`, `static/index.html`, `eval/` (test set, runner, results including the new `results_20260923_124256.csv`), `cache_test.py` with its results, both salesbooks, `demo_call.txt`, `requirements.txt`, `.claude/launch.json` and README edits.
- The commit records `todo.txt` as deleted (it was already deleted in the working copy). Restore it with `git checkout master -- todo.txt`.
- `.env`, `.venv` and `__pycache__` are gitignored and were not committed.
- Not pushed yet. To push:
  ```bash
  git push -u origin nebius
  ```
