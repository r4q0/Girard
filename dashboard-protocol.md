# Dashboard protocol v1 (agent service to Lovable dashboard)

How Bilal's agent service talks to the Lovable dashboard. The dashboard implements this in `src/lib/girard/protocol.ts` and `PROTOCOL.md` in the Lovable project. Keep all three in sync.

```
Josef's speech helper (Linux, 127.0.0.1:8766, HTTP + SSE)
        |  transcript / state / metrics events
        v
Agent service (Bilal, Python)  -- Nebius Token Factory, Tavily
        |  one WebSocket, JSON text frames
        v
Dashboard (Lovable, browser)
```

- The browser cannot call the speech helper directly. The helper rejects any cross-origin request (Host and Origin checks, no CORS). All traffic goes through the agent service.
- Default dashboard URL for the agent: `ws://localhost:8000/ws`. It can be changed in the dashboard settings or with `?agent=ws://host:port/ws`.
- Every message is a JSON object with a `type`. The dashboard ignores unknown types and unknown fields.
- The speech helper only captures call playback (the customer). The rep's microphone is never captured, so transcript lines are customer-only unless `speaker` says otherwise.

## Agent to dashboard

| type | When | Notes |
| --- | --- | --- |
| `hello` | On connect | Agent name, models, playbook name. |
| `devices` | On connect, after `refresh_devices` | Forward helper `GET /api/devices` unchanged. |
| `state` | On every session state change | Values match the helper: `idle`, `loading`, `listening`, `stopping`, `error`. A new `session_id` resets the dashboard. |
| `audio` | About 5 per second | From helper `metrics` events. Drives the level meter and timer. |
| `transcript` | Every helper transcript event | Forward unchanged, add `speaker`. Dashboard upserts by `(session_id, segment_id)`. |
| `card` | Fast lane found a card | Display-ready. See below. |
| `research` | Research lane start and finish | Upsert by `research_id`. |
| `precall` | Reply to `precall` | `searching` first, then `done` or `failed`. |
| `summary` | Slow lane, every 30 to 45 s | Replaces the previous summary. |
| `metrics` | After every model call | Cumulative tokens, cost, latency percentiles. |
| `sentiment` | Optional (stretch) | `value` from -1 to 1. |
| `debrief` | After `stop` | `writing`, then `done` with content. |
| `notice` | Warnings and errors | Shown as a toast. |

```json
{"type":"hello","protocol":1,"agent":"girard-agent 0.1.0","models":{"fast":"Qwen/Qwen3-30B-A3B-Instruct-2507","slow":"slow-lane-model"},"playbook":{"name":"Demo salesbook","entries":32}}

{"type":"devices","outputs":[{"id":"alsa_output.pci-0000_00_1f.3.analog-stereo","name":"Built-in Audio Analog Stereo","monitor":"alsa_output.pci-0000_00_1f.3.analog-stereo.monitor","sample_rate":48000,"is_default":true}],"streams":[{"id":42,"name":"Playback","application":"Google Chrome","sink_id":"alsa_output.pci-0000_00_1f.3.analog-stereo"}]}

{"type":"state","session_id":"3f9c2a","state":"listening","started_at":1790150000000,"error":null}

{"type":"audio","level":0.031,"elapsed_seconds":84.2,"queue_ms":12.4,"processing_ms":2.1}

{"type":"transcript","session_id":"3f9c2a","segment_id":"7","start_ms":99000,"end_ms":103000,"text":"I'd have to run that past our CFO first.","is_final":true,"speaker":"customer"}
```

### card

```json
{"type":"card","card_id":"c_0007","playbook_id":"risk_cfo_01","kind":"risk","title":"CFO has to approve","say":["What would your CFO want to see…","Would it help if I joined that conversation…"],"proof":"Deals close faster when the CFO joins a call.","q":null,"trigger":{"segment_id":"7","text":"I'd have to run that past our CFO first."},"latency_ms":{"stt":210,"trigger":480,"ttft":162,"total":1010},"created_at":1790150104100}
```

- The agent sends cards ready to display. With the `CLAUDEcontext.md` §4.4 schema (`{"id","say","q"}`), the agent looks up `title` and `proof` in the playbook entry for `id`, and `kind` is the id prefix (`obj`, `ans`, `comp`, `sig`, `risk`). The model never generates them.
- A model result of `{"id":null}` sends nothing.
- Drop cards that would arrive more than 4 s after their trigger line.
- `trigger.segment_id` lets the dashboard mark the transcript line that caused the card.

### research, precall, summary

```json
{"type":"research","research_id":"r_pipedrive","entity":"Pipedrive","status":"searching","origin":"live"}
{"type":"research","research_id":"r_pipedrive","entity":"Pipedrive","status":"done","origin":"live","bullets":["Sales CRM built around deal pipelines.","No built-in invoice matching found."],"sources":[{"title":"pipedrive.com","url":"https://www.pipedrive.com"}],"took_ms":3400}

{"type":"precall","status":"done","company":"Van Dijk Logistics","website":"https://vandijk-logistics.example","summary":"Mid-size logistics firm.","bullets":["Runs Exact Online for accounting."],"likely_competitors":["HubSpot","Pipedrive"],"sources":[{"title":"vandijk-logistics.example","url":"https://vandijk-logistics.example"}]}

{"type":"summary","text":"Van Dijk Logistics. Ops manager. Manual invoice matching ~20 h/wk. Quoted EUR 400/mo. CFO decides, not on call.","stage":"Negotiation","ask_next":["What would the CFO need to see?"],"risks":["Over budget","Decision maker not on call"],"next_step":"Book 20 min with the CFO","updated_at":1790150110000}
```

`research.status`: `searching`, `done`, `failed`. `research.origin`: `live`, `cache`, `pre_call`.

### metrics, sentiment, debrief, notice

```json
{"type":"metrics","tokens":{"input":48210,"cached":45100,"output":412},"cost_eur":0.0071,"calls":{"fast":14,"slow":3,"research":1},"cache_hit_rate":0.93,"latency_ms":{"stt":{"last":210,"p50":190,"p95":340,"p99":420},"trigger":{"last":480,"p50":470,"p95":560,"p99":600},"ttft":{"last":162,"p50":157,"p95":320,"p99":1100},"total":{"last":1010,"p50":930,"p95":1480,"p99":2300}}}

{"type":"sentiment","value":-0.3,"label":"Hesitant"}

{"type":"debrief","status":"writing"}
{"type":"debrief","status":"done","summary":"...","went_well":["..."],"improve":["..."],"needs":["..."],"objections":[{"objection":"...","handled":"...","status":"open"}],"competitors":["..."],"next_steps":["..."],"email":{"subject":"...","body":"..."}}

{"type":"notice","level":"warning","message":"Speech backlog exceeded 1.5 s. Capture stopped."}
```

`metrics` is cumulative per session. The dashboard computes EUR per hour itself. Latency stages: `stt` (speech end to final text), `trigger` (silence wait and decision), `ttft` (model time to first token), `total` (customer stops speaking to card on screen).

## Dashboard to agent

```json
{"type":"refresh_devices"}
{"type":"precall","company":"Van Dijk Logistics","website":"vandijk-logistics.example","contact":"Sanne de Vries, operations manager","goal":"Book a call with the CFO"}
{"type":"start","sink_id":"alsa_output.pci-0000_00_1f.3.analog-stereo","isolate":false,"stream_id":null,"prospect":{"company":"Van Dijk Logistics","website":"vandijk-logistics.example","contact":"Sanne de Vries, operations manager","goal":"Book a call with the CFO"}}
{"type":"stop"}
{"type":"feedback","card_id":"c_0007","useful":true}
{"type":"dismiss","card_id":"c_0007"}
```

## Mapping to Josef's speech helper

| Dashboard command or event | Speech helper call |
| --- | --- |
| `refresh_devices` -> `devices` | `GET /api/devices` |
| `start` | `POST /api/start` with `{"sink_id","engine":"local","isolate","stream_id"}` (only include `stream_id` when `isolate` is true), then consume `GET /api/events` (SSE) |
| helper SSE `transcript` -> `transcript` | Forward as is and add `"speaker":"customer"`. Feed final segments into the trigger logic. |
| helper SSE `state` -> `state` | Forward `state`, `session_id`, `error`. |
| helper SSE `metrics` -> `audio` | Forward `level`, `elapsed_seconds`, `queue_ms`, `processing_ms`. |
| helper SSE `error` / `warning` -> `notice` | |
| `stop` | `POST /api/stop`, poll `GET /api/state` until `idle`, fetch `GET /api/transcript` for the debrief. |

Helper rules to respect: every POST needs `X-Call-Audio: 1` and `Content-Type: application/json`. Upsert transcript by `(session_id, segment_id)`. Closing the SSE stream does not stop capture. Starting a new session wipes the previous transcript, so save it first. The helper only runs on Linux (PipeWire or PulseAudio).
