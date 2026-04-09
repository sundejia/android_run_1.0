# Sidecar 界面显示图片方案

**日期**: 2026-01-18
**状态**: ✅ 已实施

## 1. 当前状态

目前 Sidecar 界面对于图片消息只显示 `[image] [图片]` 文字标签，而不是实际的图片缩略图。

**当前渲染逻辑** (`SidecarView.vue` Line 1722-1725):

```vue
<div class="break-words whitespace-pre-wrap text-sm">
  <span v-if="msg.message_type !== 'text'" class="opacity-70">[{{ msg.message_type }}] </span>
  {{ msg.content || '(no content)' }}
</div>
```

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        数据库层 (SQLite)                      │
├──────────────────────────────────────────────────────────────┤
│ messages 表: id, content, message_type, ...                  │
│ images 表: id, message_id, file_path, width, height, ...     │
│              └──> 关联到 messages.id                          │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│         后端 API (sidecar.py)                                 │
│ GE../03-impl-and-arch/{serial}/conversation-history                   │
│ 返回: ConversationHistoryMessage (不包含 image_url)           │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│         前端 (SidecarView.vue)                                │
│ 只渲染 msg.content 文本，不处理图片                            │
└──────────────────────────────────────────────────────────────┘
```

## 3. 实现方案

### 3.1 后端修改

#### 3.1.1 新增图片服务端点

在 `backend/routers/sidecar.py` 中添加静态文件服务：

```python
from fastapi.responses import FileResponse
from pathlib import Path

@router.get("/images/{image_path:path}")
async def serve_image(image_path: str):
    """Serve image files from the conversation_images directory."""
    # 构建完整路径 (需要配置 base path)
    base_dir = Path("conversation_images")
    full_path = base_dir / image_path

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(full_path, media_type="image/png")
```

#### 3.1.2 扩展消息响应模型

修改 `ConversationHistoryMessage` 以包含图片信息：

```python
class ConversationHistoryMessage(BaseModel):
    id: int
    content: Optional[str] = None
    message_type: str
    is_from_kefu: bool
    timestamp_raw: Optional[str] = None
    timestamp_parsed: Optional[str] = None
    extra_info: Optional[str] = None
    created_at: str
    # 新增字段
    image_url: Optional[str] = None      # 图片访问 URL
    image_width: Optional[int] = None    # 图片宽度
    image_height: Optional[int] = None   # 图片高度
```

#### 3.1.3 修改消息查询逻辑

在 `get_conversation_history` 中 JOIN images 表：

```python
cursor.execute(
    """
    SELECT
        m.id,
        m.content,
        m.message_type,
        m.is_from_kefu,
        m.timestamp_raw,
        m.timestamp_parsed,
        m.extra_info,
        m.created_at,
        m.ui_position,
        i.file_path as image_path,
        i.width as image_width,
        i.height as image_height
    FROM messages m
    LEFT JOIN images i ON m.id = i.message_id
    WHERE m.customer_id = ?
    ORDER BY ...
    LIMIT ?
    """,
    (customer_id, limit)
)

# 构造响应时生成图片 URL
for row in messages_raw:
    image_url = None
    if row["image_path"]:
        # 转换本地路径为 API URL
        image_url = f"/a../03-impl-and-arch/images/{row['image_path']}"

    messages.append(ConversationHistoryMessage(
        ...
        image_url=image_url,
        image_width=row["image_width"],
        image_height=row["image_height"],
    ))
```

### 3.2 前端修改

#### 3.2.1 更新 TypeScript 类型

在 `api.ts` 中扩展类型定义：

```typescript
export interface ConversationHistoryMessage {
  id: number
  content: string | null
  message_type: string
  is_from_kefu: boolean
  timestamp_raw: string | null
  timestamp_parsed: string | null
  extra_info: string | null
  created_at: string
  // 新增
  image_url?: string
  image_width?: number
  image_height?: number
}
```

#### 3.2.2 修改消息渲染模板

在 `SidecarView.vue` 中处理图片显示：

```vue
<div class="break-words whitespace-pre-wrap text-sm">
  <!-- 图片消息 -->
  <template v-if="msg.message_type === 'image' && msg.image_url">
    <img
      :src="msg.image_url"
      :alt="msg.content || '图片'"
      class="max-w-[200px] max-h-[200px] rounded cursor-pointer hover:opacity-90 transition-opacity"
      @click="openImagePreview(msg.image_url)"
      @error="handleImageError($event)"
    />
    <div v-if="msg.content && msg.content !== '[图片]'" class="text-xs mt-1 opacity-70">
      {{ msg.content }}
    </div>
  </template>

  <!-- 图片消息但无图片文件 -->
  <template v-else-if="msg.message_type === 'image'">
    <div class="flex items-center gap-2 text-wecom-muted">
      <span>🖼️</span>
      <span class="opacity-70">[图片不可用]</span>
    </div>
  </template>

  <!-- 其他消息类型 -->
  <template v-else>
    <span v-if="msg.message_type !== 'text'" class="opacity-70">[{{ msg.message_type }}] </span>
    {{ msg.content || '(no content)' }}
  </template>
</div>
```

#### 3.2.3 图片预览功能 (可选)

添加点击放大查看功能：

```typescript
const previewImageUrl = ref<string | null>(null)

function openImagePreview(url: string) {
  previewImageUrl.value = url
}

function closeImagePreview() {
  previewImageUrl.value = null
}
```

```vue
<!-- 图片预览遮罩层 -->
<div
  v-if="previewImageUrl"
  class="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
  @click="closeImagePreview()"
>
  <img 
    :src="previewImageUrl" 
    class="max-w-[90vw] max-h-[90vh] object-contain"
  />
</div>
```

## 4. 实现步骤

| 步骤 | 描述                         | 文件                         | 复杂度 |
| :--- | :--------------------------- | :--------------------------- | :----- |
| 1    | 添加图片静态文件服务端点     | `backend/routers/sidecar.py` | 低     |
| 2    | 扩展消息响应模型             | `backend/routers/sidecar.py` | 低     |
| 3    | 修改 SQL 查询 JOIN images 表 | `backend/routers/sidecar.py` | 中     |
| 4    | 更新 TypeScript 类型定义     | `src/services/api.ts`        | 低     |
| 5    | 修改消息渲染模板             | `src/views/SidecarView.vue`  | 中     |
| 6    | (可选) 添加图片预览功能      | `src/views/SidecarView.vue`  | 低     |

## 5. 注意事项

1. **路径处理**: 数据库中存储的 `file_path` 可能是绝对路径或相对路径，需要统一处理。
2. **安全性**: 图片服务端点需要验证路径不会访问系统敏感目录（路径遍历攻击）。
3. **性能**: 对于大量图片，考虑使用懒加载 (`loading="lazy"`)。
4. **缓存**: 可以在前端使用 `<img>` 标签的浏览器缓存，或在后端添加 Cache-Control 头。

## 6. 预期效果

修改后，Sidecar 界面将：

- 对于有图片文件的消息：显示图片缩略图（最大 200x200）
- 对于图片文件缺失的消息：显示 "🖼️ [图片不可用]" 占位符
- 点击图片可放大查看（可选功能）
