# Girard: Project Context

> Girard. The open-source sales copilot.
>
> Girard is a realtime, fully open-source, open-weight sales copilot that listens to your calls and helps you close in the moment.

This file gives full context on what we are building, why, and every decision made so far. Read it fully before writing code. When something here conflicts with a later instruction from the team, the team wins; update this file.

---

## 1. What we are building

Girard listens to a live sales call, transcribes it in realtime, and shows the sales rep short advice cards while the conversation is happening. Example: the customer says "we already use HubSpot for this", and within about a second the rep sees a card with 1 to 3 sentence openers they can start saying about how we compare.

Built for a one-day hackathon by a small team. It must work end to end in a live demo.

Named after Joe Girard, listed by Guinness as the world's greatest salesman (13,001 cars, sold one conversation at a time). A company called Girard AI already exists, so always publish with the descriptor: "Girard, the open-source sales copilot".

### Hackathon requirements (hard constraints)

1. Use at least one approved open-weight model served through **Nebius Token Factory**.
2. Prove a **measurable edge**: quality, cost, speed, or adaptability. We go for speed and cost, backed by a published benchmark.
3. Build something a real person would actually use.

### Differentiation

Existing open-source "sales copilots" (Pluely, free-cluely, VideoDB sales-copilot) use closed APIs, are built for cheating in interviews rather than transparent sales use, or publish no latency numbers. No existing open model or LoRA does live sales coaching (the few sales models on Hugging Face either play the salesperson, like salesGPT on phi-1.5, or score conversion odds). Girard stands on:

- **Open-weight models only**, no closed APIs anywhere in the product pipeline.
- **EU zero-retention inference** on Nebius Token Factory.
- **Consent-first, transparent design** for sales teams. A coaching tool, not a hidden cheating overlay.
- **Published latency and cost benchmark** proving realtime works with open models.

---

## 2. Architecture overview

```
 Mic / call audio
       |
 [1] Audio capture (speaker separation: REP vs CUSTOMER)
       |
 [2] Speech-to-text, streaming, sentence by sentence
       |
 [3] Trigger logic: decide WHEN to call the LLM
       |
   +---+---------------------------+-----------------------------+
   |                               |                             |
 [4] FAST LANE                  [5] SLOW LANE                 [6] RESEARCH LANE
 per customer sentence          every 30-45s or on events     async Tavily lookups
 -> one card or nothing         -> summary, deal state,       -> research cards,
                                   next questions, risks         cached per entity
   |                               |                             |
   +---------------+---------------+-----------------------------+
                   |
 [7] UI (Lovable): cards, research panel, live cost counter, latency per stage
                   |
 [8] Post-call summary report

 [0] Pre-call research (Tavily): prospect, website, likely competitors, cached before the call
```

### [1] Audio capture
- Capture both sides with **speaker separation** (REP vs CUSTOMER). The fast lane only reacts to the CUSTOMER.
- Optional audio optimizer: noise reduction, silence trimming, resampling to what the STT model needs, to cut STT latency.

### [2] Speech-to-text
Streaming, output per sentence. Candidates in order:
1. **Voxtral Realtime**
2. **Parakeet TDT 0.6B v3**
3. **Whisper large-v3-turbo** (fallback)

Nebius Token Factory only serves text-to-text models, so STT cannot run there. Run it locally or on a GPU (Nebius AI Cloud or our own H100s). Pick the lowest latency option on the day.

### [3] Trigger logic
Fast lane:
- Fire on **400 to 600 ms of silence after the CUSTOMER speaks** (voice activity detection).
- **Filter backchannels** ("yeah", "mm-hmm", "okay", "right").
- **Merge fragments** when the customer pauses mid-sentence.
- Optional early fire on keywords (competitor names, "price", "budget", "contract").
- **Cancel stale in-flight requests** when a newer customer sentence arrives.

Slow lane:
- **Every 30 to 45 seconds**, or immediately on major events (competitor, pricing, close attempt).
- Always **async**. Never blocks the fast lane.

### [4] Fast lane (advice cards)
- One LLM call per relevant customer sentence. Returns one card or nothing. Most calls return nothing.
- Purely **reactive**: only responds to what the customer just said. Proactive discovery questions ("you haven't asked about budget") belong to the slow lane.
- Prompt and schema in section 4.

### [5] Slow lane
- Input: full salesbook, full transcript so far, pre-call research.
- Output: the rolling **call summary** used by the fast lane (section 5), deal stage, unasked discovery questions, risks, next step.
- Produces the **post-call summary** at the end.
- Larger model, quality over speed. Internal outputs (summary, notes) written in terse "caveman" style; see section 7.

### [6] Research lane (live Tavily lookups)
No sub-agents needed. A plain async background job:
1. **Detect**: the fast lane returns a `q` field with a vendor/product name not in the playbook (or a keyword/entity check finds one).
2. **Fire and forget**: start a Tavily search as a background task (`asyncio.create_task` or a small job queue). The fast lane never awaits it.
3. **Summarize**: one quick LLM call condenses results into 1 to 3 bullets.
4. **Deliver**: push to the UI as a **research card**, visually distinct from advice cards (own panel or style).
5. **Cache** by entity, so the next mention is instant.

Rules:
- Check the pre-call cache before searching live.
- **Dedupe**: never search the same entity twice per call.
- **Timeout**: give up after ~10 to 15 s.
- Research cards do NOT use the fast lane staleness rule; they stay relevant for minutes.
- **Cap** lookups per call to control cost and UI clutter.
- Multi-step research ("search, read, search again") only in the slow lane, as a simple loop in our own code.

### [0] Pre-call research
Before the call: prospect company, website, recent news, maybe LinkedIn, plus likely competitors. Cached, so competitor cards need no live search.

### [7] UI (Lovable)
- Advice cards **close to the camera** so the rep keeps eye contact.
- Separate **research panel** for research cards.
- **Live cost counter** (tokens and euros this call).
- **Latency per stage** (STT, trigger, time to first token, total), including p95.
- Stretch: customer emotion / sentiment indicator.
- Lovable project already exists in the "Girard" workspace.
- The UI derives card type and title from the playbook entry via `id`; the model does not generate them (section 4.4).

### [8] Post-call summary
Summary, objections raised and how they were handled, competitors mentioned, next steps, follow-up email draft. Written for humans, so normal prose, not caveman style.

---

## 3. Models

### Fast lane: `Qwen/Qwen3-30B-A3B-Instruct-2507` (final decision)
- Mixture-of-experts: 30.5B total, ~3.3B active per token. Small-model speed with much better judgment than a dense 4B.
- Instruct-2507 is **non-thinking only**, so no reasoning tokens.
- **Confirmed served on Nebius Token Factory.**
- Used **prompt-only** first. Works from minute one.
- On Token Factory's LoRA fine-tuning list, so a LoRA can be added later with the same prompt.

Why not Qwen3.8: it has no small models (smallest dense is 27B; Qwen3.8-Flash-Next is a 125B MoE preview) and it cannot be LoRA fine-tuned on Token Factory. For speed, model size matters more than version.

### Optional later: LoRA fine-tune
- Goal: better cards, fewer false triggers, same speed. Clean benchmark: same model, same prompt, only the LoRA differs.
- **Caveat**: Nebius documents a separate procedure for merging **MoE** LoRA weights onto **dedicated endpoints**, so a LoRA on this MoE model may not be deployable serverless. Verify before investing time.
- Fallback for the LoRA phase: **Qwen3-8B** (dense) or **Qwen3-4B** if speed matters more. **Llama-3.1-8B-Instruct** is the model Nebius uses in its own serverless LoRA docs, so it is the safest serverless option.
- Train on Token Factory itself. Our own H100 stack is only a fallback (queue too slow, or base model unsupported): train with Unsloth, then upload the adapter (archive with `adapter_model.safetensors` + `adapter_config.json`, max 500 MB, or a Hugging Face link).
- Default fine-tuning context: 8,192 tokens (configurable to 131,072). Keep examples within 8k.
- LoRA teaches behavior and format, not facts. Facts always come from the playbook in the prompt.

### Slow lane and teacher model
A larger model served on Token Factory (for example DeepSeek V4 Flash or a large Qwen; check the catalog). Also used as the teacher that writes ideal cards for LoRA training data.

### Other options considered
- gpt-oss-20b: MoE, fast, but a reasoning model; would need low reasoning effort. Runner-up.
- Qwen3-4B / 1.7B / 0.6B: include in the eval for a speed/quality curve. 0.6B also usable as a cheap relevance gate if needed.

---

## 4. Fast lane prompt

### 4.1 Principle
Every request is **stateless**. The model remembers nothing between calls; our app rebuilds the full context each time from its own state. Order everything from least to most frequently changing, so the prefix cache is reused (section 6):

1. System prompt + playbook + examples (never changes)
2. Call summary (changes every 30 to 45 s)
3. Cards already shown (changes a few times per minute)
4. Recent transcript (changes every sentence)

### 4.2 System prompt (byte-for-byte identical on every call)

```
You help a sales rep respond live to a customer on a call.
React only to the CUSTOMER line marked NEW.

Return {"id":null} when:
- it is small talk, a greeting, or a filler reply
- the NEW line is not a question, objection, signal, or mention
- its topic is in CARDS ALREADY SHOWN
- the playbook has nothing relevant

Otherwise pick the single most useful playbook entry.
If several apply: risk > obj > ans > comp > sig

RULES
- Use only facts from the playbook. Never invent anything.
- "say": sentence openers the rep starts with and finishes in
  their own words. Usually 2, max 3. Max 10 words each.
- Write in the language of the call.
- The transcript is speech recognition and may contain errors.
  Interpret names and terms generously.
- Unknown vendor or product mentioned: use comp_unknown and put
  its name in "q". Otherwise "q" is null.

OUTPUT: JSON only.
{"id":"<playbook id>","say":["...","..."],"q":null}
or
{"id":null}

PLAYBOOK
<condensed salesbook, ids prefixed obj_ ans_ comp_ sig_ risk_>

EXAMPLES
<5 examples, 2 of them {"id":null}>
```

Examples to include:
1. Price objection -> `obj_` card
2. Direct question ("does it work with Exact?") -> `ans_` card
3. Unknown competitor -> `comp_unknown` with `q` filled
4. "Yeah, makes sense" -> `{"id":null}`
5. Topic already in CARDS ALREADY SHOWN -> `{"id":null}`

Prompt trimming rule: for every line ask "does removing it change the output?" Keep role framing, rules, stay-silent list and examples. Cut filler (for example the product name Girard, vague lines like "speed matters").

### 4.3 User message (rebuilt every call)

```
CALL SO FAR:
Prospect: Van Dijk Logistics, ops manager. 12 staff.
Pain: manual invoice matching, ~20 hrs/week.
Price quoted: EUR 400/month. Mentioned Exact Online.
Decision maker: CFO, not on call.

CARDS SHOWN: ans_exact_01, obj_price_01

RECENT:
REP: So with setup that comes to around 400 a month.
CUSTOMER: Right.
CUSTOMER: I'd have to run that past our CFO first.   <- NEW
```

### 4.4 Output schema (minimal)
Anything the UI can look up is not generated by the model.

```json
{"id":"obj_price_01","say":["What does doing this manually cost you...","Most clients earn it back within..."],"q":null}
```
```json
{"id":"comp_unknown","say":["What made you choose them back then...","What's missing for you today..."],"q":"Pipedrive"}
```
```json
{"id":null}
```

- `id` is the **first key**, so "no card" is known after ~4 tokens and the client can stop the stream.
- Type comes from the id prefix: `obj`, `ans`, `comp`, `sig`, `risk`. Title and proof come from the playbook entry.
- A card is ~30 output tokens, a no-card ~4.

UI side:
```js
const entry = playbook[card.id];          // title, type, proof
const type  = card.id.split("_")[0];      // obj, ans, comp, sig, risk
if (card.q) researchLane.lookup(card.q);  // async Tavily, never awaited
```

### 4.5 Enforcing the schema on Nebius
- Token Factory supports structured output via `response_format` with `{"type": "json_schema"}` plus a JSON Schema. `{"type": "json_object"}` also exists but does not enforce a schema.
- Nebius recommends putting the schema **both** in the prompt text and in the `json_schema` parameter.
- Check the model card for the "JSON mode" tag; support differs per model.
- Verify structured output works together with streaming.

---

## 5. Context management (summary + window)

The model only knows what is in the current request, so context is layered:

1. **Recent transcript, verbatim**: last ~45 to 60 s, both speakers. Handles references like "that" or "it".
2. **Call so far**: summary of everything older, written by the slow lane every 30 to 45 s, capped at ~100 to 200 tokens. The slow lane **rewrites** it to the budget instead of appending.
3. **Cards already shown**: prevents repeats.

Why: request size stays constant regardless of call length.

```
S = static prefix (~3.5-4.7k tokens), r = ~150 tokens per minute of speech,
t = minutes into the call, w = window (0.75 min), C = summary cap (~150)

Full transcript:     L(t) = S + r*t        grows linearly
Summary + window:    L    = S + C + r*w    constant

Cumulative input over a call of length T at k calls/min:
Full transcript:   k * (S*T + r*T^2/2)   quadratic
Summary + window:  k * T * (S + C + r*w) linear
```

For a 40 minute call at 10 calls/min, transcript tokens alone: ~1,200,000 (full) vs ~108,000 (summary + window). Plus: decode slows with longer context, cache misses cost more with long prompts, and small models lose accuracy with long irrelevant context.

App state (lives in our code, never in the model):
```
state: summary, cards_shown, recent_lines

on each new customer sentence:
  request = system_prompt + summary + cards_shown + recent_lines
  send -> get card -> update cards_shown
```

---

## 6. Nebius caching and latency (measured)

Test: `cache_test.py`, 25 calls per group, groups alternated in random order, plus a 10 call test with a brand-new prefix, ~4,700 token prompt, fast lane model. Raw data in `cache_test_results.csv`. Run again with more calls: `python cache_test.py 50`.

Findings:
- **Nebius caches identical prompt prefixes automatically**, even though prompt caching is not documented and there is an open feature request for discounted cache pricing.
- Same prefix every call: **24 of 25 cached** (96%), 4,720 of 4,728 tokens cached.
- New first line every call: 0 of 25 cached.
- A new prefix is cached from its 2nd call; 8 of 10 hits overall.
- Time to first token: **hit median 157 ms** (middle 50%: 139 to 194), **miss median 260 ms** (228 to 326). About 100 ms (~40%) saved at this size; savings grow with longer prefixes.
- Plan for **5 to 20% misses** even with a repeated prefix (likely calls spread across servers).
- **Tail latency is the real risk**: some calls took 1 to 11 s, cached or not (likely server queueing).

Rules that follow:
- Build the static prefix (system prompt, playbook, examples) **once at startup**, never re-format it. One changed character near the top wipes the cache for the whole prompt.
- No timestamps, session IDs, or dates above the transcript. Anything that changes goes at the end.
- **Hard timeout ~1.5 s** on fast lane calls; past that, cancel and show nothing.
- **Hedged requests**: if no first token after ~400 ms, fire an identical second request, use whichever answers first, cancel the other. Fast lane only.
- **Drop stale cards** older than ~4 s after their trigger sentence.
- Track **p50, p95 and p99** per stage, not just the median.
- Possibly reuse one client connection per session for server affinity; test, don't assume.
- Open question: check the Nebius invoice after a test run to see whether `cached_tokens` are billed at a discount or at full price. Assume full price until proven otherwise. This decides the cost line in the benchmark.

---

## 7. Salesbook (playbook)

Fed in through the **prompt**, not trained into weights. Girard works with any company's salesbook without retraining.

For the demo: one salesbook for a **believable fictional company**, matching the demo call.

### 7.1 Sections
- **Company and product basics**: what, for whom, core value in two lines.
- **Pricing and packages**: exact numbers, inclusions, allowed and forbidden discounts.
- **Ideal customer profile and qualification**: fit, non-fit, disqualifiers.
- **Discovery questions**: tagged by stage (used by the slow lane).
- **Objections** (the core): triggers, underlying concern, response, proof.
- **Competitors**: how they are mentioned, where we win, where they are better, what not to say. Plus a generic `comp_unknown` entry.
- **Direct answers**: common customer questions (integrations, security, contract terms) with factual answers.
- **Proof**: case studies and numbers as short facts.
- **Buying signals**: phrases plus suggested next step.
- **Risk signals**: "check with my boss", "no budget this year", with responses.
- **Compliance and don'ts**: promises and claims that are not allowed.

### 7.2 Entry format
Compact text, not JSON. Terse ("caveman") everywhere except the lines meant to be spoken.

```
[obj_price_01] OBJECTION: too expensive
Triggers: "too expensive", "over budget", "cheaper elsewhere"
Concern: doesn't see ROI yet
Say: Ask what the manual process costs per month. Compare to price.
Proof: Client X saved 40 hrs/month, paid back in 5 months.

[comp_hubspot_01] COMPETITOR: HubSpot
Mentions: "we use HubSpot", "HubSpot already does this"
We win: <...>
They win: <...>
Don't say: anything negative about HubSpot itself
Say: Ask what they wish HubSpot did better. We integrate, no migration.
```

### 7.3 Size
~3,000 to 4,000 tokens, roughly 25 to 40 entries. Caching makes the static part cheap in latency, but not necessarily in cost, and shorter still means fewer distractions for the model.

### 7.4 Salesbook converter
Any messy salesbook (PDF, doc, notes) goes through a large model and comes out in this format. Demo moment: "drop in any salesbook".

### 7.5 Where terse "caveman" style is used
- Playbook entries: yes (except spoken lines).
- Slow lane internal outputs (summary, deal state, notes): yes. Use a few lines of our own ("No filler. No articles. Fragments OK. Facts only."), not the full viral caveman skill; a short version performs as well or better.
- Fast lane `say` openers: **no**. They must sound natural when spoken.
- Post-call summary and follow-up email: no. Humans read them.
- Transcript compression (LLMLingua-style): no. Adds latency, and the model needs the customer's exact words.

---

## 8. Benchmark and eval (our measurable edge)

Build the eval harness early. Same labeled test set through several configurations:

- Fast lane model, prompt-only (Qwen3-30B-A3B-Instruct-2507)
- Lean vs full system prompt (ship the lean one if accuracy is equal)
- Same model + LoRA (if we get there)
- Smaller models for the speed/quality curve (Qwen3-4B, Qwen3-1.7B)
- A large model as quality reference

Measure:
- **Latency**: time to first token, total, p50 / p95 / p99, cache hit rate
- **Cost**: euros per call-hour
- **Quality**: correct card vs expected, false positives, false negatives, JSON validity

Test set: transcript chunks from the demo conversation plus synthetic ones, each labeled with the expected card or `{"id":null}`.

Headline: *"Girard shows the right card in under X seconds at Y euros per hour of calls, fully open-weight, in the EU."*

---

## 9. LoRA training data (if we fine-tune)

1. Realistic transcript chunks (demo conversation plus synthetic variations).
2. A large teacher model writes the ideal output for each chunk using the playbook (distillation).
3. Spot-check and delete bad examples (at least 30 minutes).
4. 500 to 1,500 examples, with plenty of `{"id":null}`.
5. Chat JSONL with the **playbook inside the system prompt** of every example, so the model learns to use any playbook:

```json
{"messages": [
  {"role": "system", "content": "<exact fast lane system prompt with playbook>"},
  {"role": "user", "content": "CALL SO FAR: ...\nCARDS SHOWN: ...\nRECENT: ..."},
  {"role": "assistant", "content": "{\"id\":\"obj_price_01\",\"say\":[\"...\"],\"q\":null}"}
]}
```

Time estimate: data 1.5 to 2.5 h, training ~20 to 60 min (mostly queue), deploy 10 to 20 min, eval ~1 h. Run a 50-example test fine-tune early to learn real times. While training runs, the app keeps using the base model with the same prompt; swapping is just the model name.

---

## 10. Team and task list

Owners in parentheses. Status: not started unless noted.

**Data and demo**
- Test transcript file / demo conversation (Noah)

**Audio**
- Capture audio (Josef)
- Audio to text, locally or fastest option (Josef)
- Audio optimizer / "caveman-esque" preprocessing (Josef)

**Core logic**
- When to send transcript to the LLM (all, led by Dante)
- Salesbook standard input (Milan + Noah)
- Output format (Noah + Dante): proposal in section 4.4
- LLM optimization / context feed / RAG (Noah + Dante): proposal in sections 4 to 6
- Tavily retrieval for competitors mentioned (Noah): design in section 2 [6]
- Post-call summary report (Noah)
- Pre-call strategy retrieval: Tavily, website, maybe LinkedIn (whoever has time)
- Nebius prefix caching test: **done**, results in section 6

**UI**
- Lovable UI: live price counter, emotion reading (stretch), latency per part, output close to camera (Milan, then everyone)

**Launch**
- Presentation (all)
- Demo recording: Noah writes the concept, everyone acts. Ultra-high quality.
- Product Hunt and similar, LinkedIn copy and strategy, outreach messages, people list (all)

**Stretch**
- Emotional indicator (~2 h)

---

## 11. Engineering conventions

- **Open-weight models only** in the product pipeline. No OpenAI, Anthropic or Gemini calls.
- The **fast lane never waits** on the slow lane, research lane, or web search.
- **Log latency per stage** and **token usage / cost per request** from the start.
- Secrets (Nebius API key, Tavily key) only in environment variables, never in code, chat, or the repo. Any key that was ever pasted into a chat must be revoked.
- Token Factory is OpenAI-compatible: `base_url="https://api.tokenfactory.nebius.com/v1"` with the standard `openai` client.
- Enforce output schemas via `response_format` json_schema.
- Consent-first: make it easy to tell the customer the call is assisted. Never build features that hide Girard.

### Copy and writing style
- Never use em dashes in any user-facing copy, docs, or UI text.
- Short declarative sentences. No marketing fluff.

---

## 12. Open questions

- Can a LoRA on the MoE fast lane model be deployed serverless, or only on a dedicated endpoint?
- Are cached tokens billed at a discount? (check invoice)
- Does structured output (json_schema) work with streaming for our schema on this model?
- Which slow lane / teacher model is best from the Token Factory catalog?
- Which STT option is fastest on the day's hardware?
- Does connection reuse improve cache hit rate?
