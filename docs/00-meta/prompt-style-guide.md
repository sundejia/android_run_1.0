# Prompt Style Guide

> Last Updated: 2026-02-05

## Principles for AI Interaction

This guide defines how we interact with AI assistants (Claude, GPT, etc.) to maintain consistency and effectiveness across development sessions.

## Core Philosophy

**Context-Rich, Output-Focused Prompts**

Our prompts balance between:

- Enough context for the AI to understand the system
- Clear, specific output requirements
- Avoiding overwhelming detail that reduces effectiveness

## Prompt Components

### 1. Context Setting

Always start with relevant context:

- Current working directory
- Type of project (WeCom automation framework)
- Relevant architectural patterns
- Key constraints or requirements

### 2. Clear Objective

State what you want explicitly:

```
"Implement X feature that does Y"
"Analyze Z component and identify performance issues"
"Refactor A module to improve B"
```

### 3. Success Criteria

Define what good looks like:

- Tests pass
- Code follows project patterns
- Documentation updated
- No breaking changes

### 4. Output Format

Specify expected output:

- Code files with full paths
- Step-by-step implementation plan
- Analysis with recommendations
- Diagrams (if applicable)

## Prompt Templates

### For Feature Implementation

```markdown
# Feature Request: [Feature Name]

## Context

We're building a WeCom automation framework using [tech stack].
The current implementation is in [location].

## Requirements

Implement [feature] that should:

1. [Requirement 1]
2. [Requirement 2]
3. [Requirement 3]

## Constraints

- Must use existing [service/module] patterns
- Follow [architectural principle]
- Handle [edge case]

## Expected Output

1. Implementation plan with file list
2. Code changes with full paths
3. Tests added/modified
4. Documentation updates needed

## Related Files

- [Key file 1]
- [Key file 2]
- [Existing similar feature]
```

### For Bug Analysis

```markdown
# Bug Investigation: [Bug Title]

## Problem Description

[What's happening vs what should happen]

## Context

- When it occurs: [timing/conditions]
- Impact: [severity/affected users]
- Recent changes: [relevant commits]

## Files Involved

- [File 1]: [role]
- [File 2]: [role]

## Investigation Steps

1. Analyze the code flow
2. Identify root cause
3. Propose fix with explanation
4. Suggest test cases

## Output Format

Provide:

- Root cause analysis
- Proposed fix (code diff preferred)
- Test cases to verify
- Prevention strategies
```

### For Refactoring

```markdown
# Refactor Request: [Module/Component]

## Current State

[What exists now, what's problematic]

## Goals

- Improve [maintainability/performance/readability]
- Reduce [complexity/coupling/duplication]
- Maintain [existing behavior/compatibility]

## Constraints

- Don't break [API/feature/behavior]
- Follow [pattern/principle]
- Update [tests/docs]

## Expected Output

1. Refactoring plan
2. Code changes with rationale
3. Migration guide if breaking
4. Tests to verify correctness
```

## Best Practices

### DO ✅

- Provide file paths when referencing code
- Share relevant code snippets
- State constraints explicitly
- Ask for reasoning, not just code
- Specify output format
- Link to similar patterns in codebase

### DON'T ❌

- Paste entire files unless necessary
- Assume AI knows recent changes
- Be vague about requirements
- Skip context about architecture
- Forget to mention edge cases
- Omit error handling requirements

## Context Building Strategies

### 1. Progressive Disclosure

Start with high-level goal, add detail as needed:

```
"Implement image download feature"
→ "Download images during sync, save to resources/"
→ "Handle deduplication with SHA256, support PNG/JPEG"
```

### 2. Reference-Based

Point to existing implementations:

```
"Similar to voice handler (services/message/handlers/voice.py),
implement video handler with these differences: ..."
```

### 3. Architectural Reminders

Remind AI of patterns:

```
"Remember our three-layer architecture:
- CLI layer for commands
- Services layer for business logic
- Core layer for primitives
Place new service in services/ accordingly."
```

## Session Management

### Starting a New Session

1. Copy relevant context from CLAUDE.md
2. State current working directory
3. Mention active branch or feature
4. State what you're trying to achieve

### Mid-Session Clarification

When AI goes off-track:

- "Actually, we need to follow [pattern] instead"
- "Let me clarify: [specific requirement]"
- "Looking at [existing code], we should [approach]"

### Session Wrap-Up

Ask for:

- Summary of changes made
- Files modified
- Tests to run
- Documentation to update
- Potential follow-up tasks

## Code Review Prompts

### Before Implementation

```
"Review this plan for [feature]:
[Plan details]

Check for:
- Architectural consistency
- Edge cases missed
- Performance concerns
- Testing gaps"
```

### After Implementation

```
"Review this implementation of [feature]:
[Code or file paths]

Check for:
- Correctness
- Error handling
- Code style consistency
- Documentation completeness
- Test coverage"
```

## Troubleshooting Prompts

### Debugging

```
"I'm seeing this error:
[Error message]

Context:
- What I was doing: [action]
- Expected behavior: [expectation]
- Recent changes: [commits]

Help me:
1. Understand the error
2. Find the root cause
3. Fix the issue
4. Prevent recurrence"
```

### Performance Issues

```
"[Component/Operation] is slow:
[Metrics or observations]

Analyze:
- Where's the bottleneck?
- What's causing it?
- How can we optimize?

Consider:
- Caching opportunities
- Algorithm improvements
- Database queries
- Network calls"
```

## AI-Specific Notes

### Claude (Anthropic)

- Good at: Code reasoning, architectural discussions
- Prefers: Context over verbosity
- Use for: Design discussions, refactoring, analysis

### GPT-4

- Good at: Quick implementations, boilerplate
- Prefers: Clear, step-by-step instructions
- Use for: Straightforward features, code generation

### When to Switch

- Claude → GPT: Simple, well-defined tasks
- GPT → Claude: Complex reasoning, architecture

## Example Interactions

See `02-prompts-and-iterations/session-logs/` for real examples of effective AI interactions.

## Updating This Guide

When you find a prompt pattern that works well:

1. Document it here
2. Add example to `02-prompts-and-iterations/prompts-library/`
3. Share with team

## Related Documentation

- [How We Document](how-we-document.md)
- [Session Logs](../02-prompts-and-iterations/session-logs/)
- [Prompt Library](../02-prompts-and-iterations/prompts-library/)
