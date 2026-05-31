# 02 — Data Model

> The runtime entities the engine persists. This is the *instance* data (actual lanes
> and their progress). The *definition* data (step library, templates, market bindings)
> is in `03`. Field types below are conceptual — map them to your DB of choice.

---

## 1. Entity overview

```
User ──┐
       │ owns / acts on
       ▼
Lane ──┬── LaneAttributes        (1:1, seeded at creation)
       ├── ValueBag              (1:1, grows as steps run)
       ├── StepInstance[]        (the resolved, ordered steps for this lane)
       │        └── Override     (0:1 per step)
       │        └── RecordedLink[] / RecordedValue[]
       └── AuditEntry[]          (append-only history)
```

## 2. Lane

The unit of work: one release of one ARCAD package to one market.

| Field | Type | Notes |
|---|---|---|
| `id` (`lane_id`) | id | **Primary key and the lane's true, stable identity.** Never changes — survives package/branch renames (see §3, §10). |
| `market` | string | FK-ish to a market in config. Part of the *display* identity. |
| `arcad_package` | string | ARCAD package name = market-repo branch name. **Mutable** display attribute (renameable — see §10), not the true identity. May be seeded at creation OR produced by a creation step (see §3). |
| `branch_name` | string | Market-repo branch; **kept equal to `arcad_package`** (see §3 alignment rule). Mutable. |
| `owner_user_id` | id | The owning user (Rule 3: multi-user-aware). |
| `created_by_user_id` | id | Who created the lane. |
| `created_at` | timestamp | |
| `workflow_template_id` | string | Which template this lane resolved from (see `03`). |
| `status` | enum | Derived rollup: `ACTIVE / WAITING / SUSPENDED / BLOCKED / DONE / CANCELLED`. |
| `current_step_id` | string | The step the lane is currently on (nullable when DONE). |

- **Identity vs. display:** `lane_id` is the immutable identity that owns all history,
  value bag, links, and audit. `(market, arcad_package)` is the **human-readable** display
  identity shown everywhere — but `arcad_package`/`branch_name` are **mutable** (renameable
  anytime, §10). A rename updates the attribute + audits; `lane_id` and all history are
  untouched.
- Lanes are **independent** — no parent/child batching (explicit product decision).

## 3. LaneAttributes

Values belonging to the whole lane, available to every step's triggers and views via
`{placeholder}` templating. Distinct from the value bag (§5). Most are seeded at creation;
some may be **produced** by an early step, and some are **mutable**.

| Attribute | Type | Source | Notes |
|---|---|---|---|
| `market` | string | creation | also on Lane; mirrored for templating. Immutable. |
| `arcad_package` | string | creation **or** produced | ARCAD package name. **Mutable** (renameable, §10). For an existing package, seeded at creation; for a *new* package, produced by a creation step (e.g. `create_arcad_package`, see `03`). |
| `branch_name` | string | creation **or** produced | Market-repo branch. **Must equal `arcad_package`** (alignment rule below). Mutable; renamed together with the package. |
| `owner` | string | creation | defaults from market config, overridable. |
| `jira_id` | string | creation | the assigned Jira story; clickable link in UI. |
| `confluence_page` | string/url | creation | release info page (linked or to-be-created). |
| *(extensible)* | | | further per-lane identifiers may be added in config. |

- **Package may be created by the flow, not only supplied.** A lane needs *some* identity
  at creation (market + an intended package name/version). Whether `arcad_package` already
  exists (seeded) or is created by the first step (produced), the rest of the flow consumes
  it identically from the bag/attributes. (Scenario: create-package-as-start.)
- **Name-alignment rule (MANDATORY):** `branch_name` must always equal `arcad_package`. A
  creation step that produces both must assert equality; a rename (§10) renames both
  together. The engine validates this invariant (see §9).
- **One Jira ID per lane** is the default. If a lane may map to several stories, model
  `jira_ids` as a list — confirm before relying on multiplicity. (Open item; default to
  single.)
- Attributes are referenced in templates as `{market}`, `{arcad_package}`, `{branch_name}`,
  `{jira_id}`, `{confluence_page}`, etc.

## 4. StepInstance

A concrete step within a lane, produced by lane resolution from a step-library
definition (see `03`). Uniform structure regardless of what the step does.

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique within the lane (e.g. `create_cr`). |
| `lane_id` | id | Owner lane. |
| `order` | int | Position in this lane's resolved sequence. |
| `definition_ref` | string | Which step-library entry this came from. |
| `label` | string | Display name. |
| `kind` | enum | `standard` (default) or `external_hold` — a parks-the-lane suspend point (see §4.1, `05` §1.7). |
| `mode` | enum | `AUTO / HYBRID / MANUAL` — *default* behaviour (see `04`/`05`). |
| `view` | string | `generic` or a custom view name (see `04`). |
| `status` | enum | `PENDING / IN_PROGRESS / SUSPENDED / DONE / BLOCKED / SKIPPED`. |
| `auto_result` | enum | `SUCCESS / FAILED / UNKNOWN` — what automation detected. |
| `override` | Override? | Optional manual override (see §6). |
| `effective_status` | derived | `override.value ?? auto_result`, mapped to status. |
| `produces` | string[] | Value-bag keys this step writes (see §5). |
| `consumes` | string[] | Value-bag keys this step requires before firing. |
| `recorded_links` | RecordedLink[] | URLs captured for this step. |
| `recorded_values` | RecordedValue[] | Field values captured for this step. |
| `trigger_ref` | object | The trigger config for this step (see `05`). |
| `post_actions` | object[] | Optional follow-on actions on completion (see `05`). |
| `entered_at` / `completed_at` | timestamp | Timing (also supports a timeline view). |
| `last_acted_by_user_id` | id | Who last advanced it (Rule 3). |

### Status semantics
- `PENDING` — not yet eligible or not yet started.
- `IN_PROGRESS` — trigger fired / work underway; for AUTO, awaiting auto-detected result.
- `SUSPENDED` — lane is intentionally parked at an `external_hold` step pending a separate
  workstream outside the dashboard (distinct from a human-approval wait). See §4.1.
- `DONE` — complete (by auto-detection, manual mark, or override).
- `BLOCKED` — failed / cannot proceed; surfaces prominently in UI.
- `SKIPPED` — not applicable to this lane (e.g. composed-out for this market) or
  explicitly skipped.

### 4.1 `external_hold` steps (parks the lane for external work)
A step with `kind: external_hold` models a deliberate gap where **other developers /
processes do work entirely outside the dashboard** (e.g. build, GitHub check-in by a
separate team) before the release flow resumes. (Scenario: create-package-then-pause.)

- The lane enters `SUSPENDED` (not `BLOCKED`, not `IN_PROGRESS`) and parks **durably and
  indefinitely** (state persists — Rule 1).
- It resumes via a **resume signal**: a webhook (e.g. the other team's build completed), a
  polled condition (e.g. branch has a new commit / build N passed), or **manual** ("external
  work done, continue"). Resume semantics are defined in `05` §1.7.
- On resume, downstream steps consume whatever the external work produced (e.g. a new build
  URL, commit ref) — recorded by the resume webhook or by a human — from the value bag.
- An `external_hold` step never fires a forward trigger of its own; it only waits and
  resumes. It is distinct from a `HYBRID` approval gate (which waits on a person to confirm
  a dashboard-driven action).

### Effective status rule (mandatory)
```
auto_result      = what automation reported (SUCCESS|FAILED|UNKNOWN)
override         = { value, who, when, reason }   (optional)
effective_status = override ? override.value : auto_result
```
The UI shows `effective_status`; the audit retains both. Example: scan `auto_result =
FAILED`, overridden to DONE by alice with reason → effective DONE, audit shows the divergence.

## 5. ValueBag

Per-lane key/value store of outputs produced by steps, consumed by later steps. **Lane-
scoped** — never shared across lanes.

| Field | Type | Notes |
|---|---|---|
| `lane_id` | id | Owner. |
| `key` | string | e.g. `pr_url`, `cr_no`, `build_url`, `sast_url`. |
| `value` | string | Captured value. |
| `produced_by_step_id` | string | Provenance. |
| `source` | enum | `manual / api / derived` (how it was obtained). |
| `recorded_at` | timestamp | |

### Value sources
- `manual` — a human typed/pasted it (e.g. CR number on a no-API tool).
- `api` — extracted from a trigger's API response (e.g. build URL from Jenkins JSON).
- `derived` — computed/templated from other values/attributes.

### Produce / consume contract (mandatory)
- A step declares `produces` (keys it writes) and `consumes` (keys it needs).
- Before firing a step, the engine **validates all `consumes` keys exist** in the bag
  (or in lane attributes). If missing, the step is not fired; the UI states exactly which
  value is missing.
- Lane attributes (§3) and the value bag share one templating namespace: `{cr_no}` may
  resolve from the bag, `{jira_id}` from attributes.

```
LANE VALUE BAG (example, grows over time)
  pr_url    = ".../pull/501"   produced_by create_pr   source api
  build_url = ".../build/1342" produced_by release_build source api
  sast_url  = ".../sast/..."   produced_by sast_scan    source manual
  cr_no     = "CR0048821"      produced_by create_cr    source manual
  cr_url    = ".../cr/..."     produced_by create_cr    source manual
```

## 6. Override

| Field | Type | Notes |
|---|---|---|
| `step_instance_id` | id | The overridden step. |
| `value` | enum | The forced result (e.g. `DONE`, `FAILED`). |
| `reason` | string | **Required.** Why the override was applied. |
| `who_user_id` | id | Who applied it. |
| `when` | timestamp | |

- Available on **every** step in **every** mode.
- `reason` is mandatory — attributability principle.

## 6a. Lane-level actions (anytime operations, not sequenced steps)

Some operations act on the **whole lane** and may happen **at any time**, independent of
the step sequence — analogous to how `override` is an out-of-band operation on a step.
They are defined in config (see `05` §1.8) and recorded in the audit. The primary example
is **rename**.

| Field | Type | Notes |
|---|---|---|
| `lane_id` | id | The lane acted on. |
| `action` | string | e.g. `rename_package`. |
| `trigger_ref` | object | The action's trigger (e.g. a Jenkins rename pipeline) — same trigger types as steps (`05`). |
| `updates` | object | Lane attributes set on success (e.g. `arcad_package`, `branch_name`). |
| `reason` | string | **Required** (attributability), like override. |
| `who_user_id` | id | Who invoked it. |
| `when` | timestamp | |

### Rename (`rename_package`) — the canonical lane-level action
ARCAD packages may be renamed **anytime**; the market-repo branch must be renamed to stay
aligned. (Scenario: rename-anytime.) Because `lane_id` is the stable identity (§2) and
`arcad_package`/`branch_name` are **mutable attributes** (§3), a rename:
1. triggers the Jenkins rename pipeline (rename ARCAD package **and** the branch together);
2. on success, updates `arcad_package` **and** `branch_name` to the new name (kept equal —
   §3 alignment rule);
3. writes an audit entry (who/when/why) and leaves `lane_id` + all history/value bag/links
   intact;
4. is picked up by any later step automatically, because steps resolve
   `{arcad_package}`/`{branch_name}` at fire time, not at creation.

## 7. RecordedLink / RecordedValue

`RecordedLink`: `{ step_instance_id, label, url, recorded_by_user_id, recorded_at }` —
rendered as clickable pills on the step and aggregated into a per-lane links summary.

`RecordedValue`: `{ step_instance_id, field_key, value, recorded_by_user_id, recorded_at }`
— values captured via a step's view fields; may also populate the value bag if the field
is declared as a `produces` key.

## 8. AuditEntry (append-only)

| Field | Type | Notes |
|---|---|---|
| `id` | id | |
| `lane_id` | id | |
| `step_instance_id` | id? | Null for lane-level events. |
| `event_type` | enum | `LANE_CREATED / STEP_TRIGGERED / STEP_RESULT / OVERRIDE_APPLIED / VALUE_RECORDED / LINK_RECORDED / STATUS_CHANGED / POST_ACTION_FIRED / LANE_SUSPENDED / LANE_RESUMED / LANE_ACTION_INVOKED / ATTRIBUTE_CHANGED / ...` |
| `actor_user_id` | id | Who (or `SYSTEM` for automated). |
| `at` | timestamp | |
| `detail` | json | Event-specific payload (old→new status, reason, captured keys…). |

- **Every** state change writes one entry. Immutable. This is the compliance backbone.

## 9. Invariants (the engine must enforce)

1. A step cannot enter `IN_PROGRESS`/`DONE` while any `consumes` value is missing.
2. `effective_status` is always derivable from `auto_result` + `override`; never stored
   inconsistently.
3. Value bag and credentials are strictly lane-scoped / user-scoped — no cross-lane leak.
4. Every state-changing operation produces exactly one audit entry.
5. Re-firing a step is idempotent (see `01` §4) — no duplicate external artifacts.
6. A `SKIPPED` step never blocks advancement and never has its trigger fired.
7. **`branch_name` always equals `arcad_package`** — enforced on creation, on any step
   that produces them, and on rename (§3, §6a).
8. **`lane_id` is immutable** — renames change attributes only; history/value bag/links
   stay bound to `lane_id`.
9. An `external_hold` step holds the lane in `SUSPENDED` indefinitely, never fires a
   forward trigger, and advances only on its resume signal or manual resume (§4.1).
