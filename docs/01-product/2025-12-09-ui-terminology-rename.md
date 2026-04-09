# UI Terminology Rename: 客服 → Agent, Customer → Streamer

**Date**: 2025-12-09  
**Status**: ✅ Complete  
**Components**: Frontend (Vue Components, Views)

## Overview

This feature renames user-facing terminology throughout the WeCom Desktop application UI to better align with the business domain:

- **客服** → **Agent** (or **Agents** for plural)
- **Customer** → **Streamer** (or **Streamers** for plural)

## Problem Statement

The original terminology used Chinese "客服" (customer service) and generic "Customer" labels, which didn't accurately represent the actual business context where:

- "客服" are agents managing streamer communications
- "Customers" are actually streamers being supported

## Changes Made

### Navigation (App.vue)

| Before    | After     |
| --------- | --------- |
| 客服      | Agents    |
| Customers | Streamers |

### Dashboard (DashboardView.vue)

| Location         | Before                    | After                      |
| ---------------- | ------------------------- | -------------------------- |
| Device sublabels | `X 客服 · Y customers`    | `X Agents · Y Streamers`   |
| Stat card title  | 客服 (Support Staff)      | Agents                     |
| Stat card title  | Customers                 | Streamers                  |
| Section heading  | 客服 Performance          | Agent Performance          |
| Empty state      | No 客服 records yet       | No Agent records yet       |
| Stats grid       | Customers                 | Streamers                  |
| Ratio bar labels | 客服 sent / Customer sent | Agent sent / Streamer sent |
| Table headers    | Customer / 客服           | Streamer / Agent           |

### Agents List (KefuListView.vue)

| Location      | Before                             | After                               |
| ------------- | ---------------------------------- | ----------------------------------- |
| Page title    | 客服                               | Agents                              |
| Description   | Browse all 客服...                 | Browse all Agents...                |
| Table headers | 客服 / Customers / Latest customer | Agent / Streamers / Latest Streamer |

### Agent Detail (KefuDetailView.vue)

| Location     | Before                           | After                            |
| ------------ | -------------------------------- | -------------------------------- |
| Label        | 客服                             | Agent                            |
| Section      | Customers                        | Streamers                        |
| Empty state  | No customers have been synced... | No streamers have been synced... |
| Table header | Customer                         | Streamer                         |

### Streamers List (CustomersListView.vue)

| Location           | Before                                                                           | After                                                                            |
| ------------------ | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Page title         | Customers                                                                        | Streamers                                                                        |
| Description        | ...each synced customer...                                                       | ...each synced streamer...                                                       |
| Search placeholder | Search by customer name...                                                       | Search by streamer name...                                                       |
| Status messages    | total customers, Loading customers, No customers found, Failed to load customers | total streamers, Loading streamers, No streamers found, Failed to load streamers |
| Table headers      | Customer / 客服                                                                  | Streamer / Agent                                                                 |

### Streamer Detail (CustomerDetailView.vue)

| Location        | Before                                    | After                                     |
| --------------- | ----------------------------------------- | ----------------------------------------- |
| Back button     | ← Back to customers                       | ← Back to streamers                       |
| ID label        | Customer ID                               | Streamer ID                               |
| Status messages | Failed to load customer, Loading customer | Failed to load streamer, Loading streamer |
| Label           | Customer                                  | Streamer                                  |
| Agent label     | 客服                                      | Agent                                     |
| Empty state     | ...synced for this customer               | ...synced for this streamer               |
| Message sender  | 客服 / 客户                               | Agent / Streamer                          |

### Device Detail (DeviceDetailView.vue)

| Location    | Before         | After       |
| ----------- | -------------- | ----------- |
| Kefu card   | 👤 客服 (Kefu) | 👤 Agent    |
| Sync status | X customers    | X streamers |

### Sidecar (SidecarView.vue)

| Location    | Before | After |
| ----------- | ------ | ----- |
| Panel label | 客服   | Agent |

### Message Trend Chart (MessageTrendChart.vue)

| Location      | Before                     | After                       |
| ------------- | -------------------------- | --------------------------- |
| Legend        | Incoming (Customer → 客服) | Incoming (Streamer → Agent) |
| Legend        | Outgoing (客服 → Customer) | Outgoing (Agent → Streamer) |
| Kefu fallback | 客服 ${id}                 | Agent ${id}                 |
| Label         | 客服:                      | Agents:                     |

### Device Card (DeviceCard.vue)

| Location        | Before      | After       |
| --------------- | ----------- | ----------- |
| Sync progress   | X customers | X streamers |
| Completed state | X customers | X streamers |

## Files Changed

| File                                          | Type of Change                             |
| --------------------------------------------- | ------------------------------------------ |
| `src/App.vue`                                 | Navigation labels                          |
| `src/views/DashboardView.vue`                 | Multiple display labels                    |
| `src/views/KefuListView.vue`                  | Page title, table headers                  |
| `src/views/KefuDetailView.vue`                | Labels, section titles                     |
| `src/views/CustomersListView.vue`             | Page title, all status messages            |
| `src/views/CustomerDetailView.vue`            | Labels, status messages, sender indicators |
| `src/views/DeviceDetailView.vue`              | Card label, sync status                    |
| `src/views/SidecarView.vue`                   | Panel label                                |
| `src/components/charts/MessageTrendChart.vue` | Legend labels                              |
| `src/components/DeviceCard.vue`               | Sync status labels                         |

## Technical Notes

### What Changed

- Only **user-facing display text** was changed
- No changes to:
  - Variable names (e.g., `customerStore` remains unchanged)
  - API endpoints (e.g., `/customers` remains unchanged)
  - Database schema or column names
  - Route paths (e.g., `/customers` path remains unchanged)

### Consistency

All instances in the `/wecom-desktop/src` directory were updated to ensure consistent terminology across the entire UI.

## Testing

After changes:

- Navigation sidebar shows "Agents" and "Streamers"
- Dashboard displays correct labels in stat cards, tables, and charts
- All list and detail views use correct terminology
- Message sender indicators show "Agent" or "Streamer" appropriately

## Related Documentation

This change affects the understanding of these related features:

- [Dashboard Visual Enhancements](2025-12-09-dashboard-visual-enhancements.md) - Stats now labeled as "Agents" and "Streamers"
- [Message Trends Line Chart](2025-12-09-message-trends-line-chart.md) - Chart legends updated
