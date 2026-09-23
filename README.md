# gpu-maid

**Your GPU's maid — she tucks resident models in when another line needs the bed.**

`gpu-maid` is a small butler for a common household: one consumer GPU (say, a Windows
gaming PC) serving several AI residents at once — an LLM, a TTS voice, an image line,
a video line — while you drive everything from your Mac.

Remote inference itself is a commodity: Ollama exposes a remote host, ComfyUI exposes
an API, Tailscale stitches them together. What's missing is the layer that decides
**who runs, who sleeps, and who gets woken**. That's the maid's job:

- **Resident registry** — declare your model services once, in one config
- **VRAM gate** — a job that needs 8 GB asks the maid; she politely sends the current
  residents to sleep first, instead of letting them fight to the death (and into swap)
- **Wake & cooldown** — on-demand wake with a load-window guard, so nothing gets
  double-started while a model is still loading
- **Watchdog** — residents that die silently get noticed and brought back
- **Master switch** — one call to hang up the whole house when you just want your GPU back

## How it works

```text
Mac / any client ──LAN or Tailscale──► gpu-maid agent (Windows) ──► residents
  thin CLI                              HTTP API · registry ·        (Ollama, TTS,
                                        VRAM gate · watchdog         ComfyUI, ...)
```

The agent runs natively on the Windows box — **no WSL2, no Docker Desktop, no Linux
server required**. The CLI is thin and boring on purpose.

## Status

🚧 **v0.1 under active development.** Scope and architecture are set; the agent is
being extracted and generalized from a setup that runs these exact patterns in daily
production (TTS + image + video + LLM sharing one consumer GPU).

## Roadmap

- [ ] `agent/` — Windows-side daemon: resident registry, VRAM gate, wake/vacate with
      load cooldown, watchdog with auto-revive, master switch, HTTP API
- [ ] `cli/` — thin client: `list / wake / run / sleep / master on|off`
- [ ] `examples/` — resident configs for an LLM, a TTS voice and an image line
- [ ] Docs: tested-environment statement (NVIDIA, with a Chinese AV suite in daily
      production use; other environments untested — everything ships as-is)

## License

[Apache-2.0](LICENSE)
