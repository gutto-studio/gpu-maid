# macOS menu bar (SwiftBar)

The maid in your menu bar: live GPU memory / utilization / temperature,
the resident roster with one-click wake & sleep, the make-room queue,
per-process VRAM attribution and recent events.

Menu bar title: `GPU 9.1/12.0G · 3% · 42°C` (green / orange / red as free
VRAM shrinks; purple 💤 when the master switch is off).

## Install

```bash
brew install --cask swiftbar          # or download from https://swiftbar.app
mkdir -p ~/Library/Application\ Support/SwiftBar/Plugins
cp gpu-maid.5s.py ~/Library/Application\ Support/SwiftBar/Plugins/
chmod +x ~/Library/Application\ Support/SwiftBar/Plugins/gpu-maid.5s.py
```

Open SwiftBar once and point it at that plugin folder (it usually finds it
by itself when installed via brew).

## Configure

The plugin reads the same settings as the CLI:

- `GPUMAID_URL` — agent address, or the `~/.gpumaid/config.json` written by
  `gpumaid connect HOST:PORT` (either works).
- `GPUMAID_TOKEN` — sent as `Authorization: Bearer …` if your agent has
  `server.token` set. Set it with `launchctl setenv GPUMAID_TOKEN …` so
  menu-bar children inherit it, then log out/in once.

## Behavior notes

- The `.5s` filename suffix = refresh every 5 seconds (rename to `.10s.py`
  to poll less often).
- Wake/sleep actions call the agent's HTTP API directly with a 3-second
  client timeout — the maid keeps working server-side even if a cold start
  outlives it; the bar catches up on the next refresh.
- A dead agent shows `maid ✗` in red instead of beachballing the bar.
