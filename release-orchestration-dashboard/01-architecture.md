# 01 — Architecture

> Components, engine behaviour, the durable-state model, the language options
> (Python and Java), and the **four mandatory local→shared rules**.

---

## 1. Components

```
UI  ──REST/WebSocket──►  Release Engine  ──►  Config Store
                              │                Credential Store
                              │                Integration Clients
                              ▼
                          Database
```

- **UI** — renders the matrix and lane detail from the engine's API. Decoupled from the
  backend language (talks over REST/WebSocket). See `04`.
- **Release Engine** — the core. Owns lanes, resolves workflows, runs/tracks steps,
  manages the value bag, advances waiting lanes, writes audit.
- **Config Store** — step library, backbone/templates, market bindings, tools, markets.
  May be config-as-file (version-controlled) or config-in-DB. See `03`.
- **Credential Store** — per-user credentials per tool (token / basic / form_login),
  encrypted at rest. See `05`.
- **Integration Clients** — per-tool clients (Jenkins/GitHub/SNOW/Confluence/Jira/scan).
- **Database** — lane state, value bags, audit log, and (optionally) config. The single
  durable store.

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

## 5. Language options

The spec is language-agnostic. Two supported backends; pick later. Both must satisfy
every requirement here and the four rules in section 7.

### 5.1 Java / Spring Boot

- **Durable workflow:** use an **embedded workflow engine** (Flowable or Camunda 7) as a
  library inside the Spring Boot app, running against the application database. It
  provides durable execution, human-task gates (map PR/CR approvals onto these), timers
  (for waiting-lane polling), and an audit trail.
- **Background work:** the engine's job executor / Spring scheduling runs the
  poll/advance loop in-process (promotable to a separate worker later — see rule 4).
- **Script triggers:** Java or Groovy scripts run **in-process**. A Python script trigger
  requires shelling out to a Python subprocess with a defined data contract (see `05`).
- **Packaging:** a single self-contained **executable JAR** (backend + UI assets +
  embedded web server + embedded DB for local). Cleanest single-artifact story.
- **Local/shared switch:** Spring **profiles** (`local` vs `shared`) select embedded DB
  vs networked PostgreSQL, local vs server-side secret store, etc.

### 5.2 Python

- **Durable workflow:** assembled from **FastAPI** (web/API) + **Celery** (background work
  & beat scheduler for waiting-lane polling) + a **state/audit schema you design** in the
  database. You own the advance/retry/resume logic — implement it deliberately and test
  resume-after-restart explicitly.
- **Background work:** Celery workers are **already separate processes**, which makes the
  Python build naturally "shared-ready" for the worker (rule 4 mostly free).
- **Script triggers:** Python scripts run **in-process** (seamless, same data structures)
  — an advantage if many comprehensive script-driven steps are expected. Non-Python
  scripts run as subprocesses.
- **Packaging:** clean via one command (`uvicorn` / `streamlit`), but a true single-file
  artifact needs **PyInstaller** (fiddly) or **Docker** (recommended for Python).
- **Local/shared switch:** environment-based settings select embedded SQLite vs networked
  PostgreSQL, etc.

### 5.3 Side-by-side (build to whichever is chosen)

| Concern | Java / Spring Boot | Python |
|---|---|---|
| Durable lane state | Embedded Camunda/Flowable (built-in) | Hand-built: Celery + state/audit tables |
| Human-approval gates | Engine human-task construct | Modelled by you |
| Audit trail | Engine-provided | Schema you design |
| Waiting-lane polling | Engine timers / scheduler | Celery beat |
| http / http_flow triggers | Easy | Easy |
| script triggers (real logic) | Java/Groovy in-process; Python via subprocess | Python in-process (seamless) |
| Browser automation | Playwright (Java) | Playwright (Python) |
| Single-artifact packaging | Excellent (one JAR) | PyInstaller or Docker |
| Time to first prototype | Slower | Faster |

Whichever is chosen, isolate durability logic behind a clean interface so the rest of the
codebase does not depend on the choice.

## 6. UI delivery (language-agnostic)

The UI talks to the backend over an API, so it does not force the backend language.
**Recommended:** React + TypeScript (the generic-view-by-default / custom-view-by-
exception pattern via a view registry is React's sweet spot — see `04`). Server-rendered
(Thymeleaf+HTMX for Java, Jinja+HTMX for Python) is acceptable if custom views stay few.
Build output is bundled with the backend (into the JAR for Java; served by FastAPI or via
Docker for Python).

## 7. The four local→shared rules (MANDATORY, any language)

The app must run as a **local single-instance tool first** and be promotable to a
**shared on-prem service later** by **configuration only, not a rewrite**. To guarantee
this, all four rules are mandatory from day one:

### Rule 1 — State lives in a database from day one, even locally
Never keep lane state in memory or process-local files. Always go through a data-access
layer to a database. Local = embedded (H2/SQLite); shared = networked PostgreSQL. Swapping
is a connection-string/profile change. The data-access layer must not assume which.

### Rule 2 — Externalize all configuration
DB location, secret-store location, tool base URLs, and run mode are read from
configuration/environment, never hardcoded. Provide two profiles:
`local` (embedded DB, local encrypted secret store, in-process worker) and
`shared` (PostgreSQL, server-side secret store, always-on worker, dashboard SSO).

### Rule 3 — Multi-user-aware data model from the start
Even running locally, model lanes and actions as belonging to a **user** (per-user
credentials already require this). Never bake in single-user assumptions. When multiple
people share an instance later, the schema already supports "whose lane / whose action /
whose credential."

### Rule 4 — Separable background worker
Keep the poll/advance/trigger-execution worker logic cleanly separated from request
handling, so it can run **in-process locally** and be promoted to a **standalone always-on
process** when shared. (Python/Celery is already separate; Java should keep the executor
logic decoupled.)

### Migration path this enables
```
PHASE A (pilot, local):   single instance · embedded DB · local secrets · in-process worker
        │  (same codebase — change profile only)
        ▼
PHASE B (shared, on-prem): one team instance · PostgreSQL · server-side secrets
                           · always-on worker · dashboard SSO
```
Going shared **adds** (does not rewrite): networked DB, server-side secret storage,
multi-user dashboard auth, optional standalone worker. Engine, config model, UI, and
integrations are unchanged.

### Security note (call out to stakeholders)
Per-user credentials encrypted on individual laptops (local) are the weakest security
point — and passwords (`basic` / `form_login`) more so than tokens. The same credentials
encrypted **server-side** (shared) are safer and easier to revoke. Treat the shared step
as **expected**, not hypothetical; do not let many users run local instances holding real
credentials for long. (Full risk ordering and guidance: `05` §3.)
