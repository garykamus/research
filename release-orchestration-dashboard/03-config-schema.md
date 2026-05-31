# 03 — Configuration Schema

> The *definition* data that drives the engine: the step library, the backbone template,
> per-market bindings with composition, tool/market config, and trigger-type definitions.
> Config may live as version-controlled files or in the DB (see §8). YAML is used for
> illustration; JSON is equally valid.

---

## 1. The layered model (read this first)

The market situation: **common backbone, a few steps added/skipped per market, across
15+ markets.** This is handled by **composition, not duplication**. Three layers:

```
1. STEP LIBRARY      — every step defined ONCE, reusable
2. WORKFLOW TEMPLATES — named sequences assembled from the library
                        (the BACKBONE is the primary template)
3. MARKET BINDINGS    — 15+ thin deltas: each market = template + small ops
```

**Mandatory property:** editing the backbone propagates to all markets automatically
(they *reference* it, never copy it). Adding the 16th market is a few lines and touches
no existing market. If a market binding grows large, promote its pattern to a new
template rather than hand-writing a market.

## 2. Step Library

Each step defined independently of any workflow. This is where most maintained content
lives.

```yaml
steps:
  create_pr:
    label: "Create PR on GitHub"
    mode: HYBRID
    view: generic
    tool: github
    produces: [pr_url]
    consumes: [package]
    trigger:
      type: http
      method: POST
      url_template: "{tool.github.api}/repos/{market.repo}/pulls"
      body_template: '{"head":"{package}","base":"main","title":"Release {package}"}'
      capture: { pr_url: "$.html_url" }
    link_buttons:
      - { label: "Open PR", url_template: "{pr_url}" }

  release_build:
    label: "Trigger release build"
    mode: AUTO
    view: generic
    tool: jenkins
    consumes: [package]
    trigger:
      type: http_flow            # trigger then poll (see 05)
      steps:
        - call: "POST {market.build_url}?PACKAGE={package}&OWNER={owner}"
        - poll: "GET {market.build_url}/lastBuild/api/json"
          until: "$.result != null"
          timeout: 30m
        - capture: { build_url: "$.url", build_result: "$.result" }
    produces: [build_url, build_result]

  sast_scan:
    label: "SAST / cyber scan"
    mode: HYBRID
    view: generic
    consumes: [build_url]
    produces: [sast_url, cyber_url]
    trigger: { type: webhook }   # results arrive via pipeline; human confirms acceptability

  create_cr:
    label: "Create CR on ServiceNow"
    mode: HYBRID
    view: cr_creation            # CUSTOM view (see 04)
    tool: servicenow
    produces: [cr_no, cr_url]
    view_config:
      fields:
        - { key: short_desc,       label: "Short description", type: text, required: true }
        - { key: assignment_group, label: "Assignment group",  type: dropdown, options_ref: snow_groups }
        - { key: planned_start,    label: "Planned start",      type: datetime }
        - { key: planned_end,      label: "Planned end",        type: datetime }
    trigger:
      type: http                 # ServiceNow REST where permitted; else type: browser / none
      method: POST
      url_template: "{tool.servicenow.api}/table/change_request"
      capture: { cr_no: "$.result.number", cr_url: "$.result.sys_url" }

  arcad_lock:
    label: "Lock ARCAD package"
    mode: AUTO
    tool: jenkins
    consumes: [package]
    trigger: { type: http, method: POST, url_template: "{market.g3_lock_url}?PACKAGE={package}" }

  g3_package:
    label: "Create G3 package"
    mode: AUTO
    tool: jenkins
    consumes: [package, cr_no]
    trigger: { type: http, method: POST, url_template: "{market.g3_url}?PACKAGE={package}&CR={cr_no}" }
    produces: [g3_url]

  submit_cr:
    label: "Submit CR for approval"
    mode: HYBRID
    tool: servicenow
    consumes: [cr_no]
    trigger: { type: http, method: POST, url_template: "{tool.servicenow.api}/.../{cr_no}/submit" }
    # waiting gate: engine polls SNOW for approval (see 01 state model)

  update_evidence:
    label: "Update CR info / audit page"
    mode: AUTO
    tool: servicenow
    consumes: [cr_no, sast_url, cyber_url, test_evidence_url, regression_url]
    view: evidence_update        # CUSTOM view: choose/preview fields to publish
    trigger:
      type: http
      url_template: "{market.cr_update_url}"
      body_template: '{"cr":"{cr_no}","sast":"{sast_url}","cyber":"{cyber_url}","test":"{test_evidence_url}","regression":"{regression_url}"}'

  update_confluence_release:
    label: "Update Confluence release page"
    mode: HYBRID
    tool: confluence
    view: confluence_release     # CUSTOM view: choose/preview fields to publish
    consumes: [cr_no, build_url, sast_url, test_evidence_url, regression_url]
    trigger: { type: http, url_template: "{confluence_page}/update" }   # or browser / none fallback

  update_jira_status:
    label: "Update Jira story status"
    mode: AUTO
    tool: jira
    consumes: [cr_no]
    trigger:
      type: http
      method: POST
      url_template: "{tool.jira.api}/issue/{jira_id}/transitions"
      body_template: '{"transition":{"id":"{target_transition}"},"update":{"comment":[{"add":{"body":"CR {cr_no} approved"}}]}}'

  regional_compliance:        # used only by some markets (composition)
    label: "Regional compliance sign-off"
    mode: MANUAL
    view: generic
    view_config:
      fields:
        - { key: signoff_ref, label: "Sign-off reference", type: text, required: true }
    produces: [signoff_ref]
```

### Step definition fields
`label`, `mode`, `view`, `view_config` (fields for the view), `tool`, `produces`,
`consumes`, `trigger` (see `05`), `link_buttons`, `post_actions` (see `05`).

## 3. Workflow Templates (the backbone)

Named sequences composed from the library. The **backbone** is the one nearly every
market uses.

```yaml
templates:
  backbone:
    steps:
      - create_pr
      - release_build
      - sast_scan
      - create_cr
      - arcad_lock
      - g3_package
      - submit_cr
      - update_evidence
      - update_confluence_release
      - update_jira_status

  regulated_flow:            # a variant for markets needing extra compliance
    extends: backbone
    add:
      - { step: regional_compliance, before: submit_cr }
```

- `extends` lets a template build on another (composition between templates).
- Templates reference library step ids; they never inline step definitions.

## 4. Market Bindings (thin per-market deltas)

Each market = a template + a small set of composition ops + its URLs/defaults.

```yaml
markets:
  HK:
    use: backbone
    urls:
      build_url:     "https://jenkins-hk/job/core-build"
      g3_lock_url:   "https://jenkins-hk/job/g3-lock"
      g3_url:        "https://jenkins-hk/job/g3-create"
      cr_update_url: "https://jenkins-hk/job/cr-update"
    repo: "org/hk-core"
    default_owner: "team-hk"

  SG:
    use: backbone
    urls: { build_url: "https://jenkins-apac/sg/release", g3_url: "https://jenkins-apac/sg/g3", ... }
    repo: "org/sg-core"
    override:
      release_build: { extra_params: { REGION: "apac" } }   # tweak a shared step

  ID:
    use: regulated_flow         # different STEPS, via a template
    add:
      - { step: data_residency_check, after: create_cr }
    override:
      create_cr: { extra_fields: [ { key: residency_zone, label: "Residency zone", type: text } ] }
    urls: { ... }
    repo: "org/id-core"

  TH:
    use: backbone
    add:    [ { step: regional_compliance, before: submit_cr } ]
    skip:   [ arcad_lock ]
    urls: { ... }
    repo: "org/th-core"
```

### Per-market browser / portal parameters (for shared no-API portals)
When many markets hit the **same** web portal (e.g. an Audit portal) but differ only in
which tab/sub-link/selector they use, the variation is **data, not code**. Put it in the
market binding under a `portal` (or similarly named) block, and a **single** browser flow
or script reads it (see `05` — one parameterized script serves all markets):
```yaml
markets:
  HK:
    # ...use / urls / repo as above...
    portal:
      audit:
        tab:           "Hong Kong"
        section_link:  "audit/hk"
        form_selector: "#hk-audit-form"
  SG:
    portal:
      audit:
        tab:           "Singapore"
        section_link:  "audit/sg"
        form_selector: "#sg-audit-form"
  # ...15+ markets, each a few lines — never a new script per market
```
Keep selectors in config (not hardcoded in scripts) so a portal UI change is a config fix.
Prefer stable selectors (text/role/label) over brittle ones (nth-child, generated ids).
Add a market by adding its `portal` block — never by writing a new script.

### Composition operations
| Op | Meaning | Example |
|---|---|---|
| `use` | Base template to start from | `use: backbone` |
| `add` | Insert a library step at a position | `add: [{step: X, before: submit_cr}]` |
| `skip` / `remove` | Drop a step for this market (becomes `SKIPPED`) | `skip: [arcad_lock]` |
| `reorder` | Move a step | `reorder: [{step: g3_package, after: submit_cr}]` |
| `override` | Tweak a shared step's params/fields for this market | `override: { create_cr: {...} }` |

Keep market entries thin. A market should be 0–3 ops in the common case.

## 5. Tool Config

Per-tool base URLs, auth type, and shared templates. Markets reference tools; tools hold
the cross-market base config. (Credentials are NOT here — see `05`, credential store.)

```yaml
tools:
  jenkins:     { base: "https://jenkins-...", auth: token }
  github:      { api: "https://api.github.com", auth: token }
  servicenow:  { api: "https://snow.../api/now", auth: token, fallback: browser }
  confluence:  { api: "https://confluence.../rest/api", auth: token, fallback: deep_link }
  jira:        { api: "https://jira.../rest/api/2", auth: token }
  legacy_api:  { api: "https://legacy.../api", auth: basic }        # username + password (HTTP Basic)
  audit_portal:                                                      # no API at all
    url: "https://audit-portal..."
    auth: form_login            # username + password used to log into the UI
    login_url: "https://audit-portal.../login"
    headless: true              # browser triggers run headless by default (see 05)
```

### `auth` types (full handling in `05` §3)
- `token` — API token / PAT. **Preferred** wherever supported; scoped, revocable.
- `basic` — username + password sent as HTTP Basic auth on `http`/`http_flow` calls
  (the tool has an API but uses passwords). Fully compatible with value capture/attribution.
- `form_login` — username + password used to **log into a web UI** that a `browser`
  trigger then drives (the tool has **no API**). Highest-risk; see security note in `05`.

`fallback` declares the integration tier to drop to when the API is unavailable
(see `05` tiers): `browser` (Playwright) or `deep_link` (manual + pre-filled URL).
`headless` (browser-driven tools) defaults to `true`; set `false` only as a debug switch.

## 6. Trigger types (summary; full contract in `05`)

`none` (manual) · `http` (one call) · `http_flow` (calls + poll + capture) ·
`script` (run Python/Java/shell with the bag/creds/market_config-in, result-out contract) ·
`browser` (Playwright — **declarative or scripted**, headless by default) ·
`webhook` (wait for inbound event). Defined per step under `trigger`. Browser triggers may
use `form_login` credentials and read per-market `portal` params so **one** flow/script
serves all markets (see `05` §1.4/§1.6).

## 7. Lane resolution + validation (MANDATORY)

At lane creation: `market → use template (+ extends) → apply add/skip/reorder/override →
concrete ordered StepInstance[]`.

The resolver **must validate** (critical at 15+ markets where deltas are easy to slip):
1. Every referenced step id exists in the step library.
2. Every `add.before/after` anchor exists in the resolved flow.
3. No `skip` of a step already absent (warn, don't fail).
4. **Value-bag coherence:** for every step's `consumes`, some earlier step in *this
   lane's resolved order* (or a lane attribute) `produces` it. Fail resolution with a
   precise message naming the missing producer.
5. No duplicate step ids in the resolved sequence.

Resolution validation runs at config-load time for every market too (a startup check),
so broken bindings are caught before any lane is created.

## 8. Config storage: file vs DB (decision deferred, support the seam)

- **Config-as-file** (version-controlled YAML/JSON): simplest, auditable, reload-on-change.
  Recommended default for a developer-facing tool.
- **Config-in-DB** (admin UI editing, live changes): more build effort; lets non-technical
  users edit flows without redeploy.

Build the config layer behind an interface so the **source** (file vs DB) can change
without touching the engine. Start with file; the engine must not assume file-ness.

## 9. Templating namespace (one namespace for all `{...}`)

Resolvable in any `*_template` / `url_template` / `body_template` / browser-flow value:
- **Lane attributes:** `{market}`, `{package}`, `{owner}`, `{jira_id}`, `{confluence_page}`
- **Value bag:** `{pr_url}`, `{cr_no}`, `{build_url}`, … (whatever has been produced)
- **Market config:** `{market.build_url}`, `{market.repo}`, `{market.g3_url}`,
  `{market.portal.audit.tab}`, `{market.portal.audit.form_selector}`, … (nested keys allowed)
- **Tool config:** `{tool.github.api}`, `{tool.servicenow.api}`, `{tool.audit_portal.url}`, …

Resolution fails loudly if a referenced placeholder is unavailable at fire time (ties to
the `consumes` validation — a step must not fire with unresolved required placeholders).
