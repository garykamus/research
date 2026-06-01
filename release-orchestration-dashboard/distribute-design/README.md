# Release Orchestration Dashboard — Implementation Spec

Implementation specification for an agent (or team) to build the **Release Orchestration
Dashboard** for AS400 multi-market deployment. Language-agnostic: both **Python** and
**Java/Spring Boot** are carried as options with handling notes, and the **four
local→shared rules** are mandated regardless of language.

## Read in this order

| File | Purpose |
|---|---|
| `00-overview.md` | Problem, five principles, glossary, the whole picture. **Read first.** |
| `01-architecture.md` | Components, durable-state model, language options (Python/Java), the four local→shared rules. |
| `02-data-model.md` | Runtime entities: lane, attributes, value bag, step instance, status, override, audit. |
| `03-config-schema.md` | Step library, backbone/templates, market bindings + composition, tools, trigger types, lane-resolution validation. |
| `04-ui-spec.md` | Matrix (full/condensed) + pipeline-aware lane detail + generic/custom views. |
| `05-integration-and-triggers.md` | Trigger execution (incl. browser declarative/scripted, headless), integration tiers, script contract (bag/creds/market_config), auth types (token/basic/form_login), per-user credentials, post-actions. |
| `06-build-plan.md` | Phased delivery, validation rules, acceptance criteria, open decisions, **recommended folder structure** (config / scripts / backend / web). |

## Non-negotiables (every file assumes these)
- **Config drives the flow** — adding/reordering/skipping steps and onboarding markets is
  configuration, not code.
- **The four local→shared rules** — state in a DB from day one, externalized config,
  multi-user-aware data model, separable worker. (`01` §7)
- **Attributability** — every state change is audited (who/when/what/why); override
  requires a reason.
- **Lane independence & isolation** — no value or credential leaks across lanes/users.
- **Persist the flow, live-check external truth** — orchestration state is durable;
  build/CR/PR status is read live from the owning tool, never cached as truth. (`01` §3)
- **One generic script/flow per procedure, parameterized per market** — not one per
  market. No-API tools use `browser` (declarative or scripted, headless) with
  `form_login`, but **Tier 3 (manual + deep link) is preferred** as it stores no password.
  (`05` §1.4/§1.6/§3)
- **Stable identity, mutable names** — `lane_id` is the immutable identity; `arcad_package`
  and `branch_name` are mutable, renameable anytime (and kept equal), and the package may
  be created by the flow. Lanes can suspend for external workstreams and resume. (`02`)

## Market model (drives the config design)
Common backbone + a few steps added/skipped per market, across **15+ markets**. Handled
by **composition, not duplication**: one backbone, thin per-market deltas. (`03`)

## Open decisions (confirm with stakeholders; do not block Phase 1)
Backend language · timing of shared promotion · config-as-file vs UI · Jenkins parameter
naming · ServiceNow/Confluence API access · one vs several Jira IDs per lane. (`06` §6)

## Wireframe references (approved in design review)
- `matrix_board_wireframe` — matrix, full density
- `matrix_condensed_progressbar_wireframe` — matrix, condensed (default)
- `lane_detail_pipeline_aware_wireframe` — lane detail, resting
- `lane_detail_pipeline_expanded_step_wireframe` — lane detail, expanded (custom + manual steps)
