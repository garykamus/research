# 01 — Architecture

> Components, engine behaviour, the durable-state model, the **decided stack**
> (Python + PySide6 + single exe), and the local-tool design rules.

---

## 1. Components

```
PySide6 desktop UI  ──in-process calls──►  Release Engine (core)  ──►  Config Store
   (thin presentation)   ReleaseService          │                     Credential Store
                                                 │                     Integration Clients
                                                 ▼
                                          SQLite (local file)
```

- **UI** — a **native PySide6 (Qt) desktop** app; thin presentation that renders the matrix
  and lane detail and calls the core's `ReleaseService` **in-process** (no HTTP). See §5–6,
  `04`.
- **Release Engine (core)** — UI-agnostic Python. Owns lanes, resolves workflows, runs/
  tracks steps, manages the value bag, advances waiting lanes, writes audit.
- **Config Store** — step library, backbone/templates, market bindings, tools. Config-as-
  file (version-controlled). See `03`.
- **Credential Store** — per-user credentials per tool (token / basic / form_login),
  encrypted at rest via the OS keystore. See `05` / §7 security note.
- **Integration Clients** — per-tool clients (Jenkins/GitHub/SNOW/Confluence/Jira/scan).
- **SQLite** — lane state, value bags, audit log. The single durable store (local file).

## 2. Engine responsibilities

1. **Lane lifecycle** — create a lane from `(market, arcad_package, owner, jira_id,
   confluence_page)` (where `arcad_package` may instead be produced by a creation step);
   resolve its concrete step list (see `03`); persist it.
2. **Step execution** — fire a step's trigger when eligible; capture produced values;
   record links; set status.
3. **Advancement** — when a step completes (auto-detected, manually marked, or
   overridden), determine the next eligible step. **Do not auto-advance past human
   gates** (HYBRID/approval steps) until the human confirms.
4. **Waiting-lane polling** — for lanes parked at an external gate (e.g. CR approval),
   periodically re-check the external system and advance when the gate clears. Poll only
   waiting lanes, not all lanes.
5. **Value bag management** — maintain a per-lane bag; validate that a step's `consumes`
   values exist before firing; resolve `{placeholders}` from lane attributes + bag.
6. **Override handling** — accept a manual override on any step; record who/when/why;
   recompute effective status.
7. **Audit** — every state change writes an immutable audit entry.

## 3. State model — persist the flow, live-check external truth

This is the single most important behavioural rule of the engine.

- **Persist what only the dashboard knows** — which lane is on which step, when it
  entered, its lane attributes, its value bag, and the full audit log. This orchestration
  state exists nowhere else and must be durable.
- **Live-check what the external system owns** — did the build pass (Jenkins)? is the CR
  approved (ServiceNow)? is the PR merged (GitHub)? **Never** treat a cached copy of these
  as the source of truth.

Mechanics:
- A **background worker** polls only *waiting* lanes, updates persisted state, advances
  when a gate clears.
- **Webhooks** are used where available (Jenkins, GitHub) for instant advancement;
  polling is the fallback for systems that cannot push (ServiceNow often cannot).
- An **on-demand "refresh"** in the UI forces an immediate live re-check for a lane.

```
PERSISTED (durable, our truth)        LIVE-CHECKED (external truth)
  lane → current step                   Jenkins: build result
  step status / effective status        ServiceNow: CR approval
  value bag (cr_no, pr_url, ...)         GitHub: PR merged
  lane attributes (jira_id, ...)         (never cached as truth)
  audit log
```

## 4. Idempotency & safety (required)

- **Idempotent triggers.** Re-running a step must not create duplicate PRs/CRs/builds.
  Each fired action carries an idempotency key derived from `(lane id, step id, attempt)`;
  before firing, check whether this action was already performed for this lane.
- **No double-fire across restarts.** Because state is durable (section 3), a restart
  mid-flight must resume without re-firing an already-fired trigger.
- **Lane-scoped isolation.** A value or credential for one lane must never be readable by
  another lane's execution.

## 5. Technology stack (DECIDED: Python + PySide6 + single exe)

This is a **local desktop tool**, packaged as a **single executable** for developer PCs.
Shared-on-prem-web is considered unlikely and is **not** a design driver (see §7). The
stack:

| Layer | Choice |
|---|---|
| UI | **PySide6** (Qt for Python) — a native desktop GUI, not a web frontend |
| Engine / triggers / integrations / config | Plain **Python**, as a UI-agnostic **core** library |
| Durable state | **SQLite** (embedded, file-based) via a data-access layer |
| Background worker | **In-process** (a background thread or **APScheduler**) — **not Celery** |
| Script triggers | Python, **in-process** (no subprocess bridge) |
| Browser automation | **Playwright (Python)** — see packaging caveat in `05`/`06` |
| Packaging | **PyInstaller** → one native exe; double-click to run |

### 5.1 Architecture: UI-agnostic core + thin PySide6 presentation
Even as a desktop app, keep the logic out of the GUI. The **core** (engine, triggers,
integrations, config, credentials, persistence) is plain Python that knows nothing about
PySide6. The **PySide6 layer is presentation only** — it renders state and calls a clean
`ReleaseService` interface (e.g. `create_lane`, `fire_step`, `override`, `rename_package`,
`resume_lane`, `refresh_status`). PySide6 calls this core **directly, in-process** (no HTTP).

```
┌─────────────────────────────────────────┐
│  PySide6 desktop UI (thin presentation)  │   matrix view, lane detail, dialogs
└───────────────────┬──────────────────────┘
                    │ calls ReleaseService (plain Python, in-process)
┌───────────────────▼──────────────────────┐
│  CORE (UI-agnostic Python)               │   engine · triggers · integrations ·
│                                          │   config · credentials · persistence
└───────────────────┬──────────────────────┘
                    │
              SQLite (local file)
```

This separation is the **one seam that matters**: it keeps the UI replaceable and the
logic testable, and it is the *only* thing that would make a future web/shared rebuild
tractable (wrap the same core in an API; rebuild only the presentation). We are **not**
building that now — but the core/UI split costs little and is good hygiene regardless.

### 5.2 Why these specific choices
- **In-process worker, not Celery:** Celery needs a separate broker (Redis/RabbitMQ) that
  cannot be bundled into a single exe. A background thread / APScheduler inside the app
  does the waiting-lane polling and advancement. Simpler and correct for a single-user
  local tool. Keep the worker *logic* in the core (not tangled into Qt callbacks) so it is
  testable.
- **SQLite:** zero-setup embedded DB, lives as a file next to the exe / in the user's app
  data dir. Accessed through a data-access layer so the rest of the core never embeds SQL
  assumptions.
- **In-process Python scripts:** `script` triggers with `runtime: python` are direct
  function calls — no subprocess, no marshalling. (Non-Python scripts, if ever needed, run
  as subprocesses — rare.)
- **PyInstaller:** bundles Python + PySide6 + the core into one native exe. PySide6/Qt is a
  well-trodden PyInstaller path. Playwright bundling is the one fiddly part (`05`/`06`).

## 6. UI delivery — PySide6 desktop

The UI is a **native Qt desktop application**, not a browser page. The approved screen
designs (matrix board, pipeline-aware lane detail, generic/custom step views — `04`) carry
over fully in *concept*; they are implemented as **Qt widgets** rather than HTML/React:
- **Matrix board** → a Qt table/tree view (rows = lanes; condensed progress bar per lane).
- **Lane detail** → an expandable list/tree of steps (expand-to-act inline).
- **Custom views** (CR creation, evidence update, Confluence release) → Qt dialogs/panels.
- **Status colours, badges, value-flow notes, lane-level actions** → Qt styling + widgets.

Agents should build **Qt-native** layouts that realize the approved design — not attempt to
embed web layouts in a web-view. (A `QWebEngineView` is explicitly *not* the approach; this
is a native widget app.)

## 7. Local-tool design rules (adapted from the four local→shared rules)

The decision is a **local desktop tool; shared-web is unlikely** and not a design driver.
The original "four local→shared rules" are therefore **relaxed to what still genuinely
benefits a local tool** — kept because they are good hygiene, not because a shared future
is being engineered for:

### Rule 1 — State in SQLite via a data-access layer (kept)
Never keep lane state in memory or ad-hoc files. Persist to SQLite through a data-access
layer. This is what makes restart-resume and the audit trail work — essential even locally.

### Rule 2 — Externalize configuration (kept, simplified)
Config (step library, templates, market bindings, tools) and the DB/secret locations are
read from config files / app-data paths, not hardcoded. One local profile; no `shared`
profile required.

### Rule 3 — Model actions as belonging to a user (kept)
Per-user credentials and attributable audit require a `user` concept even on a single-user
machine (the developer is a user; actions are attributed). Cheap, and it keeps the audit
honest.

### Rule 4 — Keep worker + core logic UI-agnostic (kept, reframed)
The poll/advance worker and all engine logic live in the **core**, not in Qt callbacks, so
they are testable and the UI stays thin. (This replaces the old "separable for shared"
rationale — now it's simply clean separation.)

### Dropped (no longer design drivers)
- A `shared` deployment profile, networked PostgreSQL, server-side secret store, dashboard
  SSO, and a standalone Celery worker are **out of scope**. If a shared web service is ever
  wanted, it is a deliberate future project: wrap the UI-agnostic core in an API and build a
  web UI — the core/engine/config/integrations are reused, the PySide6 presentation is not.

### Security note (sharper for a local exe)
The SQLite DB and per-user encrypted credentials live **on the developer's machine**,
inside or beside the exe. Passwords (`basic`/`form_login`) are the highest risk (`05` §3).
**Mandatory:** encrypt secrets using the OS keystore (e.g. Windows DPAPI / macOS Keychain),
**never** a key hardcoded in the exe (trivially extractable). Prefer tokens over passwords;
prefer Tier-3 manual (no stored password) for no-API tools. (Full guidance: `05` §3.)
