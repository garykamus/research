# 04 — UI Specification

> Two primary screens — **Matrix board** (overview) and **Pipeline-aware lane detail**
> (one release) — plus the **generic / custom view** mechanism for steps. Wireframes
> were reviewed and approved; this file is the build reference. Layout is described
> structurally.
>
> **Implementation:** this is a **native PySide6 (Qt) desktop UI** (`01` §6), not a web
> page. Realize each design below with Qt widgets — matrix = `QTableView`/`QTreeView`,
> lane detail = an expandable list/tree, custom views = `QDialog`/panels. Do **not** use a
> web view. The UI is thin presentation that calls the core's `ReleaseService` in-process.

---

## 1. Screen map

```
Matrix board  ──click a lane row──►  Lane detail (pipeline-aware)
   │                                     │
   │                                     └─ each step expands → step view
   │                                          (generic OR custom)
   └─ Config screens (markets / tools / workflow)   [Phase 3+]
```

Navigation is **fixed**. Workflow changes (add/remove/reorder steps) change *content*,
never add tabs or screens. (Principle: config drives the flow.)

## 2. Matrix board (overview)

Purpose: see **all lanes at once**, and how far each has progressed.

### Layout
- Rows = lanes. Each row: `market` · `ARCAD package` · progress display · status summary
  · `jira_id` (clickable pill) · owner.
- A header with: title, filter box, "New lane" action, and a **density toggle**
  (`full` / `condensed`).
- A legend for status colours.

### Two density modes (toggle; **condensed is the default**)
- **Condensed (default):** each lane shows a single **segmented progress bar** (one
  segment per step, coloured by status) plus a plain-language status — e.g.
  `6/9 · waiting · Submit`. Scales cleanly to any step count and to **heterogeneous step
  counts across markets** (some markets have extra/skipped steps). This is why it is the
  default at 15+ markets.
- **Full:** one status box per step, column-aligned across lanes — good for spotting "are
  multiple lanes stuck at the same step?" Best when step counts are uniform/small. Where
  a market skips a step, that cell shows `n/a` (SKIPPED).

### Status colours (consistent across both screens)
`pending` (neutral/outlined) · `in progress` (info) · `done` (success) ·
`waiting` — human gate (warning) · `suspended` — external hold (distinct neutral/muted,
not danger) · `blocked` (danger).

### Behaviour
- Click a row → open that lane's detail.
- Filter/group by market, arcad_package, status, owner (at minimum: free-text filter +
  status filter).
- The set of steps shown is driven by config; adding a step adds a segment/column
  everywhere automatically.

**Wireframe references:** `matrix_board_wireframe` (full) and
`matrix_condensed_progressbar_wireframe` (condensed, default).

## 3. Lane detail (pipeline-aware)

Purpose: work and monitor **one release** — trigger steps, record results, see history,
follow value flow.

### Layout
- Header: back link, `market / arcad_package`, owner, `jira_id` link, `confluence_page`
  link, a summary line (`6/8 done · waiting on CR approval · links collected: N ·
  overrides: N`), a **refresh status** action (forces live re-check — see `01` state
  model), and an **actions** menu for **lane-level actions** (e.g. *Rename package* —
  prompts for the new name + reason; see `02` §6a). The displayed `arcad_package` updates
  in place after a rename.
- Body: the lane's resolved steps as a **vertical sequence** with **connectors** between
  them (showing pipeline order).
- Each step row (collapsed) shows: status node, number + label, **mode badge**
  (AUTO/HYBRID/MANUAL), a **custom-view badge** if applicable, recorded-link pills, any
  flags (e.g. "override applied"), a live indicator (e.g. "polling") on waiting gates,
  and an expand chevron. An **`external_hold`** step shows a `SUSPENDED` state with a
  "waiting on external process" note and, when applicable, a **Resume / continue** action
  plus any resume-capture fields (see `05` §1.7).
- **Value-flow notes** render inline where relevant: a producing step shows
  `cr_no → feeds steps 6, 8`; a consuming step shows `uses cr_no from step 4`. (Borrowed
  from a DAG view, without the DAG's inability to scale.)

### Expand-to-act (the working surface)
Clicking a step expands it **in place** into its **view** (generic or custom), which
contains the actions. The expanded panel always offers, as applicable:
- a **primary action** — `trigger` (AUTO/HYBRID) or `Open pre-filled page` (MANUAL
  Tier-3) or the custom view's own action (e.g. `Create CR`);
- **mark done** — manually set the step complete;
- **override** — force a result; **requires a reason** (attributability); records who/when;
- **fields** — inputs to capture values/links (per the view definition);
- relevant **value-flow** context (what it produces / consumes).

The expand model is **inline** (not separate tabs/pages) — confirmed in review.

**Wireframe references:** `lane_detail_pipeline_aware_wireframe` (resting) and
`lane_detail_pipeline_expanded_step_wireframe` (expanded, showing custom + manual steps).

## 4. Views: generic by default, custom by exception

A step's `view` field selects how its expanded panel renders. A **view registry** maps
view names → components. Config references views by name.

### Generic view (default — covers ~most steps)
Reads the step definition and `view_config.fields` and renders:
- a trigger button (if a trigger exists) / manual record controls;
- input fields for each declared field (`text / url / number / dropdown / checkbox /
  datetime`);
- link buttons (from `link_buttons`);
- mark-done + override controls.
Adding fields to a generic step is **config only** (`view_config.fields`).

### Custom views (built once, reused via config)
For steps needing bespoke layout / pre/post sub-steps / validation. Named, registered,
referenced from config. Examples required for v1:
- **`cr_creation`** — a ServiceNow CR form: customizable fields (short description,
  assignment group, planned start/end, plus per-market extras via `override`),
  validation, then a `Create CR` trigger; on success captures `cr_no`, `cr_url`.
- **`evidence_update`** — choose/preview which captured values (scan URLs, CR no.,
  evidence links) to publish to the CR audit page, then trigger.
- **`confluence_release`** — choose/preview fields to publish to the Confluence release
  page, then trigger (or open pre-filled page if no API).

**Customizable fields are a hard requirement:** the fields shown in a custom view (e.g.
CR-creation fields, audit-page fields) must be configurable — driven by `view_config`
and per-market `override.extra_fields` — without code changes. Building a *new* custom
view layout is a one-time code addition; changing its *fields* is config.

### When config suffices vs. code
| Change | Config only? |
|---|---|
| Add/remove/reorder a step | Yes |
| Change a step's mode | Yes |
| Change a trigger URL / params | Yes |
| Add fields / link buttons to a (generic or existing custom) view | Yes |
| Add a step using an existing trigger type & tool | Yes |
| New field type or trigger type | Code once, then config |
| New custom view layout | Code once, then config |
| New tool with novel auth | Code once, then config |

## 5. Mode badges & semantics (display)
- `AUTO` — dashboard triggers and auto-advances on detected success.
- `HYBRID` — dashboard triggers and tracks what it can, but waits for human
  confirmation / a supplied value before advancing (e.g. scans, CR steps).
- `MANUAL` — human performs elsewhere, records result/links here (e.g. no-API tools).
Mode is the step's *default*; every step still supports trigger-if-possible, manual-set,
and override regardless of badge.

## 6. Optional later view — timeline lens
A toggle that lays lanes as horizontal tracks with steps along a time axis, for spotting
stalls/bottlenecks ("stuck in CR approval 3 days"). Monitoring aid, not a working
surface. Defer beyond v1 unless SLA tracking is prioritized.

## 7. Accessibility & clarity
- Status must not rely on colour alone — pair with icon/label (e.g. node icon + status
  word).
- Every recorded URL is a clickable link; a per-lane links summary aggregates them.
- Long flows: condensed matrix default; lane detail scrolls — keep the header/ summary
  sticky.

## 8. Explicitly NOT Kanban
Do not implement a drag-between-status-columns board. Steps auto-earn progress and are
sequenced/dependent; drag-to-change-status is meaningless and unsafe here. The pipeline
+ matrix model is the approved design.
