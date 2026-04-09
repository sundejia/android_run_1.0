# Folder Structure

> Last Updated: 2026-02-05

## Overview

The documentation is organized into numbered categories that follow the natural flow of software development: from ideas and iterations, through implementation, to maintenance and retirement.

```
docs/
├── 00-meta/                      # About this documentation
├── 01-product/                   # User-facing features and flows
├── 02-prompts-and-iterations/    # AI prompts and development history
├── 03-impl-and-arch/             # Technical implementation details
├── 04-bugs-and-fixes/            # Issue tracking and patterns
├── 05-changelog-and-upgrades/    # Version history and migrations
├── 06-testing-and-qa/            # Testing documentation (future)
└── 07-appendix/                  # Reference materials
```

## Detailed Structure

### 00-meta/

**Purpose:** Documentation about documentation

Contents:

- `how-we-document.md` - Philosophy and guidelines
- `folder-structure.md` - This file
- `prompt-style-guide.md` - AI interaction patterns

**When to add here:** Meta-docs about the documentation system itself

---

### 01-product/

**Purpose:** User-facing features, personas, and flows

Contents:

- Individual feature documents (dated: `YYYY-MM-DD-feature-name.md`)
- `user-flows/` - Step-by-step user journey documentation
- `decisions/` - Product decisions and rationale

**When to add here:**

- New feature implementation
- Product requirement documents
- User experience documentation
- Feature flags and rollouts

---

### 02-prompts-and-iterations/

**Purpose:** AI interaction history and prompt evolution

Contents:

- `prompts-library/` - Reusable AI prompts
- `session-logs/` - Development session summaries
- `prompt-evolution/` - How prompts changed over time

**When to add here:**

- AI agent prompt refinements
- Session summaries with Claude/GPT
- Prompt engineering experiments
- Development iteration logs

---

### 03-impl-and-arch/

**Purpose:** Technical architecture and implementation details

Contents:

- `current-architecture.md` - System architecture overview
- `key-modules/` - Deep dives into specific components
  - Avatar capture logic
  - Message parsing
  - Database interactions
  - Sidecar implementation
  - Sync workflows
  - Settings management
- `experiments/` - Experimental features and prototypes

**When to add here:**

- Architecture design documents
- Module-specific documentation
- Code flow diagrams
- Technical analysis
- Implementation notes

---

### 04-bugs-and-fixes/

**Purpose:** Issue tracking with patterns and learnings

Contents:

- `active/` - Current bugs being worked on (2026-02)
- `fixed/` - Resolved issues (archive, organized by date)
- `patterns/` - Recurring bug patterns and prevention strategies

**When to add here:**

- Bug reports and analyses
- Fix implementation notes
- Root cause analysis
- Prevention patterns

**Lifecycle:**

1. New bug → `active/`
2. Fix implemented → Update with solution
3. Verified resolved → Move to `fixed/`
4. Recurring pattern → Document in `patterns/`

---

### 05-changelog-and-upgrades/

**Purpose:** Version history and migration guides

Contents:

- `CHANGELOG.md` - Master changelog
- `upgrade-notes/` - Migration guides between versions
- `rollback-incidents/` - Post-mortems of production issues

**When to add here:**

- Release notes
- Breaking changes
- Migration guides
- Incident reports

---

### 06-testing-and-qa/

**Purpose:** Testing documentation (currently minimal, will expand)

Contents:

- `test-scenarios.md` - Integration test scenarios
- `edge-cases.md` - Known edge cases and how to handle them
- `manual-test-checklist.md` - QA procedures

**When to add here:**

- Test plans
- QA procedures
- Test coverage reports
- Edge case documentation

---

### 07-appendix/

**Purpose:** Reference materials and resources

Contents:

- `glossary.md` - Domain-specific terminology
- `resources.md` - External links and references
- `tools-setup.md` - Development environment setup
- `faq.md` - Frequently asked questions
- Development workflow guides
- Tool-specific documentation

**When to add here:**

- Reference materials
- Setup instructions
- Glossary terms
- FAQs
- External resources

## File Placement Decision Tree

```
Is it about the documentation system itself?
└─ Yes → 00-meta/

Is it user-facing or feature-related?
└─ Yes → 01-product/

Is it about AI interactions or dev history?
└─ Yes → 02-prompts-and-iterations/

Is it technical implementation or architecture?
└─ Yes → 03-impl-and-arch/

Is it a bug report or fix documentation?
└─ Yes → 04-bugs-and-fixes/

Is it about version history or migrations?
└─ Yes → 05-changelog-and-upgrades/

Is it testing-related?
└─ Yes → 06-testing-and-qa/

Is it reference material or setup info?
└─ Yes → 07-appendix/
```

## Migration Notes

### From Old Structure

The documentation was reorganized on 2026-02-05 from a flat structure to this numbered hierarchy. Mapping:

**Old → New:**

- `features/` → `01-product/`
- `prompts/` → `02-prompts-and-iterations/prompts-library/`
- `session-summary/` → `02-prompts-and-iterations/session-logs/`
- `ai/` → `02-prompts-and-iterations/prompt-evolution/`
- `architecture/` → `03-impl-and-arch/`
- `analysis/` → `03-impl-and-arch/key-modules/`
- `followup/`, `sidecar/`, `sync/`, `settings/`, `realtime-reply/` → `03-impl-and-arch/key-modules/`
- `bugs/` → `04-bugs-and-fixes/` (split by active/fixed)
- `implementation/`, `plans/` → `03-impl-and-arch/experiments/` or `02-prompts-and-iterations/prompt-evolution/`
- `development/`, `guides/` → `07-appendix/`
- `archive/` → `05-changelog-and-upgrades/old-archive/`
