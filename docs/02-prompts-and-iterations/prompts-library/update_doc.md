# Documentation Update Protocol

> **Purpose**: Systematic instructions for AI agents to update and maintain the `/docs` folder as the project evolves.
> **Usage**: Tell the AI: "Run @docs/prompts/update_doc.md"

## Prerequisites

Before starting, ensure you understand the project's documentation philosophy:

- **Foundation documents** (README.md, plan.md, milestones.md, agents.md) are the primary source of truth
- All `/docs` content should EXTEND, not DUPLICATE foundation documents
- Documentation grows WITH the project, not ahead of it

## Update Checklist

### 1. Scan Foundation Documents for Changes

```bash
# Check for recent updates in foundation docs
git log -n 10 --oneline -- README.md plan.md milestones.md agents.md
```

**TODO**:

- [ ] Read @README.md for new features, endpoints, or configuration changes
- [ ] Read @milestones.md for recent fixes and completed work
- [ ] Read @plan.md for architecture updates and phase progress
- [ ] Read @agents.md for new development standards or protocols

### 2. Audit Current Documentation State

```bash
# List all documentation files
find docs/ -name "*.md" -type f | sort
```

**TODO**:

- [ ] Check if any planned (=�) items in docs/INDEX.md are now implemented
- [ ] Identify outdated content that contradicts foundation documents
- [ ] Find gaps where new features lack documentation

### 3. Archive Resolved Issues

```bash
# Find bug reports older than 30 days that are marked as FIXED
grep -l "FIXED\|RESOLVED" docs/troubleshooting/*.md
```

**TODO**:

- [ ] Move resolved bug reports to `docs/troubleshooting/archive/`
- [ ] Keep only active debugging guides in main troubleshooting folder
- [ ] Update INDEX.md to reflect archived count

### 4. Update Foundation Documents Where Needed

**TODO**:

- [ ] If new bugs fixed → Add to @milestones.md with date, symptoms, fix, and test reference
- [ ] If documentation created → Update @README.md docs section if it's a major new guide
- [ ] If new development pattern established → Add to @agents.md dos/don'ts or protocols
- [ ] If architecture phase completed → Update @plan.md phase status and add completion notes
- [ ] If new configuration added → Update @README.md configuration section with examples
- [ ] If timeline/UI parity changed → Add a note on the per‑user timeline and tests that assert it

### 5. Update Based on Recent Changes

#### A. New Features (from README.md/milestones.md)

**TODO**:

- [ ] If new API endpoints added → Update API docs in relevant documentation
- [ ] If new configuration options → Update configuration documentation
- [ ] If new UI features → Update user interface documentation
- [ ] If security features implemented → Update security documentation status

#### B. Architecture Progress (from plan.md)

**TODO**:

- [ ] If architecture progress � Update relevant progress files in `docs/arch/`
- [ ] If new architecture decisions → Create new architecture document in `docs/arch/`

#### C. Bug Fixes (from milestones.md)

**TODO**:

- [ ] Extract common troubleshooting patterns → Add to troubleshooting documentation
- [ ] Document new debugging techniques → Update debugging guides
- [ ] Add bug report under `do../04-bugs-and-fixes/active/` with root cause, failed attempts, final fix, and tests

#### D. Testing Updates (from agents.md)

**TODO**:

- [ ] New test patterns → Update testing documentation
- [ ] New setup requirements → Update setup guides
- [ ] Reference new tests in relevant documentation

### 6. Update INDEX.md Status Indicators

**TODO**:

- [ ] Change =� (Planned) to =� (In Progress) for items being worked on
- [ ] Change =� (In Progress) to  (Complete) for finished items
- [ ] Update phase status in Growth Strategy section
- [ ] Ensure all file paths in INDEX.md are correct

### 7. Cross-Reference Validation

**TODO**:

- [ ] Verify all links in INDEX.md point to existing files
- [ ] Check that new docs reference foundation documents appropriately
- [ ] Ensure no duplication between docs and foundation files
- [ ] Validate that tutorials reference current code/config structure

### 8. Content Migration

**TODO**:

- [ ] Move any misplaced files to appropriate folders:
  - Bug reports → `do../04-bugs-and-fixes/active/` (organized by date)
  - Feature documentation → `do../01-product/`
  - Architecture docs → `do../03-impl-and-arch/`
  - Guides → `docs/guides/`
- [ ] Remove empty folders
- [ ] Move outdated docs to `docs/legacy/` with explanatory note

### 9. Final Quality Check

**TODO**:

- [ ] Run this command to check for broken references:
  ```bash
  grep -r "\[.*\](.*\.md)" docs/ | grep -v "http" | while read -r line; do
    # Extract file path and check if target exists
    echo "$line" | grep -o '([^)]*\.md)' | tr -d '()' | while read -r ref; do
      if [ ! -f "docs/$ref" ] && [ ! -f "$ref" ]; then
        echo "Broken reference: $ref in $line"
      fi
    done
  done
  ```
- [ ] Ensure consistent formatting (headers, lists, code blocks)
- [ ] Check that all status indicators (, =�, =�) are current

### 10. Update This Protocol

**TODO**:

- [ ] Update the "Last Protocol Run" timestamp at the bottom of this file
- [ ] If new update patterns discovered → Add them to relevant sections above
- [ ] If new file types or folders created → Add migration rules in section 8
- [ ] If new foundation documents added → Include them in section 1 and throughout

## Update Commands Summary

```bash
# 1. Start with foundation docs
cat README.md | head -100  # Check recent changes
tail -50 milestones.md     # Review latest fixes
grep "Phase" plan.md       # Check phase progress

# 2. Update foundation docs if needed
# - Add new fixes to milestones.md
# - Update README.md configuration/docs sections
# - Add new protocols to agents.md
# - Update plan.md phase status

# 3. Archive old issues (bugs are already organized in do../04-bugs-and-fixes/active/)

# 4. Update INDEX.md
# - Update status indicators
# - Fix broken paths
# - Update phase progress

# 5. Validate structure
ls -la docs/*/           # Check folder organization
find docs -type d -empty # Find empty folders to remove

# 6. Update this protocol's timestamp
# Edit the "Last Protocol Run" line at the bottom of docs/prompts/update_doc.md
```

## Completion Report Template

After running this protocol, report:

```markdown
## Documentation Update Report

### Foundation Documents Updated

- README.md: [list sections updated - config, docs, troubleshooting, etc.]
- milestones.md: [list new fixes/features added with dates]
- plan.md: [list phase status updates or architecture changes]
- agents.md: [list new protocols or standards added]

### Foundation Changes Incorporated into /docs

- From README.md: [list new features/changes reflected in docs]
- From milestones.md: [list fixes/improvements documented]
- From plan.md: [list architecture updates reflected]
- From agents.md: [list new standards incorporated]

### Files Updated

- [file path]: [brief description of changes]

### Files Archived

- Moved X bug reports to troubleshooting/archive/

### Status Changes in INDEX.md

- [item]: =� � =� (now in progress)
- [item]: =� �  (now complete)

### New Documentation Created

- [file path]: [purpose]

### Issues Found

- [any broken links or inconsistencies]
```

## Important Reminders

1. **UPDATE foundation documents** (README.md, plan.md, milestones.md, agents.md) when implementing new features or fixes
2. **NEVER duplicate** content between foundation docs and /docs folder
3. **ALWAYS reference** foundation documents when extending them
4. **ONLY create** new docs when documenting genuinely new information
5. **ARCHIVE aggressively** - keep only active/current content visible
6. **UPDATE INDEX.md** every time - it's the navigation hub
7. **BIDIRECTIONAL updates** - Foundation docs and /docs folder should cross-reference each other

---

**Last Protocol Run**: 2026-02-05 (Followup Resource ID Search Button & Queue Manager Blacklist Integration)
**Next Suggested Run**: After the next bug fix or feature enhancement
