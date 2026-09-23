# Caveman compression on real telephone audio

Date: 2026-09-23 · CPU-only local experiments · production behavior unchanged

Historical report: the minimal control here uses **rules version 1**, before the subsequent request to remove `the` and sentence periods/commas while always retaining `for`. The measurements below are preserved unchanged; they do not describe the final version-2 implementation.

## 1. Decision in one minute

**Stronger compression is fast, but the extra savings are not meaning-preserving.** On the same 106 finalized segments from two genuine phone-call samples:

- **Current minimal:** 0 tokens saved. Its strict interior-filler pattern never matched.
- **Expanded disfluency:** 5–6 tokens saved, or **0.40–0.51%** of the four complete reference prompts. All four edits removed an introductory discourse marker; this corpus did not demonstrate useful broader hesitation removal.
- **Light telegraphic:** 42–43 tokens saved, **3.38–3.63%**, but article deletion changed a quantity implication.
- **Aggressive telegraphic:** 110–111 tokens saved, **8.85–9.38%**, but removed important deadline, obligation, tense, and relationship information.
- All experimental passes were quick: **p95 below 0.035 ms without counting**, or **below 0.047 ms including a local token-savings guard**, on this short-segment corpus. These are not whole-call response latencies.

**Recommendation:** keep raw text as the authoritative record and compression off by default, with the existing minimal mode available. Broader disfluency merits a controlled trial on consented customer audio, but its measured savings here are negligible. Do not enable either telegraphic mode in customer-context prompts on this evidence.

The stronger implementations are available **only in the offline experiment tooling**, not as production API modes. No Git commit/push or service restart was performed for this research request.

## 2. What was actually measured

This is **real audio → the existing local recognizer → finalized transcript → compression**. It is not a fabricated transcript, TTS conversation, acted sales script, or the old narration fixture.

| Source | Selected audio | Purpose |
| --- | --- | --- |
| CALLFRIEND non-Southern American English public sample | Full 120-second stereo sample; channels 0 and 1 separately | Real unscripted telephone speech |
| CALLFRIEND Southern American English public sample | Full 120-second stereo sample; channels 0 and 1 separately | Another real call/dialect condition |

LDC describes these as unscripted telephone conversations, generally with friends/family, and documents one telephone endpoint per channel. They are **not customer sales calls**. [Non-Southern corpus and public sample](https://catalog.ldc.upenn.edu/LDC2019S21), [Southern corpus and public sample](https://catalog.ldc.upenn.edu/LDC2020S08).

The two complete samples were selected before inspecting compression results; no favorable excerpt was selected afterward. There are **two independent source calls, four call-side streams, four minutes of unique conversation, and eight channel-minutes**—not four independent calls. Channel identity is known; customer/agent roles are not.

Each downloaded file is 3,840,044 bytes, PCM16 stereo at 8 kHz. Each side was fed separately through Moonshine Small Streaming English, version 0.1.5, in requested 20 ms blocks with a one-second silent tail. Channels were never mixed. This approximates remote-side-only input, but uses offline file replay, not a new live capture/Zoom/Teams test.

| Item | Measured/configured value |
| --- | --- |
| Final segments | 106: 18 + 28 + 27 + 33 across the four sides |
| Raw text | 824 lexical words; 3,947 characters, excluding join separators |
| Segment lengths | Median 22 characters; maximum 184 characters |
| Hardware | AMD Ryzen 7 250, 8 cores / 16 threads, 30 GiB RAM; inference/compression on CPU |
| Runtime | Python 3.12.14; tiktoken 0.14.0 |
| STT replay | As fast as possible; 114.307 seconds total wall time for eight channel-minutes, excluding initial load |
| Compression timing | 200 repetitions of every final segment per mode; 20 warmup repetitions excluded |
| Reference tokenizers | cl100k_base and o200k_base, already cached locally |
| Network during STT/compression/counting | No audio/transcript upload, hosted inference, or token-count API |
| Production changes | None; current minimal compressor and API left unchanged |

No customer recording was provided. This small, older telephone corpus cannot establish performance on modern sales vocabulary, named products, speaker overlap, accents beyond these samples, or complete customer calls. Recognizer mistakes remain in the raw transcript: this evaluation measures **additional compression damage relative to raw STT**, not recognition accuracy against the actual speakers. There is no gold transcript, word-error-rate test, or downstream answer-quality evaluation.

## 3. Implementations compared

| Name in tooling | Technique | Information at risk |
| --- | --- | --- |
| `raw` | No compaction | No additional compression loss |
| `minimal` | Existing production compressor: lowercase comma-delimited interior um/uh only | Hesitation signals; strict guards reduce opportunities |
| `disfluency` | Broader standalone um/uh/erm/er, including boundaries; leading comma-marked well/basically | Hesitation, emphasis, discourse intent |
| `telegraphic_light` | Disfluency rules plus lowercase a/an/the deletion | Definiteness, quantity implications, some name/reference structure |
| `telegraphic_aggressive` | Light rules plus lowercase copula/auxiliary forms and selected prepositions | Tense, obligation, agency, deadlines, recipients, direction, relations |

The aggressive preposition set is `of to from in on at for with by as`; copula forms are `am is are was were be been being`. There is no content-word stoplist and no deliberate deletion of negation, pronouns, modals, numeric tokens, or general uncertainty words.

Experimental guards preserve quoted/metalinguistic segments, identifiers, obvious capitalized-name spans, configured phrases, and some adjacent numeric/unit contexts. They do **not** amount to grammatical analysis or robust entity recognition. No corpus-specific protected phrases were configured in this run.

All variants are deterministic local code with original-character edit audits. Inputs over 8,192 characters stay raw; experimental variants also cap candidate edits at 512. Empty/nonmeaningful resulting segments stay raw, so standalone hesitation-only segments are not dropped. Current minimal retains its existing 64-candidate guard. Experimental passes are applied once to finalized raw text; unlike the current minimal algorithm, repeated experimental application is not promised to be idempotent.

## 4. Primary result: complete-prompt token savings

These totals sum **four complete prompts**, one per call side. Each prompt contains the same fixed instruction and that side's newline-joined transcript. Both encodings are reference measurements; no production downstream model has been selected.

| Implementation | Changed segments | cl100k compact tokens | cl100k saved | o200k compact tokens | o200k saved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw / compression off | 0/106 | 1243 | 0 (0.00%) | 1183 | 0 (0.00%) |
| Current minimal | 0/106 | 1243 | 0 (0.00%) | 1183 | 0 (0.00%) |
| Expanded disfluency | 4/106 | 1238 | 5 (0.40%) | 1177 | 6 (0.51%) |
| Light telegraphic | 31/106 | 1201 | 42 (3.38%) | 1140 | 43 (3.63%) |
| Aggressive telegraphic | 42/106 | 1133 | 110 (8.85%) | 1072 | 111 (9.38%) |

Raw baselines are **1,243 cl100k tokens** and **1,183 o200k tokens**. Percentages include unchanged final segments, short acknowledgments, and the fixed prompt wrapper; they are not calculated only over successfully edited text. Silent intervals without transcript text contribute no words or tokens.

Exact wrapper:

```text
Summarize the customer's goals, objections, constraints, commitments, and next steps from this call. Preserve exact numbers and uncertainty.
<transcript>
[the selected transcript, joined with newlines]
</transcript>
```

This is an experimental input template, not a claim that the source conversations are sales calls. Provider message framing, system prompts, retrieval context, output tokens, and cached-input billing are not included.

### Text reduction is not token reduction

| Implementation | Compact lexical words | Words removed | Compact characters | Characters removed |
| --- | ---: | ---: | ---: | ---: |
| Raw / compression off | 824 | 0 (0.00%) | 3947 | 0 (0.00%) |
| Current minimal | 824 | 0 (0.00%) | 3947 | 0 (0.00%) |
| Expanded disfluency | 820 | 4 (0.49%) | 3923 | 24 (0.61%) |
| Light telegraphic | 783 | 41 (4.98%) | 3801 | 146 (3.70%) |
| Aggressive telegraphic | 715 | 109 (13.23%) | 3577 | 370 (9.37%) |

The aggressive pass removes **13.23% of lexical words**, but saves only **8.85–9.38% of these complete-prompt tokens**. Word counts use a Unicode lexical regex, so punctuation-separated numbers can be multiple words; they are not whitespace counts or model tokens.

### Delivery pattern changes the percentage

Each cell lists **cl100k / o200k** savings. The text edits are identical.

| Implementation | Standalone segment tokens summed | Four complete call-side prompts | 106 separately wrapped segment prompts |
| --- | ---: | ---: | ---: |
| Raw / compression off | 0.00% / 0.00% | 0.00% / 0.00% | 0.00% / 0.00% |
| Current minimal | 0.00% / 0.00% | 0.00% / 0.00% | 0.00% / 0.00% |
| Expanded disfluency | 0.46% / 0.58% | 0.40% / 0.51% | 0.10% / 0.13% |
| Light telegraphic | 3.83% / 4.13% | 3.38% / 3.63% | 0.87% / 0.92% |
| Aggressive telegraphic | 10.03% / 10.66% | 8.85% / 9.38% | 2.29% / 2.39% |

The raw baseline for independently wrapping every final segment is **4,813 / 4,651 tokens**. Repeating instructions dilutes the aggressive pass's savings to **2.29–2.39%**. Larger unchanged salesbooks, RAG context, or system instructions would dilute total-request savings further. This is not a live-LLM scheduling experiment; batching also changes responsiveness and context availability.

### Variation across call sides

Complete-prompt savings, cl100k reference encoding:

| Call side | Final segments | Raw prompt tokens | Current minimal | Disfluency | Light | Aggressive |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| north-channel-0 | 18 | 220 | 0.00% | 0.00% | 3.64% | 9.09% |
| north-channel-1 | 28 | 374 | 0.00% | 0.53% | 2.67% | 9.09% |
| south-channel-0 | 27 | 343 | 0.00% | 0.87% | 5.54% | 11.37% |
| south-channel-1 | 33 | 306 | 0.00% | 0.00% | 1.63% | 5.56% |

Two sides produced no disfluency savings at all. Do not extrapolate an average from two calls as a reliable production rate or confidence interval.

## 5. Positive-token-savings guard

Each variant was also tested with the deployed-style optional guard: count raw and candidate **standalone segment** tokens locally; keep the candidate only if it strictly reduces that count.

For both encodings, all proposed edits passed: **0 / 4 / 31 / 42 accepted edits** for minimal / disfluency / light / aggressive, and **zero rejected edits**. Consequently, guarded and unguarded savings in this corpus are identical. Complete joined prompts were re-counted afterward, not inferred from segment totals; none increased.

This guard prevents a measured token increase for an individual segment. It does **not** prevent information loss, certify a whole production request, or compensate for a mismatched tokenizer. It accepted the problematic quantity/deadline edits discussed below.

## 6. Latency and speed

All values below are **milliseconds per final segment**, measured wall-clock time. The no-count column includes only the local pass/adapter; counted columns include compression plus a standalone positive-savings guard.

| Implementation | Bare p50 | Bare p95 | Bare p99 | Bare maximum | With cl100k guard p95 | With o200k guard p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw / compression off | 0.0005 | 0.0006 | 0.0010 | 0.0257 | 0.0065 | 0.0042 |
| Current minimal | 0.0014 | 0.0023 | 0.0034 | 1.9880 | 0.0076 | 0.0057 |
| Expanded disfluency | 0.0063 | 0.0270 | 0.0401 | 0.0898 | 0.0336 | 0.0316 |
| Light telegraphic | 0.0066 | 0.0299 | 0.0559 | 0.1047 | 0.0414 | 0.0364 |
| Aggressive telegraphic | 0.0076 | 0.0348 | 0.0613 | 0.3458 | 0.0462 | 0.0417 |

There are 21,200 measured invocations per variant/mode. The raw row is an adapter control; a raw production path need not call a compressor at all. Timings include measurement/adapter overhead and ordinary OS scheduling. The current minimal maximum of approximately 1.99 ms is an observed outlier, not its usual latency or a guaranteed upper bound.

The detailed JSON includes process-CPU distributions, guard-only time, and combined-operation p50/p95/p99/max. Do not add separate p95 values to estimate combined p95; the combined paths were measured directly.

These short segments are not a worst-case input-size benchmark. Imports, tokenizer loading, vocabulary downloads, file I/O, STT, prompt assembly, HTTP transport, and downstream LLM work are excluded. No additional endpointing wait was introduced. **Token savings do not demonstrate an equal percentage reduction in end-to-end response latency.** No downstream LLM was invoked, so its speedup is unmeasured.

The cost-focused configuration remains preloaded local STT plus finalized-only processing. Without an actual downstream tokenizer choice, omit live counting for minimum overhead and label savings unknown; once selected, the local guard's small measured overhead may be worth its token-count check.

## 7. Meaning preservation: the limiting factor

All coarse automatic checks passed: no count differences in matched numerals, number words, negation, modality, uncertainty, pronouns, condition/time keywords, or configured protected phrases. **That did not make the stronger output safe.** Such checks cannot detect information carried by grammar and relationships.

A separate assistant review inspected all 42 distinct changed segments across the variants against raw STT. It was not blind, not human annotation, and not an audio-faithfulness or downstream task-quality test.

| Variant | Review outcome |
| --- | --- |
| Minimal | No edits; no additional compression loss in this corpus |
| Disfluency | Four introductory-marker deletions; pragmatic nuance lost, no clear factual distortion observed |
| Light | At least two specific quantity/count caution cases |
| Aggressive | At least fourteen specific grammatical/relationship caution cases, including the light cases |

Those counts are **illustrative minimum flags, not error rates**. The other edited segments are not certified safe.

### Concrete failures in the actual STT output

Short snippets below come from the Southern sample; the rest is paraphrased to avoid reproducing full source conversations.

| Local segment reference | Change / weakened information | Why this matters |
| --- | --- | --- |
| south-channel-0 / …8116 | Light/aggressive: `a few` → `few` | A small positive quantity becomes a scarcity implication |
| south-channel-0 / …8108 | Aggressive: `by the 31st` → `31st` | The date remains, but the deadline relationship disappears |
| south-channel-0 / …8119 | Aggressive: `on the phone` → `phone` within a transfer phrase | A communication method becomes ambiguous with transferring an object |
| south-channel-1 / …8143 and …8159 | Aggressive: the obligation construction loses its linking preposition | Content words survive, but commitment/necessity becomes less clear |
| north-channel-1 / …8098 | Aggressive: location, association, and intended-recipient links are deleted | Keeping people/object words does not preserve who receives what |

Additional caution references: south-channel-0 …8103 and …8109; north-channel-0 …8064; north-channel-1 …8087, …8096, …8097, …8100; south-channel-1 …8152. Segment IDs in this run share prefix `1624341538572970`; append the suffix shown. The full side-by-side audit remains private locally.

Separate synthetic regression counterexamples also show that aggressive deletion can collapse opposite payment directions into the same text and erase past-versus-present ownership. These tests demonstrate possible failures; they are **not** included in the real-call savings totals.

## 8. What the savings mean for cost

Local STT, all compression variants, and local token counting used **no paid inference APIs**. CPU/battery usage still exists. Web research and public sample downloads were separate from the measured pipeline. Compression cannot reduce a cloud STT bill tied to connected audio time.

For an uncached input price of `P dollars per million tokens`:

```text
input-cost saving = saved input tokens × P / 1,000,000
```

Across these four call-side prompts, this is:

| Mode | Tokens saved across both reference encodings | Illustrative saving at P = $1/million input tokens |
| --- | ---: | ---: |
| Current minimal | 0 | $0 |
| Disfluency | 5–6 | $0.000005–$0.000006 |
| Light | 42–43 | $0.000042–$0.000043 |
| Aggressive | 110–111 | $0.000110–$0.000111 |

The $1 price is a round arithmetic example, **not a quoted provider price**. Use your model's real tokenizer, price, full prompt, cache policy, and output usage before estimating a bill. Absolute savings here are tiny, especially compared with the potential cost of misreading a deadline or obligation.

Send one chosen text version downstream, never raw + compact + audit metadata. Avoid retransmitting provisional revisions as new text. Review whether unchanged context or repeated instructions dominate requests before weakening customer meaning; request scheduling and state/caching semantics are separate application decisions, not changes made here.

## 9. Comparison with the earlier synthetic benchmark

| Dataset | Current minimal result | Interpretation |
| --- | --- | --- |
| Earlier 42-case synthetic sales suite | 38 tokens saved; 2.49% across separately wrapped reference prompts | Intentionally included eligible comma-delimited fillers |
| Earlier clean narration | Zero saved | Clean recognized text offers no eligible removals |
| These genuine call samples | Zero saved in both encodings | No eligible production-minimal pattern appeared in the finalized STT |

The earlier report used a different prompt wrapper. This comparison explains why synthetic savings should not be presented as real-call expectations; it is not a controlled cross-dataset statistical estimate.

## 10. Other aggressive approaches considered, not measured

| Approach | Potential benefit | Why it is not promoted by this result |
| --- | --- | --- |
| Drop standalone hesitation-only segments | Could eliminate tiny filler turns | Not implemented here; current safeguards retain nonempty raw segments, and hesitation can express uncertainty. Needs a separate event/API contract and held-out tests. |
| Remove repeated phrases or backchannels | May reduce conversational redundancy | Repetition can be emphasis/correction; acknowledgments can convey agreement/refusal. No blanket deletion was tested or endorsed. |
| Learned token classification, e.g. LLMLingua-2 | Context-aware selection instead of fixed stopwords | Requires another model/runtime. CPU latency and sales-context fidelity were not measured here, so no savings or speed claim is assigned. |
| LLM summarization or structured fact extraction | Potentially much larger text reduction | Changes the representation, needs task-quality checks, and adds inference cost/latency; not a local filler pass. |
| gzip/shorter JSON keys | Fewer transport bytes | Does not itself reduce tokens when the model still receives the same text. |

LLMLingua-2 is a learned token-classification approach using an encoder, not a synonym for these regex rules. Published gains against other neural compressors should not be treated as speedups over our measured microsecond-scale local passes. [Primary paper](https://aclanthology.org/2024.findings-acl.57/), [official implementation](https://github.com/microsoft/LLMLingua).

## 11. Reproduce and inspect

New files are `src/call_audio/experiments.py`, `scripts/transcribe_eval_audio.py`, `scripts/evaluate_real_call.py`, and their tests. Production API options are still only `none` and `minimal`.

Verification: **360 tests passed**, including 57 experimental-rule tests, 33 replay-driver tests, 33 evaluator tests, and the existing 237-test suite. Checks cover original-span reconstruction, unchanged production behavior, exact separate-channel handling, finalized-only input, token arithmetic, cache-miss network blocking, protected local exports, and explicit semantic counterexamples. Existing aiohttp application-key recommendations remain warnings. Passing tests do not certify semantic equivalence.

From `linux-audio-helper/`, with the existing local model, optional tokenizer dependency, and vocabulary caches prepared:

```bash
# Explicit local PCM16 WAVs and zero-based channels are named in a manifest.
.venv/bin/python scripts/transcribe_eval_audio.py \
  --manifest tmp/real-call-evaluation-2026-09-23/manifest.json \
  --output tmp/real-call-evaluation-2026-09-23/transcripts-new.json

.venv/bin/python scripts/evaluate_real_call.py \
  tmp/real-call-evaluation-2026-09-23/transcripts-new.json \
  --output-dir tmp/real-call-evaluation-2026-09-23/evaluation-new \
  --tokenizers cl100k_base o200k_base --iterations 200 --warmup 20 --markdown

.venv/bin/python -m pytest -q
```

Existing outputs are not overwritten. A manifest contains `corpus_id`, `provenance`, and `recordings`; each recording supplies `recording_id`, `audio_path`, and an explicit zero-based `channel`, optionally an excerpt start/duration. The replay output adds finalized segments and engine timings. The evaluator reads only that JSON, not descriptive audio paths, and refuses uncached tokenizer downloads.

Saved comparison files:

- [Spreadsheet-friendly aggregate metrics](caveman-real-call-metrics.csv): every variant, encoding, guard mode, and token-counting scope, plus timings.
- [Detailed aggregate JSON](caveman-real-call-summary.json): complete numerical results, methods, provenance, and per-side breakdowns, without full transcripts.
- Full raw/compact text, exact edit spans, per-segment JSON/CSV, and a side-by-side Markdown audit remain under the ignored local directory `linux-audio-helper/tmp/real-call-evaluation-2026-09-23/evaluation/`.

Audio and full transcripts are **not included in the shareable report or Git**. LDC marks the material copyrighted and links a restricted agreement; public sample access is not treated as an open redistribution or commercial-demo license. [LDC agreement](https://catalog.ldc.upenn.edu/license/ldc-non-members-agreement.pdf).

## 12. Next decision

For a customer-ready choice, evaluate consented, representative sales recordings on a held-out set with an explicit checklist: prices, deadlines, negation, conditions, competitor/entity names, buyer intent, and who owes what to whom. Test downstream answers against that checklist, not merely text length or surviving keywords.

On the evidence available now: **retain raw/default-off; preserve the existing minimal option; keep both telegraphic modes experimental.** The bottleneck for stronger cavemaning is meaning preservation, not the measured cost of these local passes.
