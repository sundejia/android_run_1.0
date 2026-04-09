# 定时 Follow-up 系统设计文档

## 概述

定时 Follow-up 系统是一个自动化的客户跟进系统，用于在企业微信中自动检测需要跟进的客户并发送跟进消息。系统支持多设备并行扫描、智能判断消息发送者、以及灵活的定时策略配置。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Vue.js)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Analytics  │  │    Data     │  │  Settings   │              │
│  │    Tab      │  │    Tab      │  │    Tab      │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          │                                       │
│                    REST API Calls                                │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│                    Backend (FastAPI)                             │
│                          │                                       │
│  ┌───────────────────────▼───────────────────────┐              │
│  │            followup.py (Router)                │              │
│  │  - GET  /api/followup/analytics               │              │
│  │  - GET  /api/followup/attempts                │              │
│  │  - POST /api/followup/scan                    │              │
│  │  - GET  /api/followup/scan/status             │              │
│  │  - POST /api/followup/settings                │              │
│  │  - WS   /ws/logs/followup                     │              │
│  └───────────────────────┬───────────────────────┘              │
│                          │                                       │
│  ┌───────────────────────▼───────────────────────┐              │
│  │         FollowUpService (Core Logic)          │              │
│  │  - run_multi_device_scan()                    │              │
│  │  - run_active_scan_for_device(serial)         │              │
│  │  - record_attempt()                           │              │
│  │  - find_or_create_customer()                  │              │
│  └───────────────────────┬───────────────────────┘              │
│                          │                                       │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│              Android Device Control (ADB)                        │
│                          │                                       │
│  ┌───────────────────────▼───────────────────────┐              │
│  │              WeComService                      │              │
│  │  - launch_wecom()                             │              │
│  │  - switch_to_private_chats()                  │              │
│  │  - click_user_in_list()                       │              │
│  │  - send_message()                             │              │
│  │  - go_back()                                  │              │
│  └───────────────────────────────────────────────┘              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 核心流程

### 1. 多设备并行扫描流程

```
用户点击 "Scan Now"
        │
        ▼
┌───────────────────┐
│  发现所有已连接设备  │  ← adbutils.adb.device_list()
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  并行启动设备扫描   │  ← asyncio.gather()
└─────────┬─────────┘
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
┌───────┐   ┌───────┐
│设备 A │   │设备 B │   ...
└───┬───┘   └───┬───┘
    │           │
    ▼           ▼
  扫描        扫描
    │           │
    └─────┬─────┘
          │
          ▼
┌───────────────────┐
│    聚合扫描结果     │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  更新数据库统计     │
└───────────────────┘
```

### 2. 单设备扫描流程

```
run_active_scan_for_device(serial)
        │
        ▼
┌─────────────────────────┐
│ Step 1: 连接设备         │
│ adbutils.adb.device()   │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Step 2: 初始化 WeComService │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Step 3: 启动企业微信      │
│ wecom.launch_wecom()    │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Step 4: 切换到私聊列表    │
│ switch_to_private_chats()│
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Step 5: 滚动提取所有用户  │
│ UnreadUserExtractor     │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Step 6: 滚动回顶部       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Step 7: 逐个处理用户     │
│ (详见用户处理流程)        │
└───────────────────────────┘
```

### 3. 单用户处理流程

```
处理用户 user_name
        │
        ▼
┌─────────────────────────┐
│ 点击用户打开聊天窗口      │
│ click_user_in_list()    │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 提取聊天消息             │
│ extract_conversation_messages() │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 获取最后一条消息         │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 判断消息是否为客服发送    │
│ _is_message_from_kefu() │
└───────────┬─────────────┘
            │
      ┌─────┴─────┐
      │           │
      ▼           ▼
   是客服       是客户
      │           │
      ▼           ▼
┌──────────┐ ┌──────────┐
│检查最大   │ │标记已回复 │
│尝试次数   │ │跳过此用户 │
└────┬─────┘ └──────────┘
     │
     ▼
┌──────────┐
│发送跟进   │
│消息      │
└────┬─────┘
     │
   ┌─┴─┐
   │   │
   ▼   ▼
 成功  失败
   │   │
   ▼   ▼
┌──────────┐
│记录到DB  │
│status=   │
│sent/failed│
└──────────┘
     │
     ▼
┌──────────┐
│返回列表   │
│go_back() │
└──────────┘
```

---

## 消息发送者判断逻辑

### 判断方法 `_is_message_from_kefu()`

企业微信聊天界面特点：

- **客服消息**：在屏幕右侧，通常不显示头像
- **客户消息**：在屏幕左侧，左侧显示头像

```
判断流程：
        │
        ▼
┌─────────────────────────┐
│ 1. 自动检测屏幕宽度      │
│    detect_screen_width() │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 2. 查找消息附近的头像    │
│    - 头像在左侧 → 客户   │
│    - 头像在右侧 → 客服   │
└───────────┬─────────────┘
            │
      未找到头像
            │
            ▼
┌─────────────────────────┐
│ 3. 查找消息气泡位置      │
│    - 气泡在右侧 → 客服   │
│    - 气泡在左侧 → 客户   │
└───────────┬─────────────┘
            │
      位置不明确
            │
            ▼
┌─────────────────────────┐
│ 4. 没有左侧头像 → 客服   │
│    (客服消息不显示头像)   │
└───────────────────────────┘
```

---

## 数据库设计

### 表结构

```sql
-- 客服表
CREATE TABLE kefus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    serial TEXT UNIQUE,           -- 设备序列号
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 客户表
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel TEXT,                  -- 渠道/分组
    kefu_id INTEGER,               -- 关联客服
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (kefu_id) REFERENCES kefus(id)
);

-- 跟进记录表
CREATE TABLE followup_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,  -- 第几次尝试
    status TEXT NOT NULL,             -- sent/failed/pending
    message_content TEXT,             -- 发送的消息内容
    message_preview TEXT,             -- 消息预览(前50字符)
    responded INTEGER DEFAULT 0,      -- 是否已回复
    response_time_seconds INTEGER,    -- 回复耗时(秒)
    created_at TIMESTAMP,
    sent_at TIMESTAMP,
    responded_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- 设置表
CREATE TABLE followup_settings (
    id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    scan_interval_seconds INTEGER DEFAULT 60,
    max_followups INTEGER DEFAULT 3,
    initial_delay_seconds INTEGER DEFAULT 120,
    subsequent_delay_seconds INTEGER DEFAULT 120,
    use_exponential_backoff INTEGER DEFAULT 0,
    backoff_multiplier REAL DEFAULT 2.0,
    enable_operating_hours INTEGER DEFAULT 1,
    start_hour INTEGER DEFAULT 10,
    end_hour INTEGER DEFAULT 22,
    updated_at TIMESTAMP
);
```

### 索引

```sql
-- 加速按客户和时间查询
CREATE INDEX idx_followup_attempts_customer
ON followup_attempts(customer_id, created_at);

-- 加速按日期统计
CREATE INDEX idx_followup_attempts_date
ON followup_attempts(created_at);
```

---

## 配置选项

| 配置项                    | 说明             | 默认值 |
| ------------------------- | ---------------- | ------ |
| `enabled`                 | 是否启用系统     | true   |
| `scan_interval`           | 扫描间隔(秒)     | 60     |
| `max_followups`           | 最大跟进次数     | 3      |
| `initial_delay`           | 首次跟进延迟(秒) | 120    |
| `subsequent_delay`        | 后续跟进延迟(秒) | 120    |
| `use_exponential_backoff` | 使用指数退避     | false  |
| `backoff_multiplier`      | 退避倍数         | 2.0    |
| `enable_operating_hours`  | 启用工作时间限制 | true   |
| `start_hour`              | 工作开始时间     | 10:00  |
| `end_hour`                | 工作结束时间     | 22:00  |

### 指数退避策略

当启用指数退避时，每次跟进的延迟递增：

```
第1次: initial_delay
第2次: initial_delay × multiplier
第3次: initial_delay × multiplier²
...
```

示例 (initial_delay=120s, multiplier=2):

- 第1次: 2分钟后
- 第2次: 4分钟后
- 第3次: 8分钟后

---

## API 端点

### REST API

| 方法   | 路径                        | 说明                |
| ------ | --------------------------- | ------------------- |
| GET    | `/api/followup/analytics`   | 获取统计数据        |
| GET    | `/api/followup/attempts`    | 获取跟进记录(分页)  |
| POST   | `/api/followup/scan`        | 触发手动扫描        |
| GET    | `/api/followup/scan/status` | 获取扫描状态        |
| GET    | `/api/followup/settings`    | 获取设置            |
| POST   | `/api/followup/settings`    | 更新设置            |
| DELETE | `/api/followup/attempts`    | 清空所有记录        |
| GET    | `/api/followup/export`      | 导出数据(CSV/Excel) |

### WebSocket

| 路径                | 说明       |
| ------------------- | ---------- |
| `/ws/logs/followup` | 实时日志流 |

---

## 日志系统

### 日志级别

- **INFO**: 正常操作流程
- **WARNING**: 警告信息(跳过用户、超过限制等)
- **ERROR**: 错误信息(发送失败、连接错误等)

### 日志格式

```
[设备序列号] [步骤] 消息内容
```

示例：

```
[320125365403] Step 1: Connected to device
[320125365403] Step 5: Extracting users from chat list...
[320125365403] [1/15] Processing: 张三
[320125365403]   📤 Sending follow-up #1: "您好，请问还有什么需要了解的吗？..."
[320125365403]   ✅ Follow-up #1 sent and recorded!
```

### 日志查看

1. **Logs 页面**: `/logs/followup` - 实时查看日志流
2. **终端输出**: 开发模式下同步输出到控制台

---

## 前端界面

### Analytics 标签页

显示统计数据：

- 总跟进次数
- 回复率
- 平均响应时间
- 成功/失败数量
- 7天/30天趋势图
- 成功/失败分布饼图

### Data 标签页

显示跟进记录列表：

- 分页显示
- 过滤器(日期、状态、是否回复)
- 导出功能(CSV/Excel)
- 批量删除

### Settings 标签页

配置系统参数：

- 启用/禁用
- 扫描间隔
- 最大跟进次数
- 延迟设置
- 工作时间设置

---

## 扩展点

### 1. 自定义跟进消息

当前使用固定消息模板，可扩展为：

- 从数据库读取模板
- 根据客户标签选择模板
- 接入AI生成个性化消息

### 2. 条件跟进规则

可添加更复杂的跟进条件：

- 基于客户分组
- 基于消息内容关键词
- 基于历史互动记录

### 3. 多平台支持

当前仅支持企业微信，可扩展到：

- 个人微信
- 其他IM平台

### 4. 报警机制

添加异常报警：

- 失败率过高报警
- 设备离线报警
- 运行异常报警

---

## 注意事项

1. **反检测**: 操作之间添加随机延迟，模拟人工操作
2. **并发控制**: 每个设备单独一个任务，避免操作冲突
3. **错误恢复**: 单用户处理失败不影响其他用户
4. **数据一致性**: 操作结果实时写入数据库
5. **资源释放**: 扫描完成后正确释放连接资源

---

## 版本历史

| 版本 | 日期    | 更新内容                     |
| ---- | ------- | ---------------------------- |
| 1.0  | 2024-12 | 初始版本，支持多设备并行扫描 |
