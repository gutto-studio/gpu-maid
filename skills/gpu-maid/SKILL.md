---
name: gpu-maid
description: Arbitrate VRAM between AI residents (LLM/TTS/image/video) on the household GPU box before running local AI jobs. Use when submitting work to Ollama, ComfyUI or other local model servers behind gpu-maid, when jobs fail with OOM or unexplained slowness, or when the human asks for the GPU back.
---

# gpu-maid

One consumer GPU, several AI residents. The maid decides who runs, who sleeps,
who gets woken. You talk to her through the `gpu-maid` CLI — never around her.

## When to use

- Before submitting a job to any resident behind gpu-maid (Ollama, ComfyUI,
  a TTS server, a video line).
- When a job fails with OOM or runs suspiciously slow — suspect VRAM contention.
- When the human says they want the GPU back (games, drivers, benchmarks).

## The loop

```bash
gpu-maid list                 # residents, their state, VRAM headroom
gpu-maid ensure <resident>    # wake if needed and block until ready —
                              # call this right before sending the job
# ...do the job via the resident's OWN API (ComfyUI /prompt, Ollama /api/generate).
#   The maid doesn't proxy jobs; she only guarantees the room is ready.
gpu-maid sleep <resident>     # optional: tidy up when you're done
```

`ensure` exits 0 when the resident is ready. If it fails, stop and report —
see House rules.

## House rules (important)

1. **Never kill or start resident processes yourself.** That is exactly the war
   this tool exists to end. Bypassing the maid reintroduces it.
2. **`gpu-maid master off` is rude unless the human asked for the GPU back.**
   It evicts the entire household. `wake` is cheap; `master off` is not.
3. **`always_on` residents are baseline.** Never evict them, never suggest it.
4. **If VRAM never settles after a wake, stop and report** to the human with the
   `gpu-maid list` output attached. Do not escalate to process kills on your own.

## Status

v0.1 — the verbs above are the target UX. See the repository README for what
ships when.
