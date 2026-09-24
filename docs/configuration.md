# Configuration reference (`residents.json`)

```json
{
  "server":   { "port": 9700, "token": "" },
  "policies": { "...": "see table below" },
  "residents": {
    "llm":   { "...": "one entry per AI service on this card" }
  }
}
```

Resident names: `[a-z0-9_-]` — they become the verbs
(`gpumaid wake llm`).

**Registration without hand-editing:** `gpumaid register <name> --port …
--start … [--icon 🎤] [--vram-gb 4]` adds a resident over HTTP; it lands as
a `residents.d/<name>.json` drop-in next to the config (merged on top of
`residents.json`, later files win) and survives restarts. Remove with
`gpumaid unregister <name>` — static residents.json entries are never
deleted by the maid.

## `server`

| field  | default | meaning                                             |
| ------ | ------- | --------------------------------------------------- |
| `port` | `9700`  | HTTP port the agent binds on `0.0.0.0`              |
| `token`| `""`    | when set, POSTs require `Authorization: Bearer <t>` |

An empty `token` prints a warning at startup — acceptable on a home LAN,
set one before exposing the agent beyond it. GET endpoints are read-only
and always open.

## `policies` (defaults shown)

| field               | default | meaning                                                |
| ------------------- | ------- | ------------------------------------------------------ |
| `check_interval_s`  | `30`    | watchdog cadence                                       |
| `fails_to_revive`   | `3`     | consecutive dead probes before a watchdog revive       |
| `revive_cooldown_s` | `300`   | per-resident cooldown — no crash-loop machine-gunning  |
| `ensure_timeout_s`  | `90`    | how long `ensure` blocks waiting for a cold start      |
| `settle_timeout_s`  | `120`   | max wait for VRAM to settle during make-room           |
| `settle_poll_s`     | `3`     | settle poll cadence                                    |
| `baseline_gb`       | `0.5`   | assumed overhead (CUDA contexts, always_on residents)  |

## Resident fields

| field            | protocols            | meaning                                                     |
| ---------------- | -------------------- | ----------------------------------------------------------- |
| `desc`           | all                  | free text, shown in `gpumaid list`                          |
| `icon`           | all                  | emoji for desktop panels (menu bar / tray), e.g. `"🎨"`     |
| `protocol`       | all                  | `process` / `cooperative` / `always_on` (default `process`) |
| `port`           | all                  | TCP probe target (used when `probe` is absent)              |
| `probe`          | all                  | HTTP URL; a 200 response = alive                            |
| `start`          | process, cooperative | shell command to start the resident                         |
| `stop`           | process              | optional dedicated stop command (preferred over `kill_pat`) |
| `kill_pat`       | process              | regex matched against process command lines to stop it      |
| `sleep_url`      | cooperative          | POST endpoint that unloads models (required)                |
| `sleep_body`     | cooperative          | optional JSON body for `sleep_url`                          |
| `vram_gb`        | all                  | claimed VRAM budget — drives the make-room planner          |
| `wanted_default` | all                  | watchdog keepalive by default? (default `true`)             |
| `idle_suspend`   | process              | idle seconds after which the resident is auto-suspended     |

## The three protocols

- **`process`** — bare model servers. *Sleep* = run `stop` (or kill by
  `kill_pat`); *wake* = run `start`. The resident is all-or-nothing.
- **`cooperative`** — long-lived apps that can unload their own weights:
  *sleep* = POST to `sleep_url` (e.g. ComfyUI's `/free` with
  `{"unload_models": true, "free_memory": true}`). The process, its queue and
  its UI survive; only the weights leave VRAM. Cold-start-free for everyone.
- **`always_on`** — baseline infrastructure (desktop widgets, drivers). Never
  evicted, never woken — the maid counts it as background tax.

## How make-room works

`gpumaid wake <resident>` (and `ensure`) checks **measured** free VRAM
(`nvidia-smi` free memory) against the resident's claimed `vram_gb` plus
`baseline_gb`. If the card is short:

1. eviction candidates = alive residents that are not `always_on` and not the
   target, evicted largest-claimed-first, politely (their protocol's sleep);
2. the agent then polls real free VRAM until it settles;
3. if it never settles within `settle_timeout_s`, the wake **fails loudly** —
   no silent RAM spillover, no 3x slowdowns.

Residents suspended by an eviction stay suspended — waking them again later
is one `gpumaid wake` away; that is the deal.

## Master switch

- `gpumaid master off` — everyone sleeps, all wakes are refused, state is
  persisted. The GPU belongs to the owner (games, drivers, benchmarks).
- `gpumaid master on` — on-demand mode: nothing preloads; each resident
  wakes when someone asks for it, then joins the keepalive roster.

## Idle suspension

Residents whose traffic never flows through the agent (a TTS server called
directly, say) can declare `idle_suspend`. Anyone may renew the timer with
`gpumaid touch <resident>` after a successful interaction — the resident
stays up while it is being used and returns its VRAM when it is not.
