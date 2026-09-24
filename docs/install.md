# Install & run

## What you need

- **The GPU box**: Windows 10/11 with an NVIDIA GPU, Python 3.9+. The agent is
  stdlib-only — no dependencies to install.
- **Your daily machine** (macOS / Linux / Windows): Python 3.9+ for the CLI.

## 1. Get the code (both machines)

```bash
git clone https://github.com/jincheng211/gpu-maid
```

> Packaging (`pip install gpu-maid`) is planned for the v0.1 release; until
> then, run from source.

## 2. GPU box: describe your household

```bat
cd gpu-maid\agent
copy ..\examples\residents.example.json residents.json
:: edit residents.json — one entry per AI resident on this card
```

Every field is documented in the [configuration reference](configuration.md).
Start minimal: one or two residents you actually run. `vram_gb` is the
resident's *claimed* budget — measure with `nvidia-smi` under load and round up.

## 3. GPU box: start the maid

```bat
python -m gpumaid --config residents.json
```

Verify locally:

```bat
curl http://127.0.0.1:9700/health
```

### Autostart at login (optional)

```bat
schtasks /Create /TN gpumaid /SC ONLOGON ^
  /TR "cmd /c cd /d C:\path\to\gpu-maid\agent && python -m gpumaid --config C:\path\to\residents.json"
```

> **Antivirus note:** some AV suites silently kill processes spawned from
> remote-shell chains. Starting the agent through a scheduled task (as above)
> is the reliable posture — this lesson cost the author a full afternoon.

### Remote access (optional)

The agent binds `0.0.0.0`. For access beyond your LAN, install
[Tailscale](https://tailscale.com) on both machines and point the CLI at the
box's tailnet address. If you expose the agent beyond localhost/LAN, set
`server.token` in `residents.json` (see [HTTP API](api.md)).

## 4. Daily machine: the CLI

```bash
alias gpumaid="python3 /path/to/gpu-maid/cli/gpumaid.py"
gpumaid connect 192.168.1.20:9700     # saved to ~/.gpumaid/config.json
gpumaid list
```

## 5. Smoke test

```bash
gpumaid wake <your-lightest-resident>   # it should come up
gpumaid list                            # state + VRAM headroom
gpumaid master off                      # everyone rests — GPU is yours again
gpumaid master on                       # back to on-demand mode
```

State lives in `gpumaid_state.json` next to your config: the master switch,
the keepalive roster and suspend marks all survive reboots. Nothing
resurrects behind your back.
