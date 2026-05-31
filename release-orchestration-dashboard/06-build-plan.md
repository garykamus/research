# 06 — Build Plan & Acceptance Criteria

> Phased delivery, the validation rules the engine must enforce, and acceptance criteria
> per phase. The manual-record capability means the tool is useful **before** any
> integration is automated — start all-manual, automate step by step.

---

## 1. Guiding sequencing principle

Build value-first and risk-down:
1. Make the dashboard a **source of truth** with everything manual (no integration risk).
2. Automate the **safe, high-value** integrations (Jenkins/GitHub).
3. Add **custom views** and the **harder tools** (ServiceNow/Confluence/Jira).
4. **Harden & scale** (shared backend, multi-user, optional config-in-UI).

Apply the four local→shared rules (`01` §7) from Phase 1 — they are cheap early,
expensive to retrofit.

## 2. Phases

### Phase 1 — Source of truth (all manual)
**Goal:** one place that tracks every release and gathers every link.
- Data model: Lane, LaneAttributes (incl. `jira_id`, `confluence_page`), StepInstance,
  ValueBag, Override, RecordedLink/Value, AuditEntry (`02`).
- Config layer: step library + backbone template + market bindings + **lane resolution
  with validation** (`03`). Config-as-file to start.
- Engine: lane creation + resolution; manual step advancement; value bag with
  produce/consume validation; override (with reason); full audit.
- Every step `mode: MANUAL`: trigger by hand elsewhere, paste links/values, mark done.
- UI: Matrix board (condensed default + full toggle); pipeline-aware lane detail with
  inline expand; generic view with configurable fields; clickable links + per-lane links
  summary; `jira_id`/`confluence_page` as links.
- **Local profile** working end-to-end (embedded DB, in-process worker) — but built to
  the four rules.

**Acceptance:**
- Create a lane for `(market, arcad_package, owner, jira_id, confluence_page)`; it resolves
  to the correct market-specific step list (incl. add/skip).
- Walk all steps manually; record links/values; produced values appear available to later
  steps; consume-validation blocks a step missing a required value with a precise message.
- Apply an override with a reason; effective status reflects it; audit shows auto vs
  override.
- Matrix shows multiple lanes with differing step counts correctly in condensed mode.
- Restart the app mid-flow → no state lost (Rule 1 proven).
- **Rename a lane's package** via the lane-level action (with reason): `arcad_package` and
  `branch_name` update together, `lane_id`/history are preserved, and the change is audited.
- An **`external_hold`** step parks the lane in `SUSPENDED` and a manual "continue" resumes
  it; the suspended state survives a restart.

### Phase 2 — Automate the safe wins
**Goal:** automate Jenkins/GitHub; aggregate evidence.
- Per-user encrypted credential store (`05` §3; token / basic / form_login); credential
  resolution at fire time.
- Trigger execution: `http`, `http_flow`, `webhook`; integration clients for Jenkins +
  GitHub; Jenkins per-market `param_map`.
- AUTO triggers: release build, ARCAD lock, G3. HYBRID: scans (trigger + human confirm).
- `create_arcad_package` step (creates ARCAD package + matching branch, produces
  `arcad_package`/`branch_name`); `rename_package` lane action wired to its Jenkins
  pipeline (renames package + branch together).
- `external_hold` resume via **webhook/poll** (auto-resume when the external build/check-in
  completes), in addition to the manual resume from Phase 1.
- Engine **waiting-lane polling** + webhook advancement (`01` §3); on-demand refresh.
- Evidence aggregation: `update_evidence` step composes captured scan + Confluence URLs.
- Idempotency keys; resume-after-restart proven for in-flight automated steps.

**Acceptance:**
- A build step fires via the user's token, polls to completion, captures `build_url`,
  advances automatically.
- A waiting gate (e.g. PR merged via webhook) advances the lane without manual action.
- `create_arcad_package` creates the package + branch and produces equal
  `arcad_package`/`branch_name` (alignment validated).
- An `external_hold` step auto-resumes on its webhook/poll signal, capturing the produced
  value into the bag.
- A `rename_package` action renames package + branch via Jenkins, updates both attributes,
  and later steps use the new name.
- Re-firing a step does not create a duplicate external artifact.
- Override still works on an automated step (auto FAILED → overridden DONE, audited).

### Phase 3 — Custom views & harder tools
**Goal:** bespoke step UIs and the API-light tools.
- Custom views: `cr_creation` (configurable fields incl. per-market `override.extra_fields`,
  validation, then trigger), `evidence_update`, `confluence_release` (`04` §4).
- ServiceNow/Confluence via REST where permitted; else Tier-3 pre-filled deep links +
  paste-back. Jira via REST.
- `script` trigger execution with the bag-in/result-out contract + governance (`05` §1.3).
- `browser` (Playwright) only for any tool with genuinely no API.
- Post-actions (`05` §4): e.g. on CR approval, transition Jira + update Confluence.

**Acceptance:**
- CR creation via custom view: fill configurable fields, trigger, capture `cr_no`/`cr_url`;
  `cr_no` feeds G3 + evidence steps.
- A market with extra CR fields (per `override`) shows them without code change.
- A post-action fires on completion, is audited, and a post-action failure surfaces and is
  recoverable.
- A `script` step runs, returns produced values into the bag, and is audited.

### Phase 4 — Hardening & scale
**Goal:** promote to a shared on-prem service.
- Switch to **shared profile** by config: networked PostgreSQL, server-side encrypted
  secret store, standalone always-on worker, dashboard SSO login. **No engine rewrite.**
- Multi-user concurrency: lanes/actions/tokens correctly scoped per user (Rule 3 proven).
- Optional: config-in-UI editing (admin screens) behind the existing config interface.
- Optional: timeline lens for stall/bottleneck monitoring.
- Richer audit reporting/export for compliance.

**Acceptance:**
- The same build runs under the shared profile against PostgreSQL with only config
  changes.
- Two users operate concurrently; each sees/acts with their own tokens; actions are
  attributed correctly.
- A backbone config change propagates to all 15+ markets without editing any market
  binding.

## 3. Validation rules the engine MUST enforce (cross-phase)

From `02` §9 and `03` §7 — restated as a checklist:
1. **Lane resolution** validates: referenced steps exist; add anchors exist; no duplicate
   step ids; warn on redundant skips.
2. **Value-bag coherence** at resolution: every `consumes` has a producer earlier in the
   resolved order (or a lane attribute). Fail with a precise message.
3. **Consume-gating** at fire time: a step never fires while a required value/placeholder
   is unresolved.
4. **Effective status** always derivable from `auto_result` + `override`; never stored
   inconsistently.
5. **Idempotency:** re-fire produces no duplicate external artifacts; restart resumes
   without re-firing.
6. **Lane/user scoping:** no value or credential leaks across lanes/users.
7. **Audit completeness:** every state change writes exactly one audit entry.
8. **Override requires a reason.**
9. **SKIPPED steps** never fire and never block advancement.
10. **Config-load startup check:** validate every market binding resolves coherently
    before serving.
11. **Name alignment:** `branch_name` always equals `arcad_package` — on creation, on any
    producing step, and on rename.
12. **Immutable `lane_id`:** renames change attributes only; history/value bag/links stay
    bound to `lane_id`.
13. **`external_hold`** holds the lane `SUSPENDED` indefinitely, fires no forward trigger,
    and advances only on resume (webhook/poll/manual); a lane resolving to end on an
    unresolved hold is flagged.
14. **Lane-level actions** (e.g. rename) require a reason, are audited, and apply
    atomically (no partial rename on trigger failure).

## 4. Cross-cutting non-functionals
- **Security:** credentials encrypted at rest, never logged; scripts sandboxed/timed;
  secrets never in templates' audit payloads. Risk ordering token < basic < form_login.
- **Resilience:** all triggers time out; failures are visible and recoverable; the worker
  is separable (Rule 4).
- **Performance:** poll only waiting lanes; matrix renders many lanes without per-lane
  live calls (use persisted state + on-demand refresh).
- **Auditability:** the audit log is the compliance backbone — append-only, complete,
  exportable (Phase 4).
- **Config-driven:** common changes (add/remove/reorder steps, tweak triggers, adjust
  fields, onboard a market) require **no code** — verify this holds at each phase.

## 5. Definition of done (overall v1)
- 15+ markets onboarded as thin bindings off a shared backbone; a new market is a few
  config lines.
- All eight+ workflow steps operable in their intended modes/tiers, with custom views for
  CR creation, evidence update, and Confluence release.
- Jira link on every lane; Jira status update (step or post-action) working.
- Per-user attributable actions; full audit; override everywhere.
- Runs local (single JAR or Docker) and promotes to shared on-prem by config only.
- Language: implemented in the chosen stack (Java/Spring or Python) per `01` §5, with the
  durability approach appropriate to that stack and the four local→shared rules satisfied.

## 6. Open decisions to confirm with stakeholders (do not block earlier phases)
- **Backend language** — Java/Spring (durability/audit built-in, single JAR) vs Python
  (faster prototype, in-process Python scripts, Docker packaging). `01` §5.
- **Local vs shared first** — start local (Phase 1) regardless; confirm timing of Phase 4
  promotion. `01` §7.
- **Config-as-file vs config-in-UI** — start file; UI editing optional in Phase 4. `03` §8.
- **Jenkins parameter names** — uniform across markets, or per-market `param_map` needed?
  `05` §5.
- **ServiceNow/Confluence API access** — determines Tier 1 vs Tier 3 for those steps.
- **One Jira ID per lane** vs several — default single; confirm if multiplicity needed.
  `02` §3.

## 7. Recommended folder structure

A layout that keeps the cross-cutting mandates honest: **config separate from code**,
**scripts in a reviewed location**, **local/shared as profiles**, and the **same codebase**
shippable local or shared. Names are illustrative; adapt to the chosen language's
conventions. Two backend variants shown; the non-backend folders (`config/`, `scripts/`,
`web/`, `deploy/`) are identical regardless of language.

```
release-orchestration/
├── config/                      # ALL configuration (version-controlled; NOT code)
│   ├── steps/                   # step library — one file per step or grouped
│   │   ├── core.yaml            #   create_pr, release_build, sast_scan, ...
│   │   └── compliance.yaml      #   regional_compliance, data_residency_check, ...
│   ├── templates/               # workflow templates
│   │   ├── backbone.yaml
│   │   └── regulated_flow.yaml
│   ├── markets/                 # thin per-market bindings (15+ small files)
│   │   ├── HK.yaml              #   use/urls/repo/portal/override...
│   │   ├── SG.yaml
│   │   └── ...                  #   add a market = add a file here
│   ├── tools/
│   │   └── tools.yaml           # per-tool base URLs + auth type (token/basic/form_login)
│   └── views/                   # custom-view field definitions (cr_creation, etc.)
│       └── *.yaml
│
├── scripts/                     # CUSTOM SCRIPTS — code, reviewed, version-controlled
│   ├── python/                  #   runtime: python  (one generic, parameterized per market)
│   │   ├── update_audit_portal.py     # ONE script, reads market_config.portal
│   │   ├── create_g3.py
│   │   └── lib/                 #   shared helpers (login, playwright utils, http helpers)
│   ├── groovy/                  #   runtime: groovy/java (if Java backend, in-process)
│   └── README.md                #   the bag/creds/market_config-in, result-out contract
│
├── backend/                     # the engine + API (ONE of the two below)
│   │
│   │  ── Java / Spring Boot variant ──
│   ├── src/main/java/.../
│   │   ├── engine/              # lane lifecycle, resolution, advancement, value bag
│   │   ├── triggers/            # http, http_flow, script, browser, webhook executors
│   │   ├── integrations/        # jenkins/github/servicenow/confluence/jira clients
│   │   ├── credentials/         # encrypted store (token/basic/form_login) behind iface
│   │   ├── config/              # config loader (file|db) behind iface + validation
│   │   ├── persistence/         # data-access layer (Rule 1: DB always)
│   │   └── api/                 # REST/WebSocket controllers
│   ├── src/main/resources/
│   │   ├── application-local.yaml    # profile: embedded DB, local secrets, in-proc worker
│   │   └── application-shared.yaml   # profile: PostgreSQL, server secrets, SSO, worker
│   │
│   │  ── Python variant ──
│   ├── app/
│   │   ├── engine/              # lane lifecycle, resolution, advancement, value bag
│   │   ├── triggers/            # http, http_flow, script, browser, webhook executors
│   │   ├── integrations/        # tool clients
│   │   ├── credentials/         # encrypted store behind iface
│   │   ├── config/              # loader (file|db) behind iface + validation
│   │   ├── persistence/         # data-access layer (Rule 1: DB always)
│   │   ├── worker/              # Celery tasks/beat (Rule 4: separable worker)
│   │   └── api/                 # FastAPI routers
│   ├── settings_local.py        # profile equivalents (env-driven)
│   └── settings_shared.py
│
├── web/                         # frontend (React + TS recommended; decoupled)
│   ├── src/
│   │   ├── views/               # MatrixBoard, LaneDetail
│   │   ├── stepviews/           # view registry: generic + custom (cr_creation, ...)
│   │   └── api/                 # client to backend REST/WebSocket
│   └── ...
│
├── deploy/
│   ├── local/                   # run-as-JAR / run-as-uvicorn instructions
│   └── shared/                  # docker-compose / on-prem service, PostgreSQL, worker
│
├── migrations/                  # DB schema migrations (works embedded + PostgreSQL)
└── docs/                        # this spec set (00–06)
```

### Folder rules (mandatory)
- **`config/` is never code.** Adding/reordering/skipping steps, onboarding a market,
  changing a trigger URL, adjusting view fields, or adding per-market `portal` params all
  happen here — no recompile. (Principle: config drives the flow.)
- **`scripts/` is reviewed code, kept thin.** One generic, parameterized script per
  *procedure* (reads `market_config`), not one per market. A second script only for true
  structural divergence. Shared helpers in `lib/`. The bag/creds/market_config contract is
  documented in `scripts/README.md` and `05` §1.3.
- **One market = one file in `config/markets/`.** Onboarding the 16th market adds a file
  and touches nothing else; backbone edits in `config/templates/` propagate to all.
- **Profiles, not branches, switch local↔shared** (`application-local|shared`,
  `settings_local|shared`). Same codebase (Rule 2).
- **`persistence/` is the only place that knows the DB** (Rule 1); **`worker/` (or the
  Java executor) is separable** (Rule 4); **`credentials/` and `config/` sit behind
  interfaces** so backing stores (local↔shared, file↔db) are swappable.
