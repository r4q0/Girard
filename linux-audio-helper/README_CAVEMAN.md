# Minimal caveman: changes, integration, and performance

Version 0.4.0 · minimal rules version 2 · updated 2026-09-23

This implements the selected final caveman rules: the existing minimal filler cleanup, plus standalone `the` removal and sentence period/comma removal. **`for` is never filtered.** The helper remains headless: browser/desktop-call playback → local English STT → localhost JSON/SSE, with an optional compact copy of finalized speech. No extra language model, hosted compression service, or microphone capture is introduced.

## What changed

- Removed the browser UI, static routes, browser launcher, and obsolete UI checks/screenshot. Their prior versions remain in Git; the separately installed desktop prototype is untouched.
- Added finalized transcript snapshots at `/api/transcript`; retained live revisions through `/api/events`, explicit Start/Stop, output validation, app isolation, bounded audio queues, and shutdown cleanup.
- Added per-session `compression: "minimal"`, defaulting to `"none"`. Each final segment is processed once; polling, duplicate finals, and SSE reconnection reuse retained results. Partial text is unchanged and no additional endpointing wait is introduced.
- Added a dependency-free local compressor, original-character-span audit, protected phrases, raw fallback, and per-final-segment processing time.
- Added optional local tokenizer counting, a synthetic sales corpus, API/safety tests, and reproducible benchmark reports. The tokenizer dependency is not needed for normal operation.
- Updated minimal mode to rules version 2 without enabling the experimental article/copula/preposition stoplists. Raw text remains unchanged; defaults remain `compression: "none"` until explicitly enabled.

The audio path remains native-rate mono capture with requested 20 ms buffers and preloaded Moonshine Small Streaming on CPU. Compression is not audio preprocessing and does not improve recognition accuracy or shorten the STT engine's endpointing delay.

## Start and consume

Follow [installation and audio setup](README.md#run-the-helper), then run `./launch.sh --port 8766`. The server starts idle. Restart an older instance explicitly or use another free port; the launcher checks `compression_rules_version` in health and never stops or silently reuses a server with different rules.

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
  "compact_text": "We need approval",
  "is_final": true,
  "compression": {
    "mode": "minimal",
    "changed": true,
    "removed_words": 1,
    "rules_version": "2",
    "reason": "compressed",
    "removed_spans": [
      {"start": 2, "end": 8, "text": ", um, ", "replacement": " ", "rule_id": "remove_sentence_punctuation+comma_delimited_filler_run"},
      {"start": 21, "end": 22, "text": ".", "replacement": "", "rule_id": "remove_sentence_punctuation"}
    ],
    "tokens": null
  }
}
```

`compression_ms` measures the local pass including configured token counting, not STT or network latency. Audit offsets are Unicode character positions into the original segment, start inclusive/end exclusive; apply edits backwards to reconstruct the compact string. They are not UTF-8 byte or JavaScript UTF-16 offsets.

The transcript snapshot additionally supplies top-level `compact_text`, joined in timestamp order, and `compression: {"mode":"minimal","tokenizer":null}` (or the configured encoding name). Detailed audit remains on each segment. `final_only=false` includes partials unchanged in that aggregate; partial segment events have no compression fields. Upsert SSE events by `(session_id, segment_id)`, and reconnect for a fresh snapshot after a disconnect.

With `compression: "none"`, no compact fields are added to transcript events/snapshots. Health advertises supported modes; state exposes `compression_mode` and `compression_tokenizer`. Malformed JSON, unsupported fields, and invalid compression settings return HTTP 400 before capture. Session conflicts, unavailable output/stream selections, and invalid engine/isolation settings return 409.

## Exact rules and safeguards

1. Keep the original filler rule: remove only lowercase `um`/`uh` between commas, with meaningful speech on both sides. Detect these runs before removing punctuation; do not broaden cleanup to initial fillers, discourse markers, or acknowledgments.
2. Remove standalone `the`, case-insensitively, including `The` and `THE`. Do not remove that substring from other words or identifier fragments.
3. Remove sentence periods and commas. Preserve necessary word separation instead of joining neighboring words. Keep punctuation inside numeric values, dates, domains, versions/IP addresses, URLs, and email addresses.
4. Never delete `for`, `For`, or `FOR`. Do not delete other articles (`a`/`an`), copulas, or prepositions through a generic stopword list. Question marks, exclamation marks, and other non-target punctuation remain.

Existing ambiguity checks remain: quoted/metalinguistic/control-character input or an ambiguous eligible filler may make the whole segment stay raw. Uppercase or initial/final fillers are not removed, though other eligible article/punctuation edits may still apply. Hyphenated `uh-huh`/`uh-uh`, negation, numeric values, pronouns, modality, repetitions, and words such as `like`, `well`, `just`, and `maybe` are not targeted. Names containing `the` need explicit `protected_terms`; this pass is not entity recognition. There is no paraphrasing or language detection; enable it only for English.

`protected_terms` accepts up to 64 nonempty strings of at most 128 characters each. Terms are trimmed and matched as case-insensitive literal phrases. If an edit overlaps a match, the entire segment stays raw. Nonempty terms require minimal mode and reset with each new session.

More than 8,192 characters, 64 candidate fillers, or 512 candidate edits returns raw without token counting. Ambiguity, an empty/nonmeaningful candidate, tokenizer errors, and unexpected compressor exceptions also retain raw text. Raw `text` is always authoritative: filler removal loses hesitation, article removal can weaken references, and punctuation removal loses sentence/list boundaries. No semantic-equivalence guarantee is made.

Reasons are `compressed`, `no_eligible_changes`, `ambiguous_context`, `protected_term`, `limit_exceeded`, `no_token_savings`, `token_count_failed`, or runtime fallback `compression_failed`. `removed_words` counts removed fillers/articles, not punctuation; a punctuation-only edit can therefore be changed with zero removed words. Audit spans identify the applied rules and reconstruct the exact compact string. Unexpected compressor exceptions publish a generic warning without transcript-bearing exception details.

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

## Current verification — rules version 2

Example, without token counting: `The customer, um, needs the contract for the pilot.` → `customer needs contract for pilot`.

**333 text-only and mocked API tests passed** on 2026-09-23. No TTS, speech recognition, audio playback, or capture tests were rerun for this change. The checks cover rule boundaries, preservation of `for`, numeric/identifier punctuation, protected phrases, original-span reconstruction, unchanged raw/partial text, one-time final processing, API metadata, and detection of an older running helper. Existing aiohttp string-key warnings remain.

The [new text-only benchmark](reports/minimal-v2-benchmark.json) uses the same 42 synthetic inputs as version 1, not new audio or representative customer calls. With the reference `cl100k_base` complete-prompt guard, separate prompts totaled **1,527 → 1,461 tokens: 66 / 4.32% saved**, versus 38 / 2.49% under version 1. The guard retained raw text for six otherwise changed cases; 27 of 42 cases shortened after guarding. This is a controlled comparison, not an expected production saving.

| Warm local pass, p95 | No token counter | Reference full-prompt token guard |
| --- | ---: | ---: |
| Synthetic short segments, 10,500 samples | 0.018 ms | 0.034 ms |
| 2,000-character stress segment | 0.428 ms | 0.536 ms |
| 8,192-character stress segment | 1.716 ms | 2.038 ms |

These measurements are compression overhead on this CPU-only laptop, excluding startup, STT, capture, network delivery, and downstream LLM processing. The implementation adds no model calls, API fees, or endpointing wait. Local text processing still uses CPU/battery; latency and token savings vary with inputs and hardware.

## Historical measurements — rules version 1

**The following figures describe the original filler-only rules, not version 2.** Keep the old reports as historical evidence; do not use their savings percentages for the expanded implementation. The updated synthetic benchmark writes to `reports/minimal-v2-benchmark.json`.

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

The following checks use only text and mocked API sessions; they do not synthesize, transcribe, play, or capture audio:

```bash
.venv/bin/python -m pytest -q \
  tests/test_compression.py tests/test_compression_benchmark.py \
  tests/test_caveman_api.py tests/test_headless_api.py tests/test_cli.py \
  tests/test_tokens.py tests/test_experiments.py tests/test_real_call_eval.py
.venv/bin/python scripts/check_compression.py
# Requires the optional extra; reproduces reference-token audit and warm timings.
.venv/bin/python scripts/check_compression.py --tokenizer cl100k_base \
  --report reports/minimal-v2-benchmark.json
```

`scripts/check_session.py` performs a separate live audio integration check. It was deliberately **not run** for version 2, as requested.

The original version-1 release passed **237 tests**, covering existing capture/lifecycle behavior, deterministic/idempotent edits, original-span reconstruction, preservation counterexamples, token/error fallbacks, cached final results, API validation, HTTP/SSE consistency, and session resets. Version 2 extends the checks for definite articles, punctuation, protected numeric/identifier text, and unconditional `for` preservation. Existing aiohttp string-key recommendations appear as warnings, not failures.

The historical version-1 private-output integration check used bundled recorded narration, not a real call or microphone. It verified model preload without capture, explicit Start, 32 unchanged partial events, five finalized raw/compact segments, Stop flushing in 212 ms, and removal of all owned temporary audio resources with original settings preserved. Its five finals had 0.420 ms p95 compression time with `o200k_base`; this small live-pipeline sample is distinct from the warm isolated benchmark. See [caveman-session-check.json](reports/caveman-session-check.json). That run removed zero fillers; version 2 can shorten the same clean narration through article/punctuation removal. Paid cloud transcription has not been live-tested. Long calls, accents, prices/names, and end-to-end word latency still need representative validation.
