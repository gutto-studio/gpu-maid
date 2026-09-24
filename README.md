# gpu-maid

![license](https://img.shields.io/badge/license-Apache--2.0-blue)
![status](https://img.shields.io/badge/status-v0.1%20WIP-orange)
![agent](https://img.shields.io/badge/agent-Windows--native-informational)
![client](https://img.shields.io/badge/client-macOS%20%2F%20any%20HTTP-informational)

**Your GPU's maid — she tucks resident models in when another line needs the bed.**

<p align="center">
  <img src="docs/architecture.svg" alt="gpu-maid architecture: a Mac client talks to the gpu-maid agent on the Windows GPU box, which arbitrates VRAM between resident services (LLM, TTS, image, video)" width="820">
</p>

`gpu-maid` is a small butler for a common household: one consumer GPU (say, a Windows
gaming PC) serving several AI residents at once — an LLM, a TTS voice, an image line,
a video line — while you drive everything from your Mac.

Remote inference itself is a commodity: Ollama exposes a remote host, ComfyUI exposes
an API, Tailscale stitches them together. What's missing is the layer that decides
**who runs, who sleeps, and who gets woken**. That's the maid's job.

## How a job flows

1. You ask the agent for a job that needs **8 GB free** VRAM.
2. The maid checks the resident registry: the image line is running, everyone else is asleep.
3. She politely asks the image line to sleep, and waits for VRAM to settle.
4. She wakes the target — with a cooldown, so nothing gets double-started while models load.
5. The watchdog keeps watch; anything that dies silently gets brought back.
6. Done? The house returns to its resting posture — or you flip the master switch and
   the whole household rests.

## Playing nice with self-orchestrating residents

ComfyUI juggles its own models between steps; Ollama has `keep_alive`; modern
runtimes manage memory inside their own walls. That is **their** job — gpu-maid
deliberately does not compete with it. The line is drawn like this:

- **Inside a resident** (which model is loaded, when to offload) — the resident rules.
- **Between residents** (who may still hold VRAM when someone else needs it) — the maid rules.

Three obedience classes in the registry make the coexistence explicit:

| protocol      | sleep means                        | example                                        |
| ------------- | ---------------------------------- | ---------------------------------------------- |
| `cooperative` | call its unload API; process stays | ComfyUI (`POST /free`), Ollama (`keep_alive: 0`) |
| `process`     | stop the process; wake = start cmd | bare model servers                             |
| `always_on`   | never evicted — counted as baseline | desktop widgets, drivers                      |

The gate is closed-loop: decisions are made on **measured** free VRAM (nvidia-smi),
never on promises. If the card hasn't settled after a polite eviction, the maid
escalates up the ladder the resident allows (unload API → process stop).

Residents keep their own queues, too: whatever you submit straight to ComfyUI's
own UI is ComfyUI's business. The maid only steps in when someone asks her for VRAM.

## A taste of the config

> Shape preview — the v0.1 schema is still settling.

```yaml
residents:
  llm:
    protocol: cooperative            # sleep = unload API (keep_alive: 0); process stays
    vram_gb: 5
  image:
    protocol: cooperative            # sleep = POST /free — ComfyUI keeps queue & UI
    endpoint: http://127.0.0.1:8188
    vram_gb: 8
  voice:
    protocol: process                # sleep = stop process; wake = start command
    vram_gb: 4
policies:
  baseline_gb: 1                     # CUDA contexts & always_on tenants
  vram_free_need_gb: 8               # a job gates on this before waking anyone
  load_cooldown_s: 90                # models still loading may not be re-poked
  settle_timeout_s: 120              # not settled? escalate per protocol ladder
```

## Components

| Piece     | Runs on                          | Does                                                                          |
| --------- | -------------------------------- | ----------------------------------------------------------------------------- |
| `agent/`  | Windows (native, no WSL2/Docker) | HTTP API · resident registry · VRAM gate · wake/cooldown · watchdog · master switch |
| `cli/`    | macOS or any box                 | thin client: `list / wake / run / sleep / master on/off`                       |
| transport | LAN / Tailscale                  | boring on purpose                                                              |

## Status

🚧 **v0.1 under active development.** Scope and architecture are set; the agent is
being extracted and generalized from a setup that runs these exact patterns in daily
production (TTS + image + video + LLM sharing one consumer GPU).

## Roadmap

- [ ] `agent/` — Windows-side daemon: resident registry, VRAM gate, wake/vacate with
      load cooldown, watchdog with auto-revive, master switch, HTTP API
- [ ] `cli/` — thin client: `list / wake / run / sleep / master on/off`
- [ ] `examples/` — resident configs for an LLM, a TTS voice and an image line
- [ ] Docs: install & configuration guide

## Scope & support

Built and battle-tested on one NVIDIA setup (Windows gaming PC, with a Chinese AV
suite present) in daily production use. Other GPUs, drivers and environments are
untested — everything ships **as-is**; issues welcome, patches welcome faster.

## License

[Apache-2.0](LICENSE)
