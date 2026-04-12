# Documentation Index

> **WeCom Automation Framework Documentation**
> Last Updated: 2026-04-12 (Multi-resolution group invite; DroidRun port propagation; **auto group invite returns scan to Private Chats**; docs synced)

---

## Quick Navigation

- **[Product Features](#01-product---features-and-user-experience)** - What we build
- **[Implementation](#03-implementation-and-architecture)** - How it works
- **[Bugs & Fixes](#04-bugs-and-fixes)** - Issues and resolutions
- **[Changelog](#05-changelog-and-upgrades)** - Version history
- **[Reference](#07-appendix)** - Glossary, tools, setup

---

## 00-Meta - Documentation About Documentation

| Document                                            | Description                               |
| --------------------------------------------------- | ----------------------------------------- |
| [How We Document](00-meta/how-we-document.md)       | Philosophy, guidelines, writing standards |
| [Folder Structure](00-meta/folder-structure.md)     | Detailed explanation of organization      |
| [Prompt Style Guide](00-meta/prompt-style-guide.md) | AI interaction patterns and templates     |

---

## 01-Product - Features and User Experience

### Recent Features (2026)

| Feature                                                                                                     | Status      | Date       | Description                                                                                                                                                                                                      |
| ----------------------------------------------------------------------------------------------------------- | ----------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [System Robustness Fixes](implementation/2026-04-09-system-robustness-fixes.md)                             | ✅ Complete | 2026-04-09 | AI circuit breaker, failure metrics, process auto-restart, heartbeat monitoring API, AI health checks, night-mode Sidecar timeout; 2026-04-10 follow-up: `SidecarSettings` matches DB keys, AI error logging fix |
| [Multi-Resolution Group Invite Fix](bugs/2026-04-12-multi-resolution-group-invite-and-droidrun-port-fix.md) | ✅ Complete | 2026-04-12 | Resolution-aware UI bounds for group invite; DroidRun per-device port propagation; full 10-step E2E on 720p+1080p devices                                                                                        |
| [Auto Group Invite → Private Chats List](bugs/2026-04-12-auto-group-invite-private-chats-navigation.md)     | ✅ Complete | 2026-04-12 | After auto group invite in realtime reply, restore Private Chats filter (`restore_navigation`, stronger `ensure_on_private_chats`, detector Step 7)                                                              |
| [Media Auto-Actions](features/media-auto-actions.md)                                                        | ✅ Complete | 2026-04-05 | Auto-blacklist + Android group invite; multi-resolution + DroidRun (2026-04-12); private-chats navigation after invite (2026-04-12)                                                                              |
| [Follow-up Message Deduplication](01-product/followup-deduplication-feature.md)                             | ✅ Complete | 2026-02-06 | Prevent duplicate message templates per customer, requires 3+ templates                                                                                                                                          |
| [UI Improvements - Dashboard, Realtime, Stickers](01-product/2026-02-05-ui-improvements.md)                 | ✅ Complete | 2026-02-05 | Unified dashboard card heights, Realtime Reply AI always enabled, fixed sticker display                                                                                                                          |
| [Followup Attempt Intervals](01-product/2026-02-02-followup-attempt-intervals.md)                           | ✅ Complete | 2026-02-02 | Customizable intervals between followup attempts (1st/2nd/3rd wait times)                                                                                                                                        |
| [Admin Actions Backup Service](01-product/2026-02-01-admin-actions-backup-service.md)                       | ✅ Complete | 2026-02-01 | Automatic periodic backup of admin_actions.xlsx                                                                                                                                                                  |

### 2025 Features

| Feature                                                                                                   | Status      | Date       | Description                                                  |
| --------------------------------------------------------------------------------------------------------- | ----------- | ---------- | ------------------------------------------------------------ |
| [Image Sender via Favorites](01-product/image-sender-via-favorites.md)                                    | ✅ Complete | 2025-02-05 | Universal image sender through WeCom Favorites               |
| [Device Init Messages View Verification](01-product/2025-12-16-device-init-messages-view-verification.md) | ✅ Complete | 2025-12-16 | Auto-verify WeCom on Messages view during init               |
| [WeCom Restart Script](01-product/2025-12-16-restart-wecom-if-not-on-messages.md)                         | ✅ Complete | 2025-12-16 | Force-restart WeCom if not on Messages tab                   |
| [Messages Screen Verification](01-product/2025-12-16-verify-messages-screen.md)                           | ✅ Complete | 2025-12-16 | Script to verify WeCom Messages screen state                 |
| [Volcengine ASR Test Button](01-product/2025-12-16-volcengine-asr-test-button.md)                         | ✅ Complete | 2025-12-16 | Test ASR credentials before transcription                    |
| [Voice Message Download & Playback](01-product/2025-12-15-voice-message-download.md)                      | ✅ Complete | 2025-12-15 | Download voice messages (SILK→WAV), store in DB, play in UI  |
| [Inline Video Downloading](01-product/2025-12-15-inline-video-downloading.md)                             | ✅ Complete | 2025-12-15 | Download videos inline during scroll extraction              |
| [Resources Media Browser](01-product/2025-12-12-resources-media-browser.md)                               | ✅ Complete | 2025-12-12 | Browse images/voice/videos with table/gallery views          |
| [Entity Deletion](01-product/2025-12-12-entity-deletion.md)                                               | ✅ Complete | 2025-12-12 | Safe deletion for Agents, Conversations, Streamers           |
| [Sidecar Sync Controls](01-product/2025-12-11-sidecar-sync-controls.md)                                   | ✅ Complete | 2025-12-11 | Sync controls with pause/resume/stop                         |
| [Log Popup Window](01-product/2025-12-11-log-popup-window.md)                                             | ✅ Complete | 2025-12-11 | Always-on-top log window with cross-window sync              |
| [Streamers Database & Persona Analysis](01-product/2025-12-11-streamers-database-persona-analysis.md)     | ✅ Complete | 2025-12-11 | Streamer profiles, cross-agent tracking, AI persona analysis |
| [Agent-Device Consolidation](01-product/2025-12-09-agent-device-consolidation.md)                         | ✅ Complete | 2025-12-09 | Agents by name+department, not device                        |
| [Sidecar Conversation History](01-product/2025-12-09-sidecar-conversation-history.md)                     | ✅ Complete | 2025-12-09 | Collapsible history panel in sidecar                         |
| [UI Terminology Rename](01-product/2025-12-09-ui-terminology-rename.md)                                   | ✅ Complete | 2025-12-09 | 客服→Agent, Customer→Streamer                                |
| [Message Trends Line Chart](01-product/2025-12-09-message-trends-line-chart.md)                           | ✅ Complete | 2025-12-09 | Interactive time series for message volume                   |
| [Dashboard Visual Enhancements](01-product/2025-12-09-dashboard-visual-enhancements.md)                   | ✅ Complete | 2025-12-09 | Donut/bar charts, animated stat cards                        |
| [Device Phone Frame Screenshot](01-product/2025-12-08-device-phone-frame-screenshot.md)                   | ✅ Complete | 2025-12-08 | Live screenshot in phone frame                               |
| [Device Kefu Auto-Init](01-product/2025-12-08-device-kefu-auto-init.md)                                   | ✅ Complete | 2025-12-08 | Auto-launch WeCom, cache kefu info                           |
| [Sidecar Generate Button](01-product/2025-12-08-sidecar-generate-button.md)                               | ✅ Complete | 2025-12-08 | On-demand AI/mock reply generation                           |
| [AI Reply Integration](01-product/2025-12-08-ai-reply-integration.md)                                     | ✅ Complete | 2025-12-08 | AI-powered replies during sync                               |
| [Send Button Detection](01-product/send-button-detection.md)                                              | ✅ Complete | 2025-01-31 | Enhanced send button detection with precise match            |

**[→ View All 44 Features](01-product/)**

### Product Decisions

See `01-product/decisions/` for product decisions and trade-offs.

### User Flows

See `01-product/user-flows/` for user journey documentation.

---

## 02-Prompts and Iterations - AI & Development History

### Prompts Library

Reusable AI agent prompts for common tasks.

| Prompt                                                                                                    | Purpose                           |
| --------------------------------------------------------------------------------------------------------- | --------------------------------- |
| [Bug Documentation Specialist](02-prompts-and-iterations/prompts-library/bug-documentation-specialist.md) | Document bugs systematically      |
| [Bug Fixer](02-prompts-and-iterations/prompts-library/bug-fixer.md)                                       | Fix bugs with root cause analysis |
| [Feature Implementer](02-prompts-and-iterations/prompts-library/feature-implementer.md)                   | Implement features with tests     |
| [Docs Sync Keeper](02-prompts-and-iterations/prompts-library/docs-sync-keeper.md)                         | Keep documentation synchronized   |
| [Git Merge Coordinator](02-prompts-and-iterations/prompts-library/git-merge-coordinator.md)               | Coordinate complex merges         |

### Session Logs

Development session summaries and AI interactions.

See `02-prompts-and-iterations/session-logs/` for full history.

### Prompt Evolution

How prompts have evolved over time based on learnings.

> **⚠️ Archived**: Completed upgrade plans have been moved to `old-archive/completed-upgrades/`.
> See [Archived Upgrade Plans](02-prompts-and-iterations/old-archive/completed-upgrades/) for:
>
> - Full Sync Modular Refactoring
> - FollowUp Multi-Device Refactoring
> - Settings Database Migration
> - Windows Job Object Implementation

Current prompt templates are in the [Prompts Library](02-prompts-and-iterations/prompts-library/).

---

## 03-Implementation and Architecture

### Current Architecture

System architecture overview and design patterns.

See [Current Architecture](03-impl-and-arch/) for high-level design.

### Key Modules (70 documents)

#### System Architecture

- **[系统架构分析报告](03-impl-and-arch/系统架构分析报告.md)** ⭐ NEW - Comprehensive architecture analysis (8.5/10 score)
- [Current Log Structure Analysis](03-impl-and-arch/key-modules/current-log-structure-analysis.md) - Current runtime logs, metrics JSONL, WebSocket streaming, and upload pipeline
- [Multi-Device Concurrency Audit](analysis/multi-device-concurrency-audit.md) - Current partial-isolation assessment for three-device sync
- [Device Isolation Roadmap](architecture/device-isolation-roadmap.md) - Path from process isolation to stronger device fault-domain isolation

- **[系统架构分析报告](03-impl-and-arch/系统架构分析报告.md)** ⭐ NEW - Comprehensive architecture analysis (8.5/10 score)
  - Directory structure assessment
  - Code organization review
  - Naming conventions evaluation
  - Design patterns analysis
  - Technical debt catalog (10 items)
  - Improvement roadmap

#### Avatar System

- [Avatar Logic Analysis](03-impl-and-arch/key-modules/avatar-logic-analysis.md)
- [Avatar Capture Timing Analysis](03-impl-and-arch/key-modules/avatar-capture-timing-analysis.md)
- [Avatar Storage Design](03-impl-and-arch/key-modules/avatar-storage-design.md)
- [Avatar Capture Flow](03-impl-and-arch/key-modules/avatar_capture_flow.md)

#### Database & Storage

- [Database Logic](03-impl-and-arch/key-modules/database_logic.md)
- [Three-Device Stress Test Guide](guides/three-device-stress-test.md) - Repeatable validation checklist for DB/ADB/AI/host contention
- [Followup Database Cleanup](03-impl-and-arch/key-modules/followup-database-cleanup.md)
- [Blacklist Migration to Database](03-impl-and-arch/experiments/blacklist-database-migration.md)

#### Message Handling

- [Image Saving Logic Analysis](03-impl-and-arch/key-modules/image_saving_logic_analysis.md)
- [Video/Image Detection Logic](03-impl-and-arch/key-modules/video-image-detection-logic.md)
- [Timestamp Format Explanation](03-impl-and-arch/key-modules/timestamp_format_explanation.md)

#### Performance & Optimization

- [Overlay Optimization](03-impl-and-arch/key-modules/overlay_optimization.md) - DroidRun UI state caching
- [Low-Spec Performance Profile](03-impl-and-arch/key-modules/low-spec-performance-profile.md) - Runtime tiering, effective limits, and metrics API
- [Swipe Log Analysis](03-impl-and-arch/key-modules/swipe-log-analysis.md)

#### Features Implementation

- [Android group invite workflow](implementation/2026-04-04-android-group-invite-workflow.md) - Modular `group_invite` service, `WeComService` UI steps, `GroupChatService` delegation
- [Media auto-actions: custom post-group message + chat header menu](implementation/2026-04-05-media-auto-actions-custom-message-and-chat-header-menu.md) - `template_resolver`, API/UI alignment, `test-trigger` semantics, device validation notes
- [Blacklist shim, sync media bus, Windows runbook](implementation/2026-04-05-blacklist-shim-sync-media-bus-runbook.md) - Desktop `blacklist_service` shim, `test_sync_factory`, `_is_chat_screen` for external groups
- [Multi-Device Sync Storage Isolation](implementation/2026-04-02-multi-device-sync-storage-isolation.md) - Default per-device media output roots for parallel sync
- [Pre-push Python tests restore](implementation/2026-04-03-pre-push-python-tests-restore.md) - Re-enabled `tests/unit` on push; fixed Windows pytest capture and path setup
- [System Robustness Fixes](implementation/2026-04-09-system-robustness-fixes.md) - AI circuit breaker, failure metrics, heartbeat service, AI health checks, process auto-restart, night-mode timeout
- [Followup System](03-impl-and-arch/key-modules/) - Multiple docs on followup logic
- [Realtime Reply](03-impl-and-arch/key-modules/) - Settings, configuration
- [Sidecar](03-impl-and-arch/key-modules/) - Real-time context pane
- [Image Sender](03-impl-and-arch/key-modules/image-sender.md) - Send images via Favorites
- [Sync Workflows](03-impl-and-arch/key-modules/) - Checkpointing, recovery

#### AI Integration

- [AI Server Message Format](03-impl-and-arch/key-modules/ai-server-message-format.md)
- [AI Trigger and Prompt Analysis](03-impl-and-arch/key-modules/ai_trigger_and_prompt_analysis.md)
- [AI Prompt Context Logic](03-impl-and-arch/key-modules/ai_prompt_context_logic.md)
- [AI Prompt Learning Flow](03-impl-and-arch/key-modules/ai_prompt_learning_flow.md)

**[→ View All 76 Implementation Docs](03-impl-and-arch/)**

### Experiments (Archived)

Proof of concepts and experimental implementations.

> **⚠️ Archived**: All experiment documents have been moved to `old-archive/experiments/`.
> See [Archived Experiments](03-impl-and-arch/old-archive/experiments/) for:
>
> - Anchor Detection and Send Button Enhancement
> - Feature Gap Analysis
> - Code Cleanup Report
> - Message Sending Flow Analysis
> - And 10 more experimental implementations

---

## 04-Bugs and Fixes

### Active Bugs (2026-02)

Currently being investigated or fixed.

| Bug                                                                                                                                 | Severity | Status    | Description                                          |
| ----------------------------------------------------------------------------------------------------------------------------------- | -------- | --------- | ---------------------------------------------------- |
| [Realtime Reply Duplicate During Countdown](04-bugs-and-fixes/active/2026-02-06-realtime-reply-duplicate-during-countdown.md)       | P1       | 🔴 Active | Duplicate replies sent during 10s countdown window   |
| [Sidecar Queue Message Wrong Person](04-bugs-and-fixes/active/2026-02-05-sidecar-queue-message-sent-to-wrong-person.md)             | P0       | ✅ Fixed  | Sidecar timeout leaves queue messages in READY state |
| [Message Sent to Wrong Person](04-bugs-and-fixes/active/2026-02-04-message-sent-to-wrong-person.md)                                 | P0       | ✅ Fixed  | Fuzzy text matching causes wrong contact selection   |
| [Followup Blacklist Not Filtered on Execution](04-bugs-and-fixes/active/2026-02-06-followup-blacklist-not-filtered-on-execution.md) | P0       | ✅ Fixed  | Blacklisted users still receive followup messages    |
| [AI Reply Contains XML Tags](04-bugs-and-fixes/active/2026-02-04-ai-reply-contains-xml-tags.md)                                     | P2       | ✅ Fixed  | AI responses include XML formatting tags             |
| [Followup ADB Get State Fix](04-bugs-and-fixes/active/2026-02-04-followup-adb-get_state-fix.md)                                     | P2       | ✅ Fixed  | ADB get_state method issue in followup               |
| [Followup Timezone and Prompt Fixes](04-bugs-and-fixes/active/2026-02-03-followup-timezone-and-prompt-fixes.md)                     | P2       | ✅ Fixed  | Timezone and prompt configuration issues             |
| [Blacklist Cache Not Synced](04-bugs-and-fixes/active/2026-02-03-blacklist-cache-not-synced.md)                                     | P1       | ✅ Fixed  | Blacklist not syncing between devices                |
| [Blocked User Still Clicked](04-bugs-and-fixes/active/2026-02-03-blocked-user-still-clicked.md)                                     | P1       | ✅ Fixed  | Blacklisted users still clickable                    |
| [Emulator Device Detected](04-bugs-and-fixes/active/2026-02-03-emulator-device-detected.md)                                         | P2       | ✅ Fixed  | Emulator detection improvements                      |
| [Followup Queue Manager Log Callback Error](04-bugs-and-fixes/active/2026-02-03-followup-queue-manager-log-callback-error.md)       | P2       | ✅ Fixed  | Queue manager logging error                          |
| [UTF8 Database Encoding Fix](04-bugs-and-fixes/active/2026-02-02-utf8-database-encoding-fix.md)                                     | P0       | ✅ Fixed  | Invalid UTF-8 causing backend crash                  |

**[→ View All Active Bugs](04-bugs-and-fixes/active/)** (38 files)

### Fixed Bugs (Archive)

Resolved issues organized by date.

#### 2026-02

- [Loguru KeyError: 'module' Fix](04-bugs-and-fixes/resolved/2026-02-06-loguru-module-keyerror.md) - Fixed logging format errors in followup processes

#### 2026-01

- [Avatar Capture Failure Analysis](04-bugs-and-fixes/fixed/2026-01-18-avatar-capture-failure-analysis.md) - Root cause of avatar capture failures
- [Image Path None Analysis](04-bugs-and-fixes/fixed/2026-01-18-image-path-none-analysis.md) - Image path issues during sync
- [Realtime Customer Message Not Saved](04-bugs-and-fixes/fixed/2026-01-24-realtime-customer-message-not-saved.md) - Realtime sync not saving messages
- [Chat History Wrong Contact](04-bugs-and-fixes/fixed/2026-01-24-chat-history-wrong-contact.md) - Chat history displayed for wrong contact
- [Sidecar Skip Button Issue](04-bugs-and-fixes/fixed/2026-01-24-sidecar-skip-button-issue.md) - Skip button not working properly
- [Full Sync Blacklist Issues](04-bugs-and-fixes/fixed/) - Multiple blacklist-related fixes

**[→ View All Fixed Bugs](04-bugs-and-fixes/fixed/)** (62+ files)

#### 2025 Archive

- Voice Transcription Timeout
- Voice Playback Failure
- Video Download Failure
- Image Deduplication Hash
- Streamers Implementation Fixes
- Sync Progress Tracking
- And 50+ more...

### Bug Patterns

Recurring patterns and prevention strategies.

See `04-bugs-and-fixes/patterns/` for:

- Coordinate-based UI interaction issues
- Database encoding problems
- Race conditions in async operations
- Message deduplication edge cases

---

## 05-Changelog and Upgrades

### Master Changelog

[CHANGELOG.md](05-changelog-and-upgrades/CHANGELOG.md) - Version history and release notes.

### Session Changelogs

Recent development session summaries and changelogs:

| Session                                                                                                                    | Description                                                    | Date       |
| -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ---------- |
| **[Realtime Reply Duplicate Analysis](05-changelog-and-upgrades/2026-02-06-session-realtime-reply-duplicate-analysis.md)** | Bug analysis, 3 solution approaches, comprehensive docs        | 2026-02-06 |
| **[Followup Fixes & Code Cleanup](05-changelog-and-upgrades/2026-02-06-followup-fixes-and-cleanup.md)**                    | Async/await fix, blacklist filter, logging cleanup, -636 lines | 2026-02-06 |
| **[Code Cleanup & Architecture Analysis](05-changelog-and-upgrades/2026-02-06-cleanup-and-architecture.md)**               | Vue fixes, architecture report, file cleanup                   | 2026-02-06 |
| **[Path Refactoring & Documentation Cleanup](05-changelog-and-upgrades/2026-02-06-session-summary.md)**                    | Eliminated hardcoded paths, archived 26 docs                   | 2026-02-06 |
| **[Architecture Review](05-changelog-and-upgrades/2026-02-05-architecture-review.md)**                                     | Comprehensive code audit and cleanup                           | 2026-02-05 |

### Upgrade Notes

See `05-changelog-and-upgrades/upgrade-notes/` for migration guides between versions.

### Rollback Incidents

See `05-changelog-and-upgrades/rollback-incidents/` for post-mortems.

### Old Archive

See `05-changelog-and-upgrades/old-archive/` for historical documentation.

---

## 06-Testing and QA

### Test Documentation

(Planned expansion)

- Test Scenarios
- Edge Cases
- Manual Test Checklist
- Integration Test Coverage

---

## 07-Appendix - Reference Materials

### Development Guides

| Document                                                                              | Description                                    |
| ------------------------------------------------------------------------------------- | ---------------------------------------------- |
| [Docs Organization](07-appendix/docs-organization.md)                                 | 文档目录规范                                   |
| [Image Sender Development Workflow](07-appendix/image-sender-development-workflow.md) | Complete TDD workflow for image sender feature |
| [Email Notification Timing](07-appendix/email_notification_timing.md)                 | When email notifications are sent              |

### Configuration Examples

- [Config Environment Example](07-appendix/config-env-example.md)

### Session Summaries

- [Image Sender Technical Validation](02-prompts-and-iterations/session-logs/2025-02-05-image-sender-technical-validation.md)

### Tools & Setup

(To be expanded)

- Development environment setup
- Testing tools
- Debugging guides

---

## Directory Structure

```
docs/
├── 00-meta/                    # Documentation about documentation
├── 01-product/                 # Features, user flows, product decisions (44 files)
├── 02-prompts-and-iterations/  # AI prompts, session logs, evolution (17 files)
├── 03-impl-and-arch/          # Architecture, key modules, experiments (76 files)
├── 04-bugs-and-fixes/         # Active bugs, fixed archive, patterns (62 files)
├── 05-changelog-and-upgrades/  # Version history, migrations (24 files)
├── 06-testing-and-qa/         # Testing documentation (future)
└── 07-appendix/               # Reference materials, guides (9 files)
```

---

## Statistics

- **Total Documents**: 232+ files
- **Features**: 44 implemented
- **Active Bugs**: 35 (2026-02)
- **Fixed Bugs**: 62+ archived
- **Implementation Docs**: 76 modules
- **Reorganization Date**: 2026-02-05

---

## Search Tips

### Finding What You Need

**Looking for a feature?**
→ Check `01-product/` by date or use INDEX search

**Bug reported?**
→ Check `04-bugs-and-fixes/active/` first, then `fixed/`

**Want to understand how X works?**
→ Check `03-impl-and-arch/key-modules/`

**Need context for development?**
→ Check `02-prompts-and-iterations/session-logs/`

**Setting up dev environment?**
→ Check `07-appendix/` for guides

---

## Document Maintenance

### Weekly

- Review active bugs
- Move resolved bugs to fixed
- Update timestamps

### Monthly

- Audit for stale docs
- Consolidate duplicates
- Update glossary

### Per Release

- Update CHANGELOG.md
- Review architecture docs
- Archive old decisions

---

## Contribution Guidelines

When creating new documentation:

1. **Choose the right location** - See [Folder Structure](00-meta/folder-structure.md)
2. **Follow the template** - See [How We Document](00-meta/how-we-document.md)
3. **Update INDEX.md** - Add to appropriate section
4. **Link related docs** - Cross-reference liberally
5. **Add timestamp** - Include "Last Updated" in front matter

---

## Related Resources

- [Project README](../README.md)
- [CLAUDE.md](../CLAUDE.md) - Project overview and architecture
- [wecom-desktop/README.md](../wecom-desktop/README.md) - Desktop app docs

---

**Maintained by**: Development Team
**Last Full Review**: 2026-02-05
**Next Review**: 2026-03-01
