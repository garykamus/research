# 00 — Overview & Principles

> **Read this first.** It defines the problem, the vocabulary, and the non-negotiable
> principles every other file depends on. Do not start building from later files
> without internalizing this one.

---

## 1. What we are building

A **Release Orchestration Dashboard** for AS400 multi-market deployment: a single
control plane that is the source of truth for every release. It triggers what can be
automated, lets a human perform and record what cannot, gathers every link and value
in one place, and is **driven by configuration** so the workflow can change without
rebuilding the application.

It exists to remove the toil of repeating a long, mostly-manual release process once
per market and per ARCAD package. Today that process is walked by hand across Jenkins,
GitHub, ServiceNow, Confluence, and Jira, with status and evidence scattered across all
of them.

## 2. The problem, concretely

A single release today is a chain of steps (create PR → release build → SAST/cyber scan
→ create CR → lock ARCAD package → create G3 → submit CR → update evidence page). To
deploy to multiple markets or ship multiple packages, the **entire chain repeats** —
once per `(market, ARCAD package)` pair. There is no shared state, no single status
view, and the final evidence-collation step is pure manual copy-paste of URLs.

## 3. The five principles (non-negotiable)

| Principle | Meaning in practice |
|---|---|
| **Source of truth** | The dashboard always knows where every release stands — even for steps performed by hand elsewhere. Nothing falls through the cracks. |
| **Automate, degrade gracefully** | A step may be fully automated, partly automated, or fully manual — and may switch between these **via config**, without changing the app's shape. |
| **Config drives the flow** | Steps, order, triggers, fields, per-market URLs, and per-market step variations all live in configuration. Adding/reordering a step is a config change, not new code. |
| **Everything attributable** | Every action — automated, manual, or an override — records *who*, *when*, and *why*. Essential for the compliance / CR context. |
| **Lane independence** | Each `(market, ARCAD package)` pair is its own self-contained release lane with its own status, links, value bag, and history. |

If a design decision ever conflicts with one of these, the principle wins. Flag the
conflict rather than silently violating it.

## 4. Glossary (use these terms exactly)

- **Lane** — one release of one ARCAD package to one market. The unit of work.
  Identified by `(market, ARCAD package)`. Lanes are independent.
- **ARCAD package** — the GitHub branch name on a market's repo that is being released.
  Developers know these well; the lane carries it as an identifier.
- **Step** — one stage in a lane's workflow (e.g. "Create CR on ServiceNow"). Uniform
  structure on the outside; flexible behaviour inside.
- **Mode** — a step's *default* behaviour: `AUTO`, `HYBRID`, or `MANUAL`. (See 04/05.)
- **Trigger** — the action a step performs when fired. A typed vocabulary:
  `none | http | http_flow | script | browser | webhook`. (See 05.)
- **View** — how a step renders in the UI. `generic` by default; named **custom views**
  (e.g. `cr_creation`) for steps needing bespoke fields/layout. (See 04.)
- **Lane attributes** — values belonging to the whole lane, seeded at creation
  (market, package, owner, jira_id, confluence_page). Distinct from the value bag.
- **Value bag** — per-lane key/value store of outputs **produced** by steps as they run
  (e.g. `pr_url`, `cr_no`, `build_url`), **consumed** by later steps. (See 02.)
- **Override** — a manual result that supersedes what automation detected, recorded with
  who/when/why. Available on **every** step in **every** mode. (See 02/04.)
- **Step library** — the catalogue of all step definitions, each defined once, reusable.
- **Backbone template** — the one common workflow sequence nearly every market uses.
- **Market binding** — a thin per-market delta (`use` / `add` / `skip` / `reorder` /
  `override`) that composes that market's concrete workflow from the backbone + library.
- **Lane resolution** — at lane creation, computing `market → backbone + deltas →
  concrete ordered step list` for that lane. (See 03.)
- **Post-action** — an optional follow-on action that fires when a step completes (e.g.
  on CR approval, transition the Jira story). (See 05.)

## 5. The whole picture in one diagram

```
                ┌──────────────────────────────────────────────┐
                │  DASHBOARD UI                                  │
                │   - Matrix board (full / condensed toggle)     │
                │   - Pipeline-aware lane detail (expandable)    │
                │   - Generic + custom step views                │
                │   - Config screens                             │
                └───────────────────────┬────────────────────────┘
                                        │ REST / WebSocket
                ┌───────────────────────▼────────────────────────┐
                │  RELEASE ENGINE                                 │
                │   - Lane = attributes + resolved step list      │
                │   - Per step: trigger / record / override / audit
                │   - Value bag (produces / consumes)             │
                │   - Durable state, poll/advance waiting lanes   │
                └───┬───────────────┬──────────────┬──────────────┘
                    │               │              │
            ┌───────▼──────┐ ┌──────▼──────┐ ┌─────▼────────────────┐
            │ CONFIG STORE │ │ CREDENTIAL  │ │ INTEGRATION CLIENTS  │
            │ step library │ │ STORE       │ │ Jenkins / GitHub /   │
            │ backbone /   │ │ per-user    │ │ ServiceNow /         │
            │ templates    │ │ tokens,     │ │ Confluence / Jira /  │
            │ markets +    │ │ encrypted   │ │ scan tools           │
            │ bindings     │ └─────────────┘ │ (http/script/browser)│
            │ tools        │                 └──────────────────────┘
            └──────────────┘
                    │
            ┌───────▼──────┐
            │  DATABASE    │  lane state · value bags · audit log · config
            │  (embedded   │
            │  local /     │
            │  Postgres    │
            │  shared)     │
            └──────────────┘
```

## 6. Scope of this release context

In scope: orchestration, tracking, recording, triggering, evidence aggregation across
**Jenkins, GitHub, ServiceNow, Confluence, Jira, and scan tools**, for many markets
(15+) sharing a common backbone with small per-market step differences.

Out of scope (for v1): replacing any of those tools; doing the actual AS400 build work
(that stays in Jenkins/ARCAD); approving PRs/CRs (humans still approve in GitHub/SNOW —
the dashboard tracks and links, it does not impersonate approvers).

## 7. How to read the rest of the spec

1. `01-architecture.md` — components, engine behaviour, state model, deployment, the
   language options (Python / Java) and the **four local→shared rules**.
2. `02-data-model.md` — lane, lane attributes, value bag, step instance, status, audit.
3. `03-config-schema.md` — step library, backbone/templates, market bindings &
   composition, tools, markets, trigger-type definitions, **lane-resolution validation**.
4. `04-ui-spec.md` — matrix (full/condensed), pipeline-aware lane detail, generic &
   custom views, with wireframe references.
5. `05-integration-and-triggers.md` — trigger execution, integration tiers, the script
   contract, per-user credentials, post-actions.
6. `06-build-plan.md` — phased delivery, validation rules, acceptance criteria.

## 8. Cross-cutting mandates (apply to every file)

- **Config-driven first.** Reach for configuration before code. New code is justified
  only for a genuinely new *capability* (a new field type, trigger type, custom view, or
  tool integration) — added once, then reusable from config.
- **The four local→shared rules** (defined fully in `01`) are mandatory regardless of
  language: state in a DB from day one, externalized config, multi-user-aware data model,
  separable background worker.
- **Attributability.** Every state change writes an audit entry (who/when/what/why).
- **Lane-scoped isolation.** No value or credential leaks across lanes.
