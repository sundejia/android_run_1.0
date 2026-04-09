# How We Document

> Last Updated: 2026-02-05

## Philosophy

Our documentation follows the **vibe coding style** - organized by purpose, not by technology. Each document has a clear reason for existing and lives in a predictable location.

## Core Principles

1. **Single Source of Truth** - One canonical document per topic
2. **Purpose-Over-Technology** - Organize by WHY, not WHAT
3. **Living Documents** - Docs evolve with the codebase
4. **Traceability** - Link bugs to features, features to decisions
5. **Discoverability** - If you need it, you can find it in under 30 seconds

## Document Lifecycle

```
Idea → 02-prompts-and-iterations → Implementation → 04-bugs-and-fixes → 07-appendix
         (session-logs)               (03-impl-and-arch)     (patterns)        (glossary)
```

## Naming Conventions

### Features

- Format: `YYYY-MM-DD-feature-name.md`
- Example: `2026-02-05-ui-improvements.md`
- Location: `01-product/`

### Bugs

- Format: `YYYY-MM-DD-bug-description.md`
- Example: `2026-02-04-message-sent-to-wrong-person.md`
- Location: `04-bugs-and-fixes/active/` (current issues) or `04-bugs-and-fixes/fixed/` (resolved)

### Technical Analysis

- Format: `topic-analysis.md` or `topic-explanation.md`
- Example: `avatar-logic-analysis.md`
- Location: `03-impl-and-arch/key-modules/`

## Writing Guidelines

### 1. Start with Context

Every document should answer:

- **What** problem does this address?
- **Why** does it exist?
- **Who** is it for?
- **When** was it last updated?

### 2. Use Front Matter

```markdown
> Last Updated: YYYY-MM-DD
> Status: Draft | Active | Deprecated
> Related: [link-to-other-doc](path/to/doc.md)
```

### 3. Link Generously

- Link to related features
- Link to bugs that spawned fixes
- Link to implementation details
- Link to decisions made

### 4. Include Examples

- Code snippets
- Before/after comparisons
- Screenshots where helpful
- Use cases

### 5. Update Protocol

When code changes:

1. Update related documentation immediately
2. Add "Last Updated" timestamp
3. If breaking change, note migration path
4. Cross-reference related docs

## Review Process

### Before Creating New Doc

1. Search INDEX.md - does it already exist?
2. Check appropriate category folder
3. Consider if it should update existing doc instead

### After Creating Doc

1. Add to INDEX.md
2. Link from related docs
3. Update any relevant README files
4. Create README if new subdirectory

## Anti-Patterns to Avoid

❌ **Don't** duplicate information across multiple docs
❌ **Don't** create docs without updating INDEX.md
❌ **Don't** leave outdated docs without "Deprecated" notice
❌ **Don't** bury important info in obscure locations
❌ **Don't** write docs from memory - verify with code

## Template for New Documents

```markdown
# Title

> Last Updated: YYYY-MM-DD
> Status: Draft | Active | Deprecated
> Related: [link](path)

## Context

[Why this doc exists, what problem it solves]

## Details

[Main content]

## Implementation

[How it's implemented, if applicable]

## Examples

[Concrete examples]

## Related

- [Feature X](../01-product/feature.md)
- [Bug Y](../04-bugs-and-fixes/active/bug.md)
```

## Maintenance

### Weekly

- Review `04-bugs-and-fixes/active/`
- Move resolved bugs to `fixed/`
- Update INDEX.md

### Monthly

- Audit for stale docs
- Consolidate duplicates
- Update glossary

### Per Release

- Update `05-changelog-and-upgrades/CHANGELOG.md`
- Archive old decisions
- Review architecture docs
