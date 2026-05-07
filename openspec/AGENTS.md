# OpenSpec Workflow (BOSS 直聘 招聘自动化)

This file is the canonical OpenSpec guide for this repository. The root
`AGENTS.md` and `CLAUDE.md` reference this file. Keep it updated when
conventions evolve.

## Purpose

OpenSpec is the lightweight change-proposal workflow used in this repo to
keep large, multi-step changes auditable, test-driven, and merge-friendly.

Every milestone in the BOSS Zhipin pivot ships as one `changes/<id>-<slug>/`
directory plus an incremental commit group. Capability-level contracts live
under `specs/`.

## Directory Layout

```
openspec/
├── AGENTS.md                # this file
├── specs/                   # stable capability specs (one .md per capability)
│   └── <capability>.md
└── changes/
    ├── 0001-pivot-foundation/
    │   ├── proposal.md      # WHY + WHAT (1-2 pages)
    │   ├── tasks.md         # ordered checklist with TDD red→green slots
    │   ├── design.md        # architecture, data flow, mermaid, decisions
    │   └── specs/           # NEW or UPDATED capability specs (will be
    │                          merged into ../../specs/ on completion)
    ├── 0002-recruiter-bootstrap/
    └── ...
```

Active proposals stay under `changes/`. Once a milestone is fully shipped
and merged to `main`, move its directory to `changes/_archive/<id>-<slug>/`
(do not delete) and copy any `specs/*.md` it contained into `openspec/specs/`.

## Naming

- Change ID: 4-digit zero-padded, monotonically increasing (`0001`, `0002`, ...).
- Slug: kebab-case, ≤ 4 words, descriptive (`recruiter-bootstrap`, `job-sync`).
- Capability spec filename: kebab-case noun phrase (`device-bootstrap.md`,
  `job-sync.md`).

## Required Files In Each Change

### `proposal.md`

```
# <Title>

## Why
<1 paragraph rationale: what user-visible problem does this solve?>

## What
<bullet list of new/changed behaviors>

## Out Of Scope
<bullet list of things explicitly NOT in this change>

## Success Criteria
<measurable signals: tests added, coverage delta, latency, etc.>
```

### `tasks.md`

Ordered checklist using `- [ ]` items. Each task should fit one commit.
Group tasks by RED → GREEN → REFACTOR phases.

```
## Phase 1: RED (failing tests)
- [ ] Add fixture tests/fixtures/boss/<page>/<scenario>.json
- [ ] Write tests/unit/boss/parsers/test_<x>.py covering happy path + 2 edge cases

## Phase 2: GREEN (minimal implementation)
- [ ] Implement src/boss_automation/parsers/<x>.py until tests pass

## Phase 3: REFACTOR / WIRE-UP
- [ ] Wire into orchestrator
- [ ] Add backend route
- [ ] Add frontend view
- [ ] Add integration test (marked @pytest.mark.integration)
```

### `design.md`

Free-form architecture document. Required sections:
- Context & Constraints
- Architecture (mermaid diagram preferred)
- Data Model Changes (SQL DDL or repository signatures)
- Error Handling & Safety (especially blacklist/quota guards)
- Testing Strategy (what fixtures, what mocks, what integration paths)
- Risks & Mitigations

### `specs/<capability>.md` (optional)

Only present if this change introduces or modifies a capability spec.
Format:

```
# Capability: <Name>

## Purpose
<one paragraph>

## Public API
<function/class signatures, REST endpoints, or event schemas>

## Invariants
<rules that must always hold; reference guardrails>

## Test Matrix
| Scenario | Inputs | Expected | Test |
|----------|--------|----------|------|
```

## TDD Discipline

Hard rules for every change in this repo:

1. No production code without a failing test that motivates it.
2. Every commit MUST leave the tree green: `pytest`, `vitest`, and `ruff`
   all pass. CI enforces this.
3. Coverage gate: project ≥ 80%; `src/boss_automation/parsers/` and
   `src/boss_automation/services/` ≥ 90%.
4. Real-device interaction is forbidden in unit tests. Use the
   `tests/_fixtures/loader.py` to load dumped UI trees.
5. Integration tests requiring a real device MUST be marked
   `@pytest.mark.integration` and live under `tests/integration/`. CI skips
   them; local runs use `pytest -m integration`.
6. Each commit message references the change ID, e.g.
   `feat(0002): parse recruiter profile from main page tree`.

## When To Open A Change

Open a new `changes/<id>-<slug>/` directory when the work matches any of:
- New milestone (M1, M2, ...).
- New capability or contract.
- Breaking change to schema, REST API, WebSocket message type, or settings key.
- Architecture shift affecting > 5 files outside one module.

Bug fixes and small additive features that touch a single capability do NOT
require an OpenSpec change; they go through normal PR with tests.

## Definition Of Done For A Change

- [ ] All `tasks.md` items checked.
- [ ] CI green on the change branch.
- [ ] Coverage thresholds met.
- [ ] `design.md` reflects the as-shipped architecture (no stale claims).
- [ ] Capability specs (if any) copied into `openspec/specs/` and the
      change directory moved to `changes/_archive/`.
- [ ] Migration notes (if any schema changes) added to
      `docs/05-changelog-and-upgrades/`.
