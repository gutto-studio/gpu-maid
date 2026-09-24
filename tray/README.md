# Windows system tray

`gpu-maid-tray.ps1` puts the maid in the Windows notification area — zero
dependencies, just PowerShell (built into every Windows 10/11).

The tray dot tells the story at a glance:

| color  | meaning                                  |
| ------ | ---------------------------------------- |
| green  | > 2 GB VRAM free                         |
| orange | > 0.5 GB free                            |
| red    | nearly full                              |
| purple | master switch is off (GPU is yours)      |
| gray   | agent unreachable                        |

Right-click: each resident (click to wake/sleep it), the master switch, exit.
The tooltip shows live memory / utilization / temperature. POSTs run in the
background so the menu never freezes while the maid makes room.

## Run it

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File gpu-maid-tray.ps1
```

Options: `-Url http://127.0.0.1:9700` (agent address), `-IntervalSec 5`
(refresh rate). `-SelfTest` prints one status snapshot and exits — useful
over SSH or for smoke tests.

## Autostart at login

Create a shortcut in `shell:startup` (Win+R → `shell:startup`) with target:

```text
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\path\to\gpu-maid-tray.ps1"
```

or via a scheduled task (same command, `/SC ONLOGON`).
