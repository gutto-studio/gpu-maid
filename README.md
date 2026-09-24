# gpu-maid

English · [简体中文](README.zh-CN.md)

![license](https://img.shields.io/badge/license-Apache--2.0-blue)
![status](https://img.shields.io/badge/status-v0.1%20WIP-orange)
![agent](https://img.shields.io/badge/agent-Windows--native-informational)
![client](https://img.shields.io/badge/client-macOS%20%2F%20any%20HTTP-informational)

**Your GPU's maid — she tucks resident models in when another line needs the bed.**

<p align="center">
  <img src="docs/maid-hero.jpg" alt="the gpu-maid mascot: a pink-eared maid enjoying a cup of coffee in a warm cafe" width="560">
  <br><sub><i>the maid herself, on a coffee break between jobs — art from the author's own paint line</i></sub>
</p>

`gpu-maid` is a small butler for a common household: one consumer GPU (say, a Windows
gaming PC) serving several AI residents at once — an LLM, a TTS voice, an image line,
a video line — while you drive everything from your Mac.

Remote inference itself is a commodity: Ollama exposes a remote host, ComfyUI exposes
an API, Tailscale stitches them together. What's missing is the layer that decides
**who runs, who sleeps, and who gets woken**. That's the maid's job.

## The problem

One card, several tenants — and today the scheduler is **you**:

- **VRAM tug-of-war** — two services load at once and you get OOM errors, or worse,
  silent spillover into system RAM and a 3x slowdown nobody can explain.
- **Human scheduler fatigue** — every line switch is manual: quit Ollama, stop the
  voice server, stare at `nvidia-smi`, start the video service, wait for the weights.
  Five to ten minutes of babysitting per switch.
- **Silent deaths** — long-running model servers die quietly (CUDA errors,
  antivirus, crashes) and you find out when a job fails mysteriously.
- **No service layer over the network** — Tailscale gets you connectivity; it doesn't
  decide who should sleep so someone else can work.
- **No clean way home** — when you want the GPU back for games, the AI household
  must be hunted down process by process.

gpu-maid is the butler that takes that job from you.

## How a job flows

<p align="center">
  <img src="docs/architecture.svg" alt="gpu-maid architecture: a Mac client talks to the gpu-maid agent on the Windows GPU box, which arbitrates VRAM between resident services (LLM, TTS, image, video)" width="820">
</p>

1. You ask the agent for a job that needs **8 GB free** VRAM.
2. The maid checks the resident registry: the image line is running, everyone else is asleep.
3. She politely asks the image line to sleep, and waits for VRAM to settle.
4. She wakes the target — with a cooldown, so nothing gets double-started while models load.
5. The watchdog keeps watch; anything that dies silently gets brought back.
6. Done? The house returns to its resting posture — or you flip the master switch and
   the whole household rests.

## The daily loop (target UX)

Install once — the agent on the Windows box with a residents file, the CLI on your
Mac pointed at it:

```bash
$ pip install gpu-maid            # both sides (v0.1)
$ gpu-maid connect 192.168.1.20   # point the CLI at the maid — one time
```

After that the whole day is three sentences:

```bash
$ gpu-maid list                   # who's awake, who's asleep, VRAM headroom
$ gpu-maid wake video             # ask for the room: maid clears, settles, wakes
# …then use ComfyUI / Ollama's own API as usual — the maid doesn't get in the way
$ gpu-maid master off             # done for today — the whole household rests
```

The watchdog needs no instruction at all; it's on duty whether you look or not.

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
| `agent/`  | Windows (native, no WSL2/Docker) | HTTP API · resident registry · VRAM gate + queue · wake/cooldown · watchdog · master switch · GPU util/temp telemetry |
| `cli/`    | macOS or any box                 | thin client: `connect / list / wake / sleep / touch / master on/off`           |
| transport | LAN / Tailscale                  | boring on purpose                                                              |

## Docs

- [Install & run](docs/install.md)
- [Configuration reference](docs/configuration.md)
- [HTTP API](docs/api.md)

## Teach your agent (SKILL.md)

In 2026 a large share of GPU-box operators are agents. Ship them the house rules:

```bash
# clone this repo, then hand the skill to your runtime's skills directory
cp -r skills/gpu-maid ~/.claude/skills/    # Claude Code / ZCode / SKILL.md-aware runtimes
```

The skill teaches the loop (`list → wake → native API → sleep`) and, more
importantly, the house rules: an agent must never kill resident processes behind
the maid's back, and must not flip the master switch unless the human asked.

## When you don't need it

- One AI service on the card — no contention, no problem to solve.
- Linux boxes as workers — GPUStack and friends already serve that world.
- Cloud-only workflows — there's no card at home to mind.

## Status

🚧 **v0.1 under active development.** agent, CLI, example config and docs have
landed — logic-tested (12 unit tests) and smoke-tested end to end; real-GPU
validation and packaging are next. Extracted from a setup that runs these exact
patterns in daily production (TTS + image + video + LLM sharing one consumer GPU).

## Roadmap

- [x] `agent/` — resident registry, VRAM make-room gate, revive watchdog,
      master switch, idle suspension (stdlib-only, single file)
- [x] `cli/` — thin client: `connect / list / wake / sleep / touch / master`
- [x] `skills/gpu-maid/SKILL.md` — teach agents the loop and the house rules
- [x] `examples/` + docs: [install](docs/install.md) ·
      [configuration reference](docs/configuration.md) · [HTTP API](docs/api.md)
- [ ] Real-GPU validation pass on a live Windows box
- [ ] Demo GIF · `pip install gpu-maid` packaging · v0.1 launch

## Scope & support

Built and battle-tested on one NVIDIA setup (Windows gaming PC, with a Chinese AV
suite present) in daily production use. Other GPUs, drivers and environments are
untested — everything ships **as-is**; issues welcome, patches welcome faster.

## License

[Apache-2.0](LICENSE)
