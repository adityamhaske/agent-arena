# HTTP API

The local JSON API behind `arena ui`, served by `agent_arena/web/server.py`.

**This API is unauthenticated by design.** It binds to loopback and drives your
filesystem and your API credit. Read
[../security/threat-model.md](../security/threat-model.md) before exposing it.

Base URL: `http://localhost:8420`.

## Conventions

- Requests and responses are JSON. Bodies must be a JSON **object**.
- Bodies over 8 MB are rejected with 413.
- A project `name` matches `[a-z0-9][a-z0-9_-]{0,63}`.
- Every response carries `Content-Security-Policy`, `X-Content-Type-Options:
  nosniff` and `Referrer-Policy: no-referrer`; API responses are `no-store`.
- A request whose `Host` header is not in the allow-list gets 403.

## Endpoints

| Method | Path | Does |
|---|---|---|
| GET | `/api/catalog` | Available models, scorers and wizard presets |
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Create a project |
| GET | `/api/projects/{name}` | Project detail, config and preflight |
| PUT | `/api/projects/{name}` | Update config |
| PUT | `/api/projects/{name}/tests` | Replace test cases |
| POST | `/api/projects/{name}/run` | Start a run; returns a job snapshot |
| GET | `/api/projects/{name}/history` | Past runs and model trends |
| GET | `/api/projects/{name}/result?run_id=` | A stored run (default: latest) |
| POST | `/api/projects/{name}/whatif` | Re-rank stored results under new weights |
| GET | `/api/jobs/{job_id}` | Job status |
| POST | `/api/jobs/{job_id}/cancel` | Stop a sweep that is spending money |
| DELETE | `/api/projects/{name}` | Delete a project — `?keep_results=&dry_run=` |
| POST | `/api/projects/{name}/duplicate` | Copy a project, excluding its results |
| POST | `/api/projects/{name}/archive` | Hide it from the default listing |
| GET | `/api/projects/{name}/runs` | Runs for a project — `?limit=&include_deleted=` |
| DELETE | `/api/projects/{name}/runs/{run_id}` | Delete a run — `?hard=&dry_run=` |
| POST | `/api/projects/{name}/runs/{run_id}/label` | Label a run |
| POST | `/api/projects/{name}/vacuum` | Permanently remove soft-deleted runs |
| GET | `/api/settings` | User settings |
| PUT | `/api/settings` | Update user settings |
| GET | `/api/projects/{name}/export` | Write a run to disk — `?run_id=&format=` |

`GET /api/projects` takes `?all=1` to include archived projects.

**`DELETE` takes its options from the query string**, not a body — a body on a
DELETE is not universally supported by clients and proxies. Every destructive
route accepts `dry_run=1` and returns the identical plan without changing
anything, so a confirmation dialog can show exactly what is about to happen.

## Errors

| Status | When |
|---|---|
| 400 | Bad request, or an `ArenaError` — carries `error` (plain) and `detail` (raw) |
| 403 | Host not allowed |
| 404 | No such endpoint, project or job |
| 413 | Body too large |
| 500 | Unexpected — carries `error` and `detail`, and the server stays up |

Error bodies always have an `error` string suitable for showing a user; `detail`
carries the technical text when there is one.

## Jobs

`POST /api/projects/{name}/run` starts a run in a thread and returns immediately.
Poll `GET /api/jobs/{job_id}`:

```json
{
  "id": "a1b2c3d4e5f6",
  "project": "support_triage",
  "status": "running",
  "completed": 42,
  "planned": 120,
  "fraction": 0.35,
  "elapsed_s": 18.4,
  "eta_s": 34.2,
  "skipped": {"opus_5": "ANTHROPIC_API_KEY is not set"},
  "recent": [{"model": "sim_small", "test": "t1", "status": "ok", "passed": true, "output": "billing"}],
  "run_id": null,
  "result": null,
  "cancel_requested": false
}
```

`status` is `starting`, `running`, `done`, `error` or `cancelled`. `recent` holds
the last 40 results. When `status` is `done`, `result` carries the full presented
leaderboard.

Starting a run for a project that already has one running returns the existing
job rather than starting a second — double-clicking Run must not spend twice.

At most 50 finished jobs are retained; a running job is never evicted.

## What-if

```http
POST /api/projects/support_triage/whatif
{"run_id": "run_20260902_162437_9b554f",
 "weights": {"accuracy": 0.7, "cost": 0.2, "latency": 0.1}}
```

Re-ranks from stored results — no model calls, no spend. It runs the real
`build_leaderboard`, so a what-if and a fresh run can never disagree.

## Cross-site requests

A state-changing request (anything but `GET`) carrying an `Origin` from another
site is refused with 403. The Host allow-list stops DNS rebinding but not a
plain cross-site form POST, which carries a legitimate Host header — this closes
that. Same-origin requests either omit `Origin` or send a matching one, and the
CLI sends none.

## Planned

Provider management over HTTP, cross-project run listing, and server-sent events
replacing polling. See [../roadmap/status.md](../roadmap/status.md).
