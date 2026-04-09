# Resources Media Browser Feature

> **Date**: 2025-12-12
> **Status**: ✅ Complete
> **Scope**: Images, Voice Messages, Video Messages

## Overview

Added a new "Resources" section to browse and manage all media resources (images, voice messages, videos) from conversations. The feature provides:

- **Three tabs**: Images 🖼️, Voice 🎤, Videos 🎬
- **Two view modes**: Table and Gallery (persisted across sessions)
- **Full sorting, filtering, and pagination**
- **Image viewer modal** with navigation
- **Direct navigation** to conversation with message highlighting
- **Safe deletion** with confirmation

## Navigation

Added to the main sidebar navigation between "Conversations" and "Streamers":

| Icon | Name      | Path         |
| ---- | --------- | ------------ |
| 📁   | Resources | `/resources` |

## Tab Structure

### Images Tab

Displays all images stored in the `images` table with conversation context:

- **Table View**: Thumbnail, filename, dimensions, streamer, agent, device, size, date
- **Gallery View**: Image grid with metadata cards
- **Image Viewer**: Full-screen modal with prev/next navigation

### Voice Tab

Displays all voice messages (`message_type = 'voice'`) from the `messages` table:

- Transcription content (if available)
- Streamer, agent, device info
- Creation timestamp

### Video Tab

Displays all video messages (`message_type = 'video'`) from the `messages` table:

- Description content (if available)
- Streamer, agent, device info
- Creation timestamp

## Features

### View Modes (Persisted)

| Mode    | Description                      | Persistence                             |
| ------- | -------------------------------- | --------------------------------------- |
| Table   | Sortable data table with columns | localStorage key: `resources-view-mode` |
| Gallery | Visual grid with cards           | Survives page refresh                   |

### Filtering Options

| Filter    | Description                                    |
| --------- | ---------------------------------------------- |
| Search    | Text search in streamer name, channel, content |
| Streamer  | Filter by specific streamer name               |
| Agent     | Filter by specific agent (kefu)                |
| Device    | Filter by device serial                        |
| Date From | Filter resources from this date                |
| Date To   | Filter resources until this date               |

### Sorting

All columns are sortable by clicking the header:

- `created_at` (default, descending)
- `file_name`, `file_size`, `width`, `height` (images)
- `streamer_name`, `kefu_name`

### Image Viewer Modal

When clicking on an image (in table thumbnail or gallery):

```
┌─────────────────────────────────────────────────────┐
│ [X] Close                                    [X]    │
│                                                     │
│    [<]              IMAGE              [>]         │
│                                                     │
│              filename.png                           │
│              StreamerName · @WeChat                 │
│              1920×1080 · 245.3 KB                  │
│                                                     │
│     [💬 View in Conversation]  [🗑️ Delete]        │
│                                                     │
│                   3 / 10                            │
└─────────────────────────────────────────────────────┘
```

**Features:**

- Previous/Next navigation (← → keys)
- Close with Escape key
- Image info display
- Direct actions: View in Conversation, Delete

### Navigation to Conversation

Clicking on a resource (non-image area) navigates to the conversation with the message highlighted:

```
/conversations/:customerId?highlightMessage=:messageId
```

The highlighted message:

- Scrolls into view automatically
- Has a yellow ring/background highlight
- Shows "📍 Highlighted" badge
- Fades after 5 seconds

## Backend Implementation

### New Router: `resources.py`

```python
router = APIRouter(prefix="/resources", tags=["resources"])
```

### Endpoints

| Method | Endpoint                      | Description                                   |
| ------ | ----------------------------- | --------------------------------------------- |
| GET    | `/resources/images`           | List images with filters, sorting, pagination |
| GET    | `/resources/images/{id}`      | Get image details                             |
| GET    | `/resources/images/{id}/file` | Serve actual image file                       |
| DELETE | `/resources/images/{id}`      | Delete image record                           |
| GET    | `/resources/voice`            | List voice messages                           |
| DELETE | `/resources/voice/{id}`       | Delete voice message                          |
| GET    | `/resources/videos`           | List video messages                           |
| DELETE | `/resources/videos/{id}`      | Delete video message                          |
| GET    | `/resources/filter-options`   | Get filter options and counts                 |

### Image File Serving

The `/resources/images/{id}/file` endpoint serves actual image files:

- Resolves file path relative to `PROJECT_ROOT`
- Returns appropriate `Content-Type` based on extension
- Supports: PNG, JPG, JPEG, GIF, WEBP, BMP

## Frontend Implementation

### New Store: `resources.ts`

```typescript
export const useResourcesStore = defineStore('resources', () => {
  // View mode (persisted to localStorage)
  const viewMode = ref<ViewMode>('table')

  // Images state
  const images = ref<ImageResource[]>([])
  const imagesTotalCount = ref(0)
  // ... filters, pagination, loading, error states

  // Voice state
  const voiceMessages = ref<VoiceResource[]>([])
  // ... similar structure

  // Video state
  const videoMessages = ref<VideoResource[]>([])
  // ... similar structure

  // Actions
  async function fetchImages(options) { ... }
  async function deleteImage(id) { ... }
  // ... similar for voice, video
})
```

### New View: `ResourcesView.vue`

Features:

- Tab navigation with resource counts
- View mode toggle (Table/Gallery)
- Search and filter panel
- Sortable table with all columns
- Gallery grid with cards
- Image viewer modal
- Delete confirmation modal
- Success toast notifications

### API Types (`api.ts`)

```typescript
// Resource types
interface ImageResource { id, file_path, file_name, width, height, ... }
interface VoiceResource { id, content, is_from_kefu, ... }
interface VideoResource { id, content, is_from_kefu, ... }

// Response types
interface ImageListResponse { total, items: ImageResource[], ... }
interface VoiceListResponse { total, items: VoiceResource[], ... }
interface VideoListResponse { total, items: VideoResource[], ... }

// API methods
api.getImages(params): Promise<ImageListResponse>
api.getImage(id): Promise<ImageDetailResponse>
api.getImageUrl(id): string  // Returns URL for image file
api.deleteImage(id): Promise<ImageDeleteResponse>
api.getVoiceMessages(params): Promise<VoiceListResponse>
api.deleteVoiceMessage(id): Promise<VoiceDeleteResponse>
api.getVideoMessages(params): Promise<VideoListResponse>
api.deleteVideoMessage(id): Promise<VideoDeleteResponse>
api.getResourceFilterOptions(): Promise<ResourceFilterOptions>
```

### Message Highlighting (`CustomerDetailView.vue`)

Added support for highlighting messages when navigating from resources:

```typescript
// Query param handling
const highlightedMessageId = ref<number | null>(null)

// Scroll to and highlight message
function scrollToHighlightedMessage() {
  if (highlightedMessageId.value && messageRefs.value[highlightedMessageId.value]) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

// Clear highlight after 5 seconds
function clearHighlight() {
  setTimeout(() => {
    highlightedMessageId.value = null
  }, 5000)
}
```

## Files Changed

### Backend

- `wecom-desktop/backend/routers/resources.py` - **NEW** - All resource endpoints
- `wecom-desktop/backend/main.py` - Added resources router

### Frontend

- `wecom-desktop/src/services/api.ts` - Added resource types and methods
- `wecom-desktop/src/stores/resources.ts` - **NEW** - Resources store
- `wecom-desktop/src/views/ResourcesView.vue` - **NEW** - Resources view
- `wecom-desktop/src/views/CustomerDetailView.vue` - Added message highlighting
- `wecom-desktop/src/main.ts` - Added resources route
- `wecom-desktop/src/App.vue` - Added Resources navigation item

## Database Tables Used

| Table       | Purpose                                           |
| ----------- | ------------------------------------------------- |
| `images`    | Image file records with message association       |
| `messages`  | Voice/video messages (filtered by `message_type`) |
| `customers` | Conversation context                              |
| `kefus`     | Agent information                                 |
| `devices`   | Device information                                |

## Testing Checklist

- [ ] View images in table mode with thumbnails
- [ ] View images in gallery mode with full images
- [ ] Switch view modes and verify persistence after refresh
- [ ] Sort by different columns
- [ ] Filter by streamer, agent, device, date range
- [ ] Click image to open viewer modal
- [ ] Navigate through images with ← → keys
- [ ] Click "View in Conversation" to navigate with highlight
- [ ] Verify message highlight scrolls into view
- [ ] Verify highlight fades after 5 seconds
- [ ] Delete image with confirmation
- [ ] Verify deleted image removed from list
- [ ] Test voice and video tabs (empty state if no data)
- [ ] Verify filter options load correctly

## Related Documentation

- [Entity Deletion](2025-12-12-entity-deletion.md) - Similar deletion patterns
- [Streamers Database & Persona Analysis](2025-12-11-streamers-database-persona-analysis.md) - Streamer context
- Database schema: `src/wecom_automation/database/schema.py`
