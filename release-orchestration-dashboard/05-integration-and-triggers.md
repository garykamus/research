# 05 — Integration & Triggers

> How steps actually *do* things: the trigger-type vocabulary and execution contract,
> the integration tiers (what to do when an API is missing), the script contract,
> per-user credential handling, and post-actions for side-effects (Jira/Confluence).

---

## 1. Trigger types

Every step's behaviour is a **typed trigger**. "Hit a URL" is only the simplest type.

| Type | Use | Config shape |
|---|---|---|
| `none` | Manual step — no automated trigger | `{ type: none }` |
| `http` | One REST/HTTP call | method, url_template, body_template?, capture? |
| `http_flow` | Sequence of calls with polling + capture | steps: [call / poll(until,timeout) / capture] |
| `script` | Run real logic (Python/Java/shell) | runtime, entry, (bag in / result out) |
| `browser` | Playwright automation for no-API tools | flow steps / selectors |
| `webhook` | No outbound call — wait for inbound event | event match criteria |

### 1.1 `http`
```yaml
trigger:
  type: http
  method: POST
  url_template: "{market.build_url}?PACKAGE={package}&CR={cr_no}"
  body_template: '{"key":"value"}'        # optional
  capture: { build_url: "$.url" }          # JSONPath → value bag keys
```

### 1.2 `http_flow` (trigger → poll → capture)
```yaml
trigger:
  type: http_flow
  steps:
    - call:  "POST {market.build_url}?token={token}"
    - poll:  "GET {market.build_url}/lastBuild/api/json"
      until: "$.result != null"
      timeout: 30m
      interval: 30s
    - capture: { build_result: "$.result", build_url: "$.url" }
```
Polling here is the *within-trigger* wait for a single action to finish. It is distinct
from the engine's *waiting-lane* polling for human-approval gates (see `01` §3) — both
exist; don't conflate them.

### 1.3 `script` — comprehensive logic (the escape hatch)
For steps that need branching, multi-system coordination, custom parsing, or bespoke
auth that the declarative types can't express.

**Contract (mandatory, identical across languages):** a script receives the lane's
**attributes + value bag + the acting user's credentials + the resolved market config**
as input, and returns **status + produced values**. The engine treats a script exactly
like any other trigger (same status tracking, override, audit, value pass-through).

```yaml
trigger:
  type: script
  runtime: python            # python | java | groovy | shell
  entry: "scripts/create_g3.py"
```

Input handed to the script (conceptual):
```json
{ "lane":   { "market":"MY","package":"hotfix-3309","jira_id":"PROJ-4471" },
  "bag":    { "cr_no":"CR0048821","build_url":"..." },
  "creds":  { "jenkins":{...}, "servicenow":{...} },   // acting user's tokens/passwords
  "market_config": { "portal": { "audit": { "tab":"...", "section_link":"...",
                                            "form_selector":"..." } }, "urls": {...} } }
```
Required return:
```json
{ "status": "SUCCESS",                 // SUCCESS | FAILED
  "produced": { "g3_url":"..." },       // written into the value bag
  "links":    [ {"label":"G3 job","url":"..."} ],   // optional
  "message":  "..." }                   // optional, for audit/UI
```

**`market_config` is what makes one script serve many markets** (see §1.6): per-market
differences (which tab, which sub-link, which selector) arrive as *data*, so the script
logic stays singular. Do **not** write one script per market.

**Execution by backend (see `01`):**
- Python backend + `runtime: python` → in-process call (seamless).
- Java backend + `runtime: java/groovy` → in-process.
- Cross-language (e.g. Java backend + python script) → subprocess with the JSON contract
  above over stdin/stdout. Enforce a timeout; capture stderr to audit on failure.

**A script may itself drive Playwright** for complex browser flows that the declarative
`browser` form (§1.4) can't express — this is the "scripted browser" mode (§1.4/§1.6).

**Governance (mandatory):** scripts are **code**, not config. Treat as the exception
(like custom views). They must live in a reviewed, version-controlled location (see the
folder structure in `06` §7); run with a timeout; never log credentials; and ideally run
sandboxed (least-privilege). A workflow where *every* step is a script has become a
codebase again — flag that as a smell.

### 1.4 `browser` — Playwright, with two execution modes
For tools with **only** a web UI. Browser automation is a **first-class trigger type** —
it is **not** done via a `script` (though a script *may* drive Playwright for hard cases).
It has two modes:

- **Declarative** — describe the flow (navigate / fill / click / capture) in config, with
  values templated per market. Use for simple, linear flows.
  ```yaml
  trigger:
    type: browser
    headless: true                       # default; presented like an API trigger (§1.6)
    auth: form_login                     # uses the user's username/password for the tool
    flow:
      - goto:   "{tool.audit_portal.url}"
      - login:  { creds: form_login, login_url: "{tool.audit_portal.login_url}" }
      - click:  "text={market.portal.audit.tab}"          # per-market, from config
      - goto:   "{tool.audit_portal.url}/{market.portal.audit.section_link}"
      - fill:   { selector: "{market.portal.audit.form_selector} #cr", value: "{cr_no}" }
      - submit: "button[type=submit]"
      - capture:{ audit_ref: "text=#audit-ref" }
  ```
- **Scripted** — a `script` trigger (`runtime: python`) that uses Playwright in code, for
  flows with branching, conditional dialogs, waits, etc. Same Playwright runner; full logic.

**Headless by default (§1.6):** runs without a visible window; from the UI it looks
exactly like an `http` trigger. `headless: false` is a debug-only switch.

**Caveats (state to stakeholders):** fragile to UI change; slower (seconds, treat as
long-running with a timeout like `http_flow`); and it uses **`form_login` credentials, not
tokens** — the highest-risk credential (see §3). Prefer Tier 1 (API) or Tier 3 (manual +
deep link, where **no password is stored at all** because the user logs into their own
browser). Use `browser` only when there is genuinely no API.

### 1.5 `webhook`
The step advances on an **inbound** event (e.g. Jenkins build-complete, GitHub PR-merged)
rather than an outbound call. Define match criteria (event type + correlation to lane,
e.g. by build tag or PR number). Falls back to polling if the tool can't push.

### 1.6 One script/flow for many markets + headless behaviour

**One parameterized procedure, not one-per-market.** When markets hit the same portal but
click different tabs/sub-links, the *procedure* is identical and only the *data* differs.
Put the data in each market's `portal` block (`03` §4) and write **one** declarative flow
or **one** script that reads `market_config`. Add a market by adding its `portal` block —
a few lines — never a new script.

- **Same procedure, different data → one script/flow** (the common case at 15+ markets).
- **Genuinely different procedure → a second named script/flow** shared by the markets that
  need it (mirrors the workflow-template variant rule). Never one-per-market.
- **Selectors live in config**, so a portal UI change is a config fix; a shared portal also
  means you fix breakage in one place. Prefer stable selectors (text/role/label).

**Headless presentation:** `browser` triggers run headless and are presented in the UI
identically to API triggers — the developer clicks "trigger," it runs in the background,
status updates, values are captured. The browser-ness is hidden.
- *Deployment requirement:* the process that runs the trigger (worker) must have the
  Playwright browser installed — local mode: the developer's machine; shared mode: the
  server/worker.
- *Timing:* slower than an API; treat as long-running with a timeout. UI shows
  "in progress" → "done."
- *Login is the weak point:* clean username/password (`form_login`) headless logins feel
  API-like; **MFA/SSO logins stall headless** — for those, prefer Tier 3 (manual + deep
  link). Pick the tier per tool accordingly.

## 2. Integration tiers (when an API is missing)

For each step, use the **highest feasible tier**. Real deployments end up mixed.

```
1. Real API (REST), even behind permissions  → http / http_flow      (best)
2. Tool pushes webhooks                       → webhook (instant status)
3. No API, stable UI, worth automating        → browser (Playwright)  (sparingly)
4. No API / risky UI / low frequency          → none + pre-filled deep link + paste-back
```

### Decision order per step
1. Real API available? → `http`/`http_flow` (AUTO/HYBRID).
2. Tool can push events? → `webhook`.
3. Only a web UI and automation is worthwhile? → `browser` (HYBRID).
4. Otherwise → `none` (MANUAL): build a **pre-filled deep link** (parameters substituted
   from attributes/bag) so the human lands on the right page, and capture the result via
   one paste-back field.

**Tier note for this project:** Jenkins/GitHub → Tier 1/2. ServiceNow/Confluence → Tier 1
where permissions allow, else Tier 3 (the blocker is usually permission, not absence —
exhaust Tier 1 first). Jira → Tier 1 (REST). Reserve Tier 2 browser for any tool with
genuinely no API.

## 3. Tools & per-user credentials

### 3.1 Credential store (per-user, encrypted, multi auth types)
- Each developer authenticates **as themselves** to each tool, so every triggered action
  is attributable (compliance requirement).
- The store holds, **per user, per tool**, whatever the tool's `auth` type needs:

  | `auth` type | Stored secret(s) | Used for |
  |---|---|---|
  | `token` | one token / PAT | API calls (`http`/`http_flow`) — **preferred** |
  | `basic` | username + password | HTTP Basic auth on API calls |
  | `form_login` | username + password | logging into a web UI for a `browser` trigger |

- **Prefer `token`** wherever supported (GitHub, Jenkins, ServiceNow, Jira, Confluence all
  support tokens) — scoped and revocable. Use `basic`/`form_login` only when a tool offers
  nothing better.
- **Encrypt at rest; never log; scope per user.** (Data model: credentials belong to a
  user — Rule 3.)
- **Local vs shared (see `01` §7):** local = encrypted on the machine (weakest point);
  shared = server-side encrypted store (safer, revocable). Build the store behind an
  interface so the backing location is a config/profile choice.

### 3.2 Credential resolution at fire time
When a step fires, the engine supplies the **acting user's** credential for that step's
`tool`, in the form its `auth` type requires (token / basic / form_login). If
absent/expired, the step is not fired; the UI prompts the user to add/refresh the
credential (and offers manual override as the fallback).

### 3.3 Security note — passwords raise the risk profile (MANDATORY call-out)
Risk ordering, lowest to highest: `token` < `basic` < `form_login`.
- `token` is scoped and revocable. `basic` exposes the user's real account password to an
  API. `form_login` stores a real account password used to drive a UI — the **highest-risk
  credential** in the design, and the `browser`+`form_login` combination is the
  highest-risk, highest-maintenance path overall.
- Storing **passwords encrypted on a laptop** (local mode) is the weakest posture in the
  whole system. Passwords therefore **strengthen the case for shared mode** (server-side
  encrypted store) and for treating local mode as a short-lived pilot — do not let many
  users hold real passwords in local instances for long.
- **Prefer Tier 3 (manual + pre-filled deep link) for no-API tools**: the user logs into
  their **own** browser, so **no password is stored by the tool at all**. Reserve
  `browser`+`form_login` for cases where even manual won't do.
- Never log raw credentials; for `form_login`, prefer reusing a short-lived session over
  replaying the password where the tool allows it.

## 4. Post-actions (side-effects on completion)

Some updates should fire **as a side-effect** of a step finishing (e.g. on CR approval,
move the Jira story and stamp the Confluence page) rather than as separate manual steps.

**Support both; default to explicit steps; allow post-actions for obvious side-effects.**
- **Explicit step** (default): the action is its own row in the pipeline; visible,
  controllable, fully audited. Best for compliance clarity.
- **Post-action (hook):** declared on a step; fires automatically when that step
  completes. Convenient for tightly-coupled updates; still audited (`POST_ACTION_FIRED`).

```yaml
# post-action example: when submit_cr reaches DONE (CR approved), update Jira
submit_cr:
  # ...trigger as before...
  post_actions:
    - when: DONE
      do:
        type: http
        method: POST
        url_template: "{tool.jira.api}/issue/{jira_id}/transitions"
        body_template: '{"transition":{"id":"{deployed_transition}"}}'
    - when: DONE
      do:
        type: http
        url_template: "{confluence_page}/update"
```
Post-actions use the **same trigger types** and templating as steps, and obey the same
token/tier rules. A post-action failure must surface (not silently swallowed) and be
recoverable (retry / manual override on the parent step).

## 5. Jenkins parameter mapping (per-market)

Markets' Jenkins jobs may expect **different parameter names**. Tool/market config maps
canonical fields → each job's actual param keys, so the engine stays agnostic:
```yaml
markets:
  SG:
    override:
      release_build:
        param_map: { PACKAGE: "ARTIFACT", OWNER: "REQUESTED_BY", CR: "CHANGE_NO" }
```
If all markets share param names, this is unused; if they vary (likely), the map absorbs
the difference without per-market step definitions.

## 6. Failure handling (all trigger types)
- A failed trigger sets `auto_result = FAILED`, step `BLOCKED`; writes audit with the
  error; surfaces in UI; offers retry + override.
- Retries are idempotent (see `01` §4). Timeouts apply to `http_flow` polls, `script`
  execution, and `browser` flows.
- `webhook`/waiting gates that never arrive must be visible as long-waiting (feeds the
  optional timeline lens) and manually overridable.
