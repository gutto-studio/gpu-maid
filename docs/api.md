# HTTP API

Base: `http://<gpu-box>:9700` (configured in `residents.json` → `server.port`).

**Auth**: GETs are read-only and open. If `server.token` is set, every POST
requires `Authorization: Bearer <token>`; otherwise POSTs are open — keep the
agent on your LAN or tailnet.

The CLI (`gpumaid`) is a thin wrapper over this API; anything an agent or a
script can call the endpoints directly.

## GET /health

```json
{ "ok": true, "residents": 3, "master_off": false }
```

## GET /list

```json
{
  "residents": {
    "llm":   { "alive": true,  "suspended": false, "wanted": true,
               "protocol": "process",     "vram_gb": 5, "desc": "..." },
    "image": { "alive": false, "suspended": true,  "wanted": true,
               "protocol": "cooperative", "vram_gb": 8, "desc": "..." }
  },
  "_master_off": false,
  "vram": { "free_gb": 9.1, "total_gb": 12.0 }
}
```

## POST /wake/{name}

Ask for the room: evicts (per protocol) if VRAM is short, waits for measured
settle, starts the resident, stamps the keepalive roster.

- `200 {"ok": true, "msg": "waking" | "already up"}` — ready or on its way
- `409 {"ok": false, "msg": "..."}` — refused: master off, VRAM never
  settled, or unknown resident

## POST /ensure/{name}

Wake if needed and **block** until the probe passes (bounded by
`policies.ensure_timeout_s`). This is the "I am about to send this resident a
job" call.

## POST /sleep/{name}

Put a resident to sleep per its protocol. `200` on success, `409` when there
is no way to sleep it (or unknown resident).

## POST /touch/{name}

Renew a resident's idle timer — call it after a successful interaction with
a resident whose traffic bypasses the agent. `200` always (if resident exists).

## POST /master/on · /master/off

Whole-household switch, persisted across reboots.

- `off` — every resident sleeps (per protocol), all wakes are refused.
- `on` — on-demand mode: the keepalive roster is cleared; residents wake
  when asked and are kept alive from then on.

## Errors

`401` bad token · `404` unknown route · `500` the maid tripped (check the
agent log); refusals (master off, VRAM short, unknown resident) are `409`
with a human-readable `msg`.
