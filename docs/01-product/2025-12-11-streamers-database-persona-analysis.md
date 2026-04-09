# Streamers Database with AI Persona Analysis

> **Date**: 2025-12-11  
> **Status**: ✅ Complete  
> **Category**: Feature

## Overview

A comprehensive streamer management system that provides:

1. Centralized database of unique streamers (grouped by name)
2. Cross-agent conversation tracking
3. Extensible profile management
4. AI-powered persona analysis using DeepSeek

## Problem Statement

Previously, the "Streamers" page at `/customers` was showing individual conversations (one streamer per agent conversation). This didn't account for:

- One streamer having conversations with multiple agents via different WeCom accounts
- Need for centralized streamer profile management
- No ability to analyze streamer communication patterns and personality

## Solution

### Navigation Restructuring

**Before:**

- `Streamers` tab → `/customers` (showed conversation list)

**After:**

- `Conversations` tab → `/conversations` (shows all conversation threads)
- `Streamers` tab → `/streamers` (shows unique streamer database)

### New Streamers Database View (`/streamers`)

Card-based grid displaying unique streamers with:

- Avatar (matched from local avatar files)
- Name and conversation count
- Total messages across all conversations
- Agent names who talked to this streamer
- Channels (e.g., @WeChat)
- Profile/Persona status indicators
- Last seen date

### Streamer Detail View (`/streamers/:id`)

Three-tab interface:

#### 1. Profile Tab

Extensible profile fields:

- Gender
- Age
- Location
- Height / Weight
- Education
- Occupation
- Interests (tags)
- Social Platforms (tags)
- Notes
- Custom Fields (JSON-based, extensible)

#### 2. Conversations Tab

Lists all conversations this streamer has had:

- Agent name and department
- Device serial
- Channel
- Message count
- Last message timestamp
- Click to jump to specific conversation detail

#### 3. Persona Tab

AI-powered personality analysis:

- **Personality Radar Chart** - SVG-based radar visualization with 5 dimensions:
  - 外向性 (Extraversion)
  - 开放性 (Openness)
  - 尽责性 (Conscientiousness)
  - 宜人性 (Agreeableness)
  - 情绪稳定性 (Emotional Stability)
- **Progress bars** with descriptions for each dimension
- **Communication Profile** - Style, tone, engagement level, response pattern
- **Active Hours** - When the streamer is most responsive
- **Language Patterns** - Common phrases and expressions
- **Topics of Interest** - Detected from conversation content
- **Personality Traits** - AI-detected characteristics
- **Analysis Summary** - Overall AI assessment
- **Recommendations** - Actionable suggestions for engaging this streamer

### AI Analysis Settings (Settings Page)

New section in Settings for configuring AI persona analysis:

- Enable/Disable toggle
- Provider selection (DeepSeek, OpenAI, Custom)
- API Base URL
- API Key (with show/hide toggle)
- Model selection
- Max response tokens
- Test connection button

**Default Configuration:**

- Provider: DeepSeek
- Base URL: `https://api.deepseek.com`
- Model: `deepseek-chat`
- Max Tokens: 4096

## Technical Implementation

### Frontend Components

| File                                         | Purpose                                   |
| -------------------------------------------- | ----------------------------------------- |
| `src/views/StreamersListView.vue`            | Streamer card grid with search/pagination |
| `src/views/StreamerDetailView.vue`           | Profile, conversations, persona tabs      |
| `src/components/charts/PersonalityRadar.vue` | SVG radar chart component                 |
| `src/stores/streamers.ts`                    | Pinia store for streamer state            |
| `src/stores/settings.ts`                     | Extended with AI analysis settings        |
| `src/views/SettingsView.vue`                 | Extended with AI analysis config section  |

### Backend Endpoints

| Endpoint                               | Method | Description                                              |
| -------------------------------------- | ------ | -------------------------------------------------------- |
| `GET /streamers`                       | GET    | List unique streamers with stats                         |
| `GET /streamers/{id}`                  | GET    | Get streamer detail with profile, conversations, persona |
| `PUT /streamers/{id}/profile`          | PUT    | Update streamer profile                                  |
| `POST /streamers/{id}/analyze-persona` | POST   | Run AI persona analysis                                  |
| `POST /streamers/test-ai`              | POST   | Test AI provider connection                              |

### Database Tables (auto-created)

```sql
-- Streamer profiles (extensible)
CREATE TABLE streamer_profiles (
    id TEXT PRIMARY KEY,  -- Hash of name + avatar
    name TEXT NOT NULL,
    avatar_url TEXT,
    gender TEXT,
    age INTEGER,
    location TEXT,
    height INTEGER,
    weight INTEGER,
    education TEXT,
    occupation TEXT,
    interests TEXT,       -- JSON array
    social_platforms TEXT, -- JSON array
    notes TEXT,
    custom_fields TEXT,   -- JSON object
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- AI persona analysis results
CREATE TABLE streamer_personas (
    id INTEGER PRIMARY KEY,
    streamer_id TEXT REFERENCES streamer_profiles(id),
    communication_style TEXT,
    language_patterns TEXT,    -- JSON array
    tone TEXT,
    engagement_level TEXT,
    response_time_pattern TEXT,
    active_hours TEXT,         -- JSON array
    topics_of_interest TEXT,   -- JSON array
    personality_traits TEXT,   -- JSON array
    dimensions TEXT,           -- JSON array of {name, value, description}
    analysis_summary TEXT,
    recommendations TEXT,      -- JSON array
    analyzed_at TIMESTAMP,
    analyzed_messages_count INTEGER,
    model_used TEXT
);
```

### Streamer Identification

Streamers are uniquely identified by:

- Name (primary identifier)
- Future: Avatar URL (when available from WeChat extraction)

This allows grouping conversations across different agents/devices under a single streamer profile.

## AI Analysis Process

1. Collect all messages FROM the streamer (not from agents) - up to 500 messages
2. Send to DeepSeek with a structured prompt requesting JSON output
3. Parse response into personality dimensions, traits, patterns
4. Store in `streamer_personas` table
5. Display results in UI with radar chart and detailed breakdowns

## Files Changed

### New Files

- `wecom-desktop/src/views/StreamersListView.vue`
- `wecom-desktop/src/views/StreamerDetailView.vue`
- `wecom-desktop/src/components/charts/PersonalityRadar.vue`
- `wecom-desktop/src/stores/streamers.ts`
- `wecom-desktop/backend/routers/streamers.py`
- `wecom-desktop/backend/services/ai_analysis.py`

### Modified Files

- `wecom-desktop/src/App.vue` - Navigation updated
- `wecom-desktop/src/main.ts` - Router configuration
- `wecom-desktop/src/stores/settings.ts` - AI analysis settings
- `wecom-desktop/src/views/SettingsView.vue` - AI settings UI
- `wecom-desktop/src/views/CustomersListView.vue` - Renamed to "Conversations"
- `wecom-desktop/src/views/CustomerDetailView.vue` - Updated terminology
- `wecom-desktop/src/views/DashboardView.vue` - Updated links
- `wecom-desktop/backend/main.py` - Added streamers router
- `wecom-desktop/backend/requirements.txt` - Added httpx
- `wecom-desktop/backend/routers/customers.py` - Added device info to query

## Testing

1. Navigate to `/streamers` - should see card grid of unique streamers
2. Click a streamer card - should open detail view
3. Profile tab - edit and save profile fields
4. Conversations tab - click to navigate to specific conversation
5. Persona tab - click "Analyze Persona" to run AI analysis
6. Settings page - configure and test AI connection

## Related Documentation

- [UI Terminology Rename](2025-12-09-ui-terminology-rename.md) - Previous naming conventions
- [AI Reply Integration](2025-12-08-ai-reply-integration.md) - Existing AI integration for replies
