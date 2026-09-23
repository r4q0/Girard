# Minimal caveman: changes, integration, and performance

Version 0.3.0 · verified 2026-09-23

This implements the approved conservative filler-removal plan. The helper is now headless: browser/desktop-call playback → local English STT → localhost JSON/SSE, with an optional compact copy of finalized speech. No UI, extra language model, hosted compression service, or microphone capture is introduced.

## What changed

- Removed the browser UI, static routes, browser launcher, and obsolete UI checks/screenshot. Their prior versions remain in Git; the separately installed desktop prototype is untouched.
- Added finalized transcript snapshots at `/api/transcript`; retained live revisions through `/api/events`, explicit Start/Stop, output validation, app isolation, bounded audio queues, and shutdown cleanup.
- Added per-session `compression: "minimal"`, defaulting to `"none"`. Each final segment is processed once; polling, duplicate finals, and SSE reconnection reuse retained results. Partial text is unchanged and no additional endpointing wait is introduced.
- Added a dependency-free local compressor, original-character-span audit, protected phrases, raw fallback, and per-final-segment processing time.
- Added optional local tokenizer counting, a synthetic sales corpus, API/safety tests, and reproducible benchmark reports. The tokenizer dependency is not needed for normal operation.

The audio path remains native-rate mono capture with requested 20 ms buffers and preloaded Moonshine Small Streaming on CPU. Compression is not audio preprocessing and does not improve recognition accuracy or shorten the STT engine's endpointing delay.

## Start and consume

Follow [installation and audio setup](README.md#run-the-helper), then run `./launch.sh --port 8766`. The server starts idle. Use another free port if an older instance occupies it; the launcher never stops an existing service for you.

```bash
api_base=http://127.0.0.1:8766
curl --fail-with-body -sS "$api_base/api/devices"

curl --fail-with-body -sS "$api_base/api/start" \
  -H 'X-Call-Audio: 1' -H 'Content-Type: application/json' \
  -d '{"sink_id":"PASTE_AN_OUTPUT_ID_FROM_DEVICES","engine":"local","compression":"minimal","protected_terms":["Acme"]}'

# Poll finalized raw + compact text, or subscribe to live events.
curl --fail-with-body -sS "$api_base/api/transcript"
curl --fail-with-body -N "$api_base/api/events"
```

Run the streaming consumer separately; disconnecting it does not stop capture. To stop:

```bash
curl --fail-with-body -sS "$api_base/api/stop" \
  -H 'X-Call-Audio: 1' -H 'Content-Type: application/json' -d '{}'
curl --fail-with-body -sS "$api_base/api/transcript"
```

Wait for idle/`complete: true` before treating a successful session as finished. Starting another session replaces the in-memory transcript. No transcript database or audio recording is created.

For each final segment, existing `text`, timestamps, IDs, and endpoint fields retain their meaning. Example additive fields, with timing omitted here because it is measured at runtime:

```json
{
  "text": "We, um, need approval.",
  "compact_text": "We need approval.",
  "is_final": true,
  "compression": {
    "mode": "minimal",
    "changed": true,
    "removed_words": 1,
    "rules_version": "1",
    "reason": "compressed",
    "removed_spans": [
      {"start": 2, "end": 8, "text": ", um, ", "replacement": " ", "rule_id": "comma_delimited_filler_run"}
    ],
    "tokens": null
  }
}
```

`compression_ms` measures the local pass including configured token counting, not STT or network latency. Audit offsets are Unicode character positions into the original segment, start inclusive/end exclusive; apply edits backwards to reconstruct the compact string. They are not UTF-8 byte or JavaScript UTF-16 offsets.

The transcript snapshot additionally supplies top-level `compact_text`, joined in timestamp order, and `compression: {"mode":"minimal","tokenizer":null}` (or the configured encoding name). Detailed audit remains on each segment. `final_only=false` includes partials unchanged in that aggregate; partial segment events have no compression fields. Upsert SSE events by `(session_id, segment_id)`, and reconnect for a fresh snapshot after a disconnect.

With `compression: "none"`, no compact fields are added to transcript events/snapshots. Health advertises supported modes; state exposes `compression_mode` and `compression_tokenizer`. Malformed JSON, unsupported fields, and invalid compression settings return HTTP 400 before capture. Session conflicts, unavailable output/stream selections, and invalid engine/isolation settings return 409.

## Exact rules and safeguards

Only lowercase `um` and `uh` between commas, with meaningful speech on both sides within a segment, are eligible. Adjacent eligible filler runs are handled together. Only touching whitespace/punctuation is repaired; other words remain unchanged.

Quotes, spelling/name/code discussions, possible letter spelling, sentence-boundary ambiguity, uppercase fillers, and segment-initial/final fillers stay raw. Hyphenated `uh-huh`/`uh-uh`, negation, amounts, dates, names, pronouns, modality, repetitions, and words such as `like`, `well`, `just`, and `maybe` are not deleted. There is no general stopword list, summarization, paraphrasing, or language detection; enable this only for English.

`protected_terms` accepts up to 64 nonempty strings of at most 128 characters each. Terms are trimmed and matched as case-insensitive literal phrases. If an edit overlaps a match, the entire segment stays raw. Nonempty terms require minimal mode and reset with each new session.

More than 8,192 characters or 64 candidate fillers returns raw immediately, without token counting. Ambiguity, tokenizer errors, and unexpected compressor exceptions also retain raw text. Raw `text` is always authoritative: even removing a hesitation can lose a signal of uncertainty, so this cannot guarantee semantic equivalence for arbitrary speech.

Reasons are `compressed`, `no_eligible_fillers`, `ambiguous_context`, `protected_term`, `limit_exceeded`, `no_token_savings`, `token_count_failed`, or runtime fallback `compression_failed`. Unchanged results have zero removed words and an empty audit. Unexpected compressor exceptions publish a generic warning without transcript-bearing exception details.

## Lowest-cost configuration and optional counting

Local STT and local compression incur **$0 in API fees**, but consume CPU/battery. No network or model request occurs in the live compression path. Compression does not reduce audio duration or an optional cloud transcription bill; any savings apply only to downstream text input that your application actually sends.

For the lowest overhead, omit `--tokenizer` and use the default dependencies. `tokens` is then null; character/word reductions are not presented as token savings. For a locally measured positive-savings guard, install the optional [tiktoken](https://github.com/openai/tiktoken) extra and select the encoding appropriate for your downstream model:

```bash
uv sync --locked --python 3.12 --extra dev --extra tokens
# Example only: use cl100k_base only when appropriate for your downstream model.
./launch.sh --port 8767 --tokenizer cl100k_base
```

Supported encodings are `cl100k_base` and `o200k_base`. Initialization/warmup happens before capture; the first use may download a public tokenizer vocabulary, which is then cached. Offline deployments must prepare dependencies, STT model, and tokenizer cache beforehand. No API key is needed for this counting. Missing dependencies or failed initialization produce an actionable startup error rather than silently claiming counts.

With counting enabled, metadata includes `tokens: {"tokenizer":"cl100k_base","raw":N,"compact":M,"saved":N-M}`. If a proposed edit does not strictly reduce that segment's token count, raw text is retained. Literal tokenizer special-token strings are treated as ordinary customer text.

The server counts standalone segments, not a complete model request. Joining segments, adding a prompt wrapper, changing model/tokenizer, or provider framing can change counts. Benchmark your equivalent **complete prompts** with the actual downstream tokenizer before estimating cost; segment totals are not an invoice. The compressor's Python interface also accepts a local counter over your complete prompt wrapper.

Send **one** chosen string to the LLM, e.g. `snapshot.get("compact_text", snapshot["text"])`; keep raw text/audits outside that prompt. Sending the entire JSON response duplicates text and can cost more than the original. This component never calls the downstream LLM itself.

## Measured and expected performance

Measurements below are from this Linux laptop (Ryzen 7 250, 30 GiB RAM, CPU only, Python 3.12), not a guarantee for other machines. Warm timings exclude imports, model/tokenizer startup, and vocabulary downloads. The timing corpus has 42 equally weighted synthetic examples, each repeated 250 times; it deliberately includes 11 eligible cases and 31 unchanged counterexamples, not a representative call distribution.

| Local pass, p95 | No token counter | Reference full-prompt token guard |
| --- | ---: | ---: |
| Synthetic short sales segments | 0.009 ms | 0.025 ms |
| 2,000-character stress segment | 0.470 ms | 0.717 ms |
| 8,192-character stress segment | 1.752 ms | 3.021 ms |

Longer segments return raw through the size guard. Expect tiny overhead for typical short final segments and low-single-digit milliseconds near the limit on this machine. These are compression times only: they exclude STT endpointing, capture, and HTTP delivery, and are not a worst-case real-time guarantee.

Using reference `cl100k_base` with a fixed complete prompt, all 42 cases together went from **1,527 to 1,489 tokens: 38 tokens / 2.49% saved** across separate equivalent prompts, including the unchanged cases. The same cases combined into one prompt went from 502 to 464 tokens; sending both versions plus audit metadata instead required 4,049 tokens. Clean actual Moonshine narration stayed **110 → 110 tokens (zero savings)**.

The benchmark injects a full-prompt counter; the server's optional CLI counter measures standalone segments. Neither establishes production billing. The exact corpus, prompt wrapper, tokenizer version, timings, and side-by-side audits are in [compression-benchmark.json](reports/compression-benchmark.json). If your recognizer already removes fillers or punctuates them differently, this intentionally strict pass may save nothing. No downstream model or representative customer dataset has been selected, so there is no honest fixed savings percentage for production.

## Reproduce verification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_compression.py
# Requires the optional extra; reproduces reference-token audit and warm timings.
.venv/bin/python scripts/check_compression.py --tokenizer cl100k_base \
  --report reports/compression-benchmark.json
# Requires access to the existing PulseAudio/PipeWire service and pacat.
.venv/bin/python scripts/check_session.py --compression minimal --tokenizer o200k_base \
  --report reports/caveman-session-check.json
```

The full suite passed **237 tests**, covering existing capture/lifecycle behavior, deterministic/idempotent edits, original-span reconstruction, preservation counterexamples, token/error fallbacks, cached final results, API validation, HTTP/SSE consistency, and session resets. Existing aiohttp string-key recommendations appear as warnings, not failures.

The private-output integration check uses bundled recorded narration, not a real call or microphone. It verified model preload without capture, explicit Start, 32 unchanged partial events, five finalized raw/compact segments, Stop flushing in 212 ms, and removal of all owned temporary audio resources with original settings preserved. Its five finals had 0.420 ms p95 compression time with `o200k_base`; this small live-pipeline sample is distinct from the warm isolated benchmark. See [caveman-session-check.json](reports/caveman-session-check.json). The clean fixture removed zero fillers, with zero cloud fees and no physical playback. Paid cloud transcription has not been live-tested. Long calls, accents, prices/names, and end-to-end word latency still need representative validation.
