# Message Trends Interactive Line Chart

**Date**: 2025-12-09  
**Status**: ✅ Complete  
**Components**: Frontend (InteractiveLineChart, MessageTrendChart), Backend (dashboard.py), API (api.ts)

## Overview

This feature adds an interactive line chart to the dashboard that visualizes message volume over time. Users can compare different Agents, view incoming vs outgoing message trends, and adjust the time range and granularity.

## Problem Statement

The dashboard showed current totals but lacked historical trend analysis:

- No way to see message volume changes over time
- No comparison between different Agent performance
- No visualization of incoming vs outgoing message patterns
- No time-based filtering or grouping options

## Features

### 1. Time Series Visualization

- Smooth bezier curve lines with gradient area fills
- Animated line drawing on mount
- Interactive hover with vertical indicator line
- Tooltip showing all series values at hovered time point

### 2. Metric Selection

| Metric       | Description                        |
| ------------ | ---------------------------------- |
| **Total**    | All messages combined              |
| **Incoming** | Streamer → Agent messages          |
| **Outgoing** | Agent → Streamer messages          |
| **Compare**  | Incoming and Outgoing side-by-side |

### 3. Time Range Selection

- 7 days
- 30 days
- 90 days
- All time

### 4. Granularity Options

- Hour (for detailed short-term analysis)
- Day (default, best for weekly/monthly trends)
- Week (for longer-term patterns)
- Month (for historical overview)

### 5. Series Comparison

- Overall aggregated line (toggleable)
- Individual Agent lines (multi-select)
- "Select all" / "Clear" buttons
- Color-coded legend

## Backend API

### New Endpoint: `GET /dashboard/timeseries`

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `kefu_ids` | string | - | Comma-separated kefu IDs to filter |
| `start_date` | string | - | Start date (ISO format) |
| `end_date` | string | - | End date (ISO format) |
| `granularity` | string | "day" | hour, day, week, month |

**Response:**

```json
{
  "db_path": "/path/to/wecom_conversations.db",
  "overall": [
    { "time": "2025-12-05", "total": 117, "outgoing": 78, "incoming": 39 },
    { "time": "2025-12-06", "total": 219, "outgoing": 170, "incoming": 49 }
  ],
  "by_kefu": {
    "1": [{ "time": "2025-12-05", "total": 108, "outgoing": 71, "incoming": 37 }],
    "2": [{ "time": "2025-12-05", "total": 9, "outgoing": 7, "incoming": 2 }]
  },
  "kefu_names": { "1": "wyd", "2": "wgz小号" },
  "granularity": "day"
}
```

### SQL Query Structure

```sql
SELECT
    strftime('%Y-%m-%d', COALESCE(m.timestamp_parsed, m.created_at)) as time_bucket,
    COUNT(*) as total,
    SUM(CASE WHEN m.is_from_kefu = 1 THEN 1 ELSE 0 END) as outgoing,
    SUM(CASE WHEN m.is_from_kefu = 0 THEN 1 ELSE 0 END) as incoming
FROM messages m
JOIN customers c ON m.customer_id = c.id
JOIN kefus k ON c.kefu_id = k.id
WHERE {date_filters} AND {kefu_filters}
GROUP BY time_bucket
ORDER BY time_bucket ASC
```

## Frontend Components

### InteractiveLineChart (`components/charts/InteractiveLineChart.vue`)

Core SVG line chart with:

- Responsive width (adapts to container)
- Smooth bezier curve interpolation
- Gradient area fills under lines
- Axis labels (Y: values, X: time)
- Grid lines (dashed)
- Hover detection with closest point snapping
- Glow filter for highlighted lines
- Loading state with spinner
- "No data" empty state

**Props:**
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `series` | DataSeries[] | required | Array of series data |
| `height` | number | 300 | Chart height in pixels |
| `showGrid` | boolean | true | Show grid lines |
| `showTooltip` | boolean | true | Enable hover tooltip |
| `animated` | boolean | true | Enable draw animation |
| `loading` | boolean | false | Show loading state |

### MessageTrendChart (`components/charts/MessageTrendChart.vue`)

Complete chart widget with controls:

- Header with title and total messages stat
- Metric selector (Total/Incoming/Outgoing/Compare)
- Time range selector (7d/30d/90d/All)
- Granularity dropdown (Hour/Day/Week/Month)
- Refresh button
- Overall toggle checkbox
- Agent toggle buttons with color indicators
- Select all / Clear buttons
- Legend showing visible series
- Error state with retry button

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MessageTrendChart.vue                         │
│  Controls: metric, timeRange, granularity, selectedKefus        │
└────────────────────────┬────────────────────────────────────────┘
                         │ api.getMessageTimeseries()
┌────────────────────────▼────────────────────────────────────────┐
│                    Backend FastAPI                               │
│  GET /dashboard/timeseries                                       │
│  - Aggregates by time bucket                                     │
│  - Filters by kefu/date                                          │
│  - Returns overall + per-kefu breakdown                          │
└────────────────────────┬────────────────────────────────────────┘
                         │ SQL queries on messages table
┌────────────────────────▼────────────────────────────────────────┐
│                    SQLite Database                               │
│  messages.timestamp_parsed, is_from_kefu, customer_id           │
└─────────────────────────────────────────────────────────────────┘
```

## Color Scheme

| Series        | Color    | Hex     |
| ------------- | -------- | ------- |
| Total/Overall | Emerald  | #10B981 |
| Incoming      | Blue     | #3B82F6 |
| Outgoing      | Amber    | #F59E0B |
| Kefu 1        | Emerald  | #10B981 |
| Kefu 2        | Blue     | #3B82F6 |
| Kefu 3        | Violet   | #8B5CF6 |
| Kefu 4        | Amber    | #F59E0B |
| ...           | (cycles) | ...     |

## Files Changed

| File                                             | Changes                                                                            |
| ------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `backend/routers/dashboard.py`                   | Added `/timeseries` endpoint and `_fetch_message_timeseries()`                     |
| `src/services/api.ts`                            | Added `TimeseriesDataPoint`, `MessageTimeseriesResponse`, `getMessageTimeseries()` |
| `src/components/charts/InteractiveLineChart.vue` | New SVG line chart component                                                       |
| `src/components/charts/MessageTrendChart.vue`    | Chart widget with controls                                                         |
| `src/components/charts/index.ts`                 | Export new components                                                              |
| `src/views/DashboardView.vue`                    | Integrate MessageTrendChart                                                        |

## Usage Example

```vue
<template>
  <MessageTrendChart />
</template>

<script setup>
import { MessageTrendChart } from '../components/charts'
</script>
```

## Interactions

| User Action             | Result                              |
| ----------------------- | ----------------------------------- |
| Hover over chart        | Vertical line + tooltip with values |
| Click metric button     | Chart updates with selected metric  |
| Click time range        | Refetches data with new date filter |
| Change granularity      | Refetches data with new grouping    |
| Toggle Overall checkbox | Show/hide overall aggregated line   |
| Click Agent button      | Toggle that agent's line visibility |
| Click "Select all"      | Show all kefu lines                 |
| Click "Clear"           | Hide all kefu lines                 |
| Click Refresh           | Force data reload                   |

## API Type Definitions

```typescript
interface TimeseriesDataPoint {
  time: string
  total: number
  outgoing: number
  incoming: number
}

interface MessageTimeseriesResponse {
  db_path: string
  overall: TimeseriesDataPoint[]
  by_kefu: Record<number, TimeseriesDataPoint[]>
  kefu_names: Record<number, string>
  granularity: string
}
```

## Related Features

- **[Dashboard Visual Enhancements](2025-12-09-dashboard-visual-enhancements.md)**: Donut chart, bar charts, stat cards that complement this line chart
