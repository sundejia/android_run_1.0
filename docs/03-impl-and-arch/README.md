# 03-Implementation and Architecture

This directory contains technical documentation about the system's architecture, implementation details, and deep dives into specific components.

## Contents

### Core Architecture

- **`current-architecture.md`** - High-level system architecture overview

### Subdirectories

#### `key-modules/`

Deep dives into specific components and subsystems:

- Avatar capture and storage
- Message parsing and handlers
- Database schema and operations
- Sidecar real-time monitoring
- Sync workflows and checkpointing
- Settings management
- AI reply integration
- Follow-up message system
- Realtime reply orphan subprocess cleanup (`key-modules/realtime-reply-orphan-cleanup.md`) — avoids duplicate `realtime_reply_process.py` trees after uvicorn reload

Each module document includes:

- Purpose and responsibilities
- Key classes and functions
- Data flow
- Dependencies
- Configuration
- Testing approach
- Known limitations

#### `experiments/`

Experimental features, prototypes, and exploratory work:

- Proof of concepts
- A/B test documentation
- Performance experiments
- Alternative implementations

## When to Add Here

Add technical documentation when:

1. Designing new major components
2. Analyzing existing subsystems
3. Documenting complex algorithms
4. Explaining data flow
5. Running experiments

## Template for Module Documentation

```markdown
# [Module Name]: Overview

> Last Updated: YYYY-MM-DD
> Component: [Service/Module/Class]
> Status: Stable | Experimental | Deprecated

## Purpose

[What problem does this module solve? What are its responsibilities?]

## Architecture

[High-level design, key components, how they fit together]

## Key Classes/Functions

### ClassName

- **Purpose**: [What it does]
- **Key Methods**:
  - `method_name()`: [description]
  - `method_name()`: [description]

### FunctionName

- **Purpose**: [What it does]
- **Parameters**: [params and types]
- **Returns**: [return type and meaning]

## Data Flow
```

[Step 1] → [Step 2] → [Step 3]

```

## Dependencies
- Depends on: [module/service]
- Used by: [module/service]
- External: [libraries/services]

## Configuration
[Config options, environment variables, settings]

## Error Handling
[How errors are handled, edge cases]

## Performance Characteristics
- Time complexity: [O(n) etc]
- Bottlenecks: [what to watch for]
- Optimizations: [what's been done]

## Testing
- Unit tests: [location]
- Integration tests: [location]
- Manual testing: [approach]

## Known Issues
[List any known limitations or bugs]

## Future Improvements
[Planned enhancements, refactoring needs]

## Related Documentation
- [Feature X](../01-product/feature.md)
- [Bug Y](../04-bugs-and-fixes/active/bug.md)
- [Analysis Z](key-modules/analysis.md)
```

## See Also

- [How We Document](../00-meta/how-we-document.md)
- [Folder Structure](../00-meta/folder-structure.md)
- [INDEX.md](../INDEX.md)
