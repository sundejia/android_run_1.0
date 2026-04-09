# 04-Bugs and Fixes

This directory tracks bugs, issues, and their resolutions. Organized by status and date for easy tracking and pattern recognition.

## Structure

### `active/`

Currently open bugs being investigated or fixed (2026-02).

Naming: `YYYY-MM-DD-bug-description.md`

### `fixed/`

Resolved bugs, organized chronologically.

Naming: `YYYY-MM-DD-bug-description.md`

### `patterns/`

Recurring bug patterns and prevention strategies.

## Bug Lifecycle

```
New Bug → active/ → In Progress → Fixed → fixed/
                         ↓
                    Root Cause Analysis
                         ↓
                    Prevention → patterns/
```

## Bug Document Template

```markdown
# Bug: [Title]

> Status: Open | In Progress | Fixed | Wontfix
> Reported: YYYY-MM-DD
> Severity: P0 (Critical) | P1 (High) | P2 (Medium) | P3 (Low)
> Related: [Feature](../01-product/xxx.md) | [Commit](link)

## Problem Description

[What's happening? What should happen?]

## Impact

- Who affected: [Users/Systems]
- Severity: [Why this severity?]
- Frequency: [Always/Sometimes/Rarely]

## Reproduction Steps

1. [Step 1]
2. [Step 2]
3. [Step 3]

## Root Cause

[What's actually causing the issue?]

## Solution

[How did we fix it? Code changes, configuration, etc.]

## Implementation

- Files changed: [list]
- Pull requests: [links]
- Tests added: [yes/no]

## Verification

[How do we verify it's fixed?]

## Prevention

[How do we prevent this in the future?]

## Time to Resolution

- Reported: YYYY-MM-DD
- Fixed: YYYY-MM-DD
- Duration: [X days]

## Lessons Learned

[What did we learn? What should we do differently?]
```

## When to Document

### Document bugs when:

1. Impact is P1 or higher
2. Requires non-trivial investigation
3. Has learning value
4. Reveals architectural weakness
5. Requires coordination to fix

### Skip documentation for:

- Typos caught immediately
- Trivial fixes (<5 minutes)
- Test-only issues
- Already documented patterns

## Pattern Recognition

When you see 3+ bugs with similar root causes:

1. Create document in `patterns/`
2. Analyze common factors
3. Propose systemic prevention
4. Update architecture/docs to prevent recurrence

## Active Bug Management

### Weekly Review

- Check all bugs in `active/`
- Update status
- Move resolved to `fixed/`
- Identify patterns

### Priority Definitions

- **P0**: Data loss, security, production down
- **P1**: Major feature broken, significant impact
- **P2**: Minor feature broken, workaround exists
- **P3**: Cosmetic, nice-to-have

## Metrics

Track in each bug:

- Time to detection
- Time to fix
- Time to verify
- Number of users affected
- Root cause category

## See Also

- [How We Document](../00-meta/how-we-document.md)
- [Folder Structure](../00-meta/folder-structure.md)
- [INDEX.md](../INDEX.md)
