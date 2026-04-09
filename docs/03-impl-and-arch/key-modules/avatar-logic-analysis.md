# 头像获取和显示逻辑分析

## 概述

本文档分析企业微信自动化系统中头像的获取、存储、匹配和前端显示的完整逻辑流程。

## 系统架构

### 核心组件

1. **后端头像服务** (`src/wecom_automation/services/user/avatar.py`)
2. **后端API路由** (`wecom-desktop/backend/routers/avatars.py`)
3. **前端头像工具** (`wecom-desktop/src/utils/avatars.ts`)
4. **WeCom服务集成** (`src/wecom_automation/services/wecom_service.py`)

### 数据流

```
用户列表提取 → 头像捕获 → 存储到本地 → 前端API获取 → 匹配算法 → 显示头像
```

## 1. 头像获取流程

### 1.1 触发时机

头像捕获在以下场景中触发：

1. **用户列表提取时** - `WeComService.extract_private_chat_users()`

   ```python
   # 提取用户列表后
   if capture_avatars and users:
       await self._capture_avatars(users, output_dir)
   ```

2. **对话同步时** - 通过 `AvatarManager.capture_if_needed()` 按需捕获

### 1.2 头像捕获算法

#### UI树分析 (`AvatarManager._find_avatar_in_tree()`)

```python
def _find_avatar_in_tree(self, tree: Any, name: str) -> Optional[Tuple[int, int, int, int]]:
    # 1. 找到用户名节点
    for node in nodes:
        if node.get("text", "").strip() == name:
            name_node = node
            break

    # 2. 获取用户名位置
    name_bounds = self._get_node_bounds(name_node)
    name_y = name_parsed[1]  # y1坐标

    # 3. 查找同一行的头像元素
    for node in nodes:
        # 检查是否像头像的条件：
        # - 资源ID包含头像关键词
        # - 或(类名包含头像关键词 且 在左侧 且 尺寸合理 且 接近正方形)
        # - 且在同一行 (y坐标相近)
```

#### 头像识别条件

```python
# 位置条件
is_left_side = x1 < 200  # 在屏幕左侧
is_same_row = abs(y1 - name_y) < 100  # 与用户名在同一行

# 尺寸条件
width = x2 - x1
height = y2 - y1
is_avatar_size = 40 <= width <= 150 and 40 <= height <= 150  # 合理尺寸
aspect_ratio = width / height
is_square = 0.7 <= aspect_ratio <= 1.3  # 接近正方形

# 类型识别
is_avatar_rid = any(hint in resource_id for hint in AVATAR_RESOURCE_ID_HINTS)
is_avatar_class = any(hint in class_name for hint in AVATAR_CLASS_HINTS)

# 最终判断
if is_same_row and (is_avatar_rid or (is_avatar_class and is_left_side and is_avatar_size and is_square)):
    return parsed  # 返回头像坐标
```

#### 截图保存 (`WeComService._capture_avatars()`)

```python
# 1. 滚动到顶部确保从头开始
await self.adb.scroll_to_top()

# 2. 循环处理每一屏用户
while len(captured_keys) < len(users) and attempt < max_attempts:
    # 获取当前可见用户
    tree = await self.adb.get_ui_tree()
    current_users = self.ui_parser.extract_users_from_tree(tree)

    # 截取全屏截图
    _, image_bytes = await self.adb.take_screenshot()
    full_image = Image.open(BytesIO(image_bytes))

    # 3. 处理每个用户的头像
    for user in users:
        if user.avatar and user.avatar.parse_bounds():
            x1, y1, x2, y2 = user.avatar.x1, user.avatar.y1, user.avatar.x2, user.avatar.y2

            # 验证坐标有效性
            if (x1 >= 0 and y1 >= 0 and x2 <= img_width and y2 <= img_height and
                30 <= (x2-x1) <= 300 and 30 <= (y2-y1) <= 300 and
                y2 <= img_height * 0.92):  # 避免截到屏幕底部

                # 裁剪并保存
                avatar_crop = full_image.crop((x1, y1, x2, y2))
                filename = f"avatar_{idx+1:02d}_{safe_name}.png"
                avatar_path = avatar_dir / filename
                avatar_crop.save(avatar_path)
```

### 1.3 文件命名规范

头像文件命名格式：`avatar_{序号}_{用户名}.png`

- **序号**: 两位数字，从01开始，确保排序
- **用户名**: 清理后的安全文件名（只保留字母数字和-_.,其他替换为_）
- **示例**: `avatar_01_张三.png`, `avatar_02_li_si@wechat.png`

## 2. 头像存储和API

### 2.1 存储位置

- **目录**: `{PROJECT_ROOT}/avatars/`
- **默认头像**: `avatar_default.png` (用于未匹配的用户)

### 2.2 后端API接口

#### 文件服务 (`/avatars/{filename}`)

```python
@router.get("/{filename}")
async def get_avatar_file(filename: str):
    # 安全检查：防止路径遍历
    if '..' in filename or filename.startswith('/'):
        raise HTTPException(status_code=404, detail="Avatar not found")

    file_path = AVATARS_DIR / filename

    # 安全验证：确保在允许目录内
    file_path = file_path.resolve()
    if not str(file_path).startswith(str(AVATARS_DIR.resolve())):
        raise HTTPException(status_code=404, detail="Avatar not found")

    # 返回文件
    return FileResponse(path=str(file_path), media_type=get_media_type(filename))
```

#### 头像列表 (`/avatars/`)

```python
@router.get("/", response_model=AvatarListResponse)
async def list_avatars():
    avatars = _get_avatar_files()  # 排除默认头像
    return AvatarListResponse(
        avatars=avatars,
        avatars_dir=str(AVATARS_DIR),
    )
```

#### 按用户名查找 (`/avatars/by-name/{name}`)

```python
@router.get("/by-name/{name}", response_model=AvatarLookupResponse)
async def get_avatar_by_name(name: str):
    avatar = _find_matching_avatar(name)

    if avatar:
        return AvatarLookupResponse(
            found=True,
            name=name,
            url=f"/avatars/{avatar.filename}",
            filename=avatar.filename,
        )

    # 返回默认头像
    return AvatarLookupResponse(
        found=False,
        name=name,
        url="/avatars/avatar_default.png",
        filename="avatar_default.png",
    )
```

#### 元数据接口 (`/avatars/metadata`)

```python
@router.get("/metadata")
async def get_avatars_metadata():
    """返回头像文件名和名称的映射，用于前端缓存"""
    avatars = _get_avatar_files()
    return [{"filename": a.filename, "name": a.name} for a in avatars]
```

## 3. 前端头像匹配和显示

### 3.1 头像加载策略

#### 动态加载 (`loadAvatarsFromBackend()`)

```typescript
async function loadAvatarsFromBackend(): Promise<void> {
  // 优先从后端API加载
  try {
    const resp = await fetch(`${API_BASE}/avatars/metadata`)
    if (resp.ok) {
      const data = await resp.json()
      avatarFiles = data // [{filename, name}, ...]
      return
    }
  } catch {
    // API失败，回退到静态JSON
  }

  // 回退：从静态JSON加载
  try {
    const staticResp = await fetch('/avatars/avatars.json')
    // ...
  } catch {
    // 使用硬编码回退
  }
}
```

### 3.2 名称匹配算法

#### 规范化处理 (`normalizeName()`)

```typescript
function normalizeName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\u4e00-\u9fff\-_.]/g, '_') // 只保留字母数字中文和特定符号
}
```

**重要**: 前后端使用相同的规范化算法，确保匹配一致性。

#### 匹配策略 (`findMatchingAvatar()`)

```typescript
function findMatchingAvatar(customerName: string): string | null {
  const normalized = normalizeName(customerName)

  // 1. 精确匹配
  for (const avatar of avatarFiles) {
    if (normalizeName(avatar.name) === normalized) {
      return `${API_BASE}/avatars/${avatar.filename}`
    }
  }

  // 2. 前缀匹配（按名称长度降序，避免"张三"和"张三丰"的冲突）
  const sortedByLength = [...avatarFiles].sort((a, b) => b.name.length - a.name.length)
  for (const avatar of sortedByLength) {
    const avatarNorm = normalizeName(avatar.name)
    if (normalized.startsWith(avatarNorm)) {
      return `${API_BASE}/avatars/${avatar.filename}`
    }
  }

  // 3. 反向包含匹配（头像名包含客户名）
  for (const avatar of avatarFiles) {
    const avatarNorm = normalizeName(avatar.name)
    if (avatarNorm.startsWith(normalized) && normalized.length >= 2) {
      return `${API_BASE}/avatars/${avatar.filename}`
    }
  }

  return null
}
```

### 3.3 头像URL生成

#### 客户头像 (`avatarUrlForCustomer()`)

```typescript
export function avatarUrlForCustomer(
  customer: Pick<CustomerSummary, 'id' | 'name' | 'channel'>
): string {
  // 1. 尝试按名称匹配
  if (customer.name) {
    const matched = findMatchingAvatar(customer.name)
    if (matched) {
      return matched
    }
  }

  // 2. 回退到哈希选择
  const seed = [customer.name, customer.channel, customer.id].filter(Boolean).join('|')
  return pickAvatarByHash(seed || 'customer')
}
```

#### 通用种子头像 (`avatarUrlFromSeed()`)

```typescript
export function avatarUrlFromSeed(seed: string | number | null | undefined): string {
  const seedStr = String(seed ?? 'default')

  // 1. 尝试按种子匹配
  const matched = findMatchingAvatar(seedStr)
  if (matched) {
    return matched
  }

  // 2. 哈希选择
  return pickAvatarByHash(seedStr)
}
```

### 3.4 哈希回退算法 (`pickAvatarByHash()`)

```typescript
function pickAvatarByHash(seed: string): string {
  if (avatarFiles.length === 0) {
    return `${API_BASE}/avatars/avatar_default.png`
  }

  // DJB2哈希算法
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }

  const index = hash % avatarFiles.length
  return `${API_BASE}/avatars/${avatarFiles[index].filename}`
}
```

### 3.5 前端显示组件

#### 头像图片组件

```vue
<img
  :src="avatarUrlForCustomer(customer)"
  :alt="`Avatar for ${customer.name}`"
  class="w-10 h-10 rounded-full border border-wecom-border bg-wecom-surface object-cover shrink-0"
/>
```

## 4. 匹配示例

### 成功匹配场景

| 客户名称     | 头像文件名           | 匹配方式 | 结果 |
| ------------ | -------------------- | -------- | ---- |
| `张三`       | `avatar_01_张三.png` | 精确匹配 | ✅   |
| `sdj@微信`   | `avatar_02_sdj.png`  | 前缀匹配 | ✅   |
| `李四(工作)` | `avatar_03_李四.png` | 包含匹配 | ✅   |

### 匹配失败场景

| 客户名称 | 可用头像             | 结果     | 回退方式             |
| -------- | -------------------- | -------- | -------------------- |
| `王五`   | 无匹配头像           | 默认头像 | `avatar_default.png` |
| `赵六`   | `avatar_01_张三.png` | 哈希选择 | 基于姓名的哈希选择   |

## 5. 性能优化

### 5.1 前端缓存

- **内存缓存**: `avatarFiles` 数组存储已加载的头像元数据
- **加载状态**: `avatarsLoaded` 防止重复加载
- **Promise缓存**: `loadingPromise` 避免并发加载

### 5.2 后端优化

- **文件直接服务**: 使用 `FileResponse` 直接返回文件，无需读取到内存
- **路径安全**: 防止目录遍历攻击
- **媒体类型检测**: 根据文件扩展名返回正确的MIME类型

### 5.3 匹配优化

- **长度优先**: 在前缀匹配时按名称长度降序排序，避免短名匹配到长名
- **规范化缓存**: 规范化后的名称可考虑缓存
- **早期退出**: 找到匹配后立即返回

## 6. 故障排除

### 6.1 头像不显示

**可能原因**:

1. 后端API未运行
2. 头像文件不存在
3. 网络连接问题
4. 匹配算法失败

**排查步骤**:

1. 检查 `/avatars/metadata` API返回数据
2. 验证头像文件是否存在
3. 检查浏览器网络请求
4. 查看控制台错误信息

### 6.2 头像匹配错误

**可能原因**:

1. 名称规范化不一致
2. 特殊字符处理问题
3. 相似名称冲突

**排查步骤**:

1. 比较前后端的 `normalizeName()` 输出
2. 检查头像文件名格式
3. 验证匹配优先级逻辑

### 6.3 性能问题

**可能原因**:

1. 头像文件过大
2. 并发加载过多
3. 匹配算法效率低

**优化建议**:

1. 压缩头像文件
2. 实现懒加载
3. 添加匹配结果缓存

## 7. 扩展性

### 7.1 新匹配算法

可以通过修改 `findMatchingAvatar()` 函数添加新的匹配策略：

```typescript
// 示例：添加昵称匹配
function findMatchingAvatar(customerName: string): string | null {
  // ... 现有逻辑 ...

  // 4. 昵称匹配（如果有昵称映射表）
  const nickname = getNickname(customerName)
  if (nickname) {
    // 递归匹配昵称
    return findMatchingAvatar(nickname)
  }

  return null
}
```

### 7.2 头像质量优化

```python
# 在保存头像时进行质量优化
avatar_crop = full_image.crop((x1, y1, x2, y2))

# 调整大小为标准尺寸
avatar_crop = avatar_crop.resize((100, 100), Image.LANCZOS)

# 压缩质量
avatar_crop.save(avatar_path, quality=85, optimize=True)
```

### 7.3 头像更新机制

```typescript
// 添加头像刷新功能
export async function refreshAvatars(): Promise<void> {
  avatarsLoaded = false
  loadingPromise = null
  await loadAvatarsFromBackend()

  // 通知所有使用头像的组件刷新
  emitAvatarRefresh()
}
```

## 总结

头像系统采用了分层设计：

1. **捕获层**: UI分析和截图保存
2. **存储层**: 文件系统和API服务
3. **匹配层**: 智能名称匹配算法
4. **显示层**: 前端缓存和URL生成

这种设计确保了头像的高可用性（有默认头像回退）、高性能（前端缓存和优化匹配）和良好的用户体验（智能匹配和哈希回退）。
