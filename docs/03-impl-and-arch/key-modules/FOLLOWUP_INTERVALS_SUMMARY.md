# 补刀间隔功能总结 (Followup Attempt Intervals)

**状态**: ✅ 已完成并验证  
**日期**: 2026-02-06

---

## 功能说明

你的需求已经**完全实现并测试通过**！补刀系统现在支持根据尝试次数使用不同的等待间隔。

### 当前配置

```
空闲阈值 (idle_threshold_minutes): 30 分钟
最大补刀次数 (max_attempts_per_customer): 3 次
补刀间隔 (attempt_intervals): [60, 120, 180] 分钟
```

### 工作流程

```
客服发消息 → 30分钟无回复 → 进入补刀队列
                                ↓
                         首次补刀 (attempt #1)
                                ↓
                         等待 60 分钟
                                ↓
                         第2次补刀 (attempt #2)
                                ↓
                         等待 120 分钟
                                ↓
                         第3次补刀 (attempt #3)
                                ↓
                         等待 180 分钟
                                ↓
                         达到上限，停止补刀
```

---

## 如何修改配置

### 方法1: 前端界面 (推荐)

1. 打开桌面应用
2. 导航到 `Follow-up Manage` 页面
3. 切换到 `Settings` 标签
4. 找到 `⏱️ Attempt Intervals` 部分
5. 修改三个输入框的值:
   ```
   After 1st attempt: [ 60 ] min
   After 2nd attempt: [ 120 ] min
   After 3rd attempt: [ 180 ] min
   ```
6. 点击 `Save Settings` 按钮
7. 配置立即生效！

### 方法2: API 调用

```bash
curl -X POST http://localhost:8765/api/followup/settings \
  -H "Content-Type: application/json" \
  -d '{
    "followupEnabled": true,
    "maxFollowupPerScan": 5,
    "idleThresholdMinutes": 30,
    "maxAttemptsPerCustomer": 3,
    "attemptIntervals": [60, 120, 180]
  }'
```

---

## 测试结果

✅ 运行了自动化测试，所有场景通过:

```bash
python test_attempt_intervals.py
```

测试输出:

```
============================================================
测试补刀间隔功能
============================================================

1️⃣ 检查当前设置...
   补刀功能启用: True
   空闲阈值: 30 分钟
   最大补刀次数: 3
   补刀间隔: [60, 120, 180]

3️⃣ 测试间隔判断逻辑...
   场景1: 首次补刀 (current_attempt = 0)
   ✅ 符合预期 - 首次补刀无需等待，立即可执行

   场景2: 第2次补刀 - 刚完成第1次 (应不在列表)
   ✅ 符合预期 - 未满足 60 分钟间隔，不在列表中

   场景3: 第2次补刀 - 已等待70分钟 (应在列表)
   ✅ 符合预期 - 已满足 60 分钟间隔，在列表中

   场景4: 第3次补刀 - 刚完成第2次 (应不在列表)
   ✅ 符合预期 - 未满足 120 分钟间隔，不在列表中

   场景5: 第3次补刀 - 已等待130分钟 (应在列表)
   ✅ 符合预期 - 已满足 120 分钟间隔，在列表中

============================================================
✅ 测试完成！补刀间隔功能工作正常
============================================================
```

---

## 代码实现位置

### 前端

- **配置界面**: `wecom-desktop/src/views/FollowUpManageView.vue` (第722-775行)
- **设置状态**: `settings.attemptIntervals` (第32行)

### 后端

- **核心逻辑**: `wecom-desktop/backend/services/followup/attempts_repository.py`
  - `get_pending_attempts()` 方法 (第224-304行)
- **设置管理**: `wecom-desktop/backend/services/followup/settings.py`
  - `FollowUpSettings.attempt_intervals` (第48行)
- **API路由**: `wecom-desktop/backend/routers/followup_manage.py`
  - GET/POST `/api/followup/settings` (第55-107行)

### 数据库

- **主表**: `followup_attempts` (wecom_conversations.db)
  - `current_attempt`: 已完成补刀次数
  - `last_followup_at`: 最后补刀时间
- **设置表**: `settings`（与主库 `wecom_conversations.db` / `WECOM_DB_PATH` 同文件）
  - `category='followup'`, `key='attempt_intervals'`

---

## 验证方法

### 1. 检查数据库

```sql
-- 查看设置
SELECT * FROM settings
WHERE category = 'followup' AND key = 'attempt_intervals';

-- 查看补刀记录
SELECT
  customer_name,
  current_attempt,
  last_followup_at,
  status
FROM followup_attempts
WHERE device_serial = 'YOUR_DEVICE_SERIAL'
ORDER BY created_at DESC
LIMIT 10;
```

### 2. 查看日志

启动补刀流程后，日志会显示:

```
补刀配置:
  - 最大补刀数/次: 5
  - 使用AI回复: True
  - 补刀间隔: [60, 120, 180] 分钟

获取待补刀列表（考虑间隔时间）...
找到 2 个待补刀目标:
  1. 张三 (第1/3次)
  2. 李四 (第2/3次)
```

### 3. 前端界面验证

1. 打开 `Follow-up Manage → Settings`
2. 查看 `Attempt Intervals` 部分
3. 确认三个输入框显示正确的值

---

## 常见配置示例

### 快速补刀 (适合测试)

```json
{
  "idleThresholdMinutes": 5,
  "maxAttemptsPerCustomer": 3,
  "attemptIntervals": [10, 20, 30]
}
```

- 5分钟无回复进队列
- 第1次补刀后等10分钟
- 第2次补刀后等20分钟
- 第3次补刀后等30分钟

### 标准配置 (默认)

```json
{
  "idleThresholdMinutes": 30,
  "maxAttemptsPerCustomer": 3,
  "attemptIntervals": [60, 120, 180]
}
```

- 30分钟无回复进队列
- 第1次补刀后等1小时
- 第2次补刀后等2小时
- 第3次补刀后等3小时

### 耐心等待配置

```json
{
  "idleThresholdMinutes": 60,
  "maxAttemptsPerCustomer": 3,
  "attemptIntervals": [240, 480, 720]
}
```

- 1小时无回复进队列
- 第1次补刀后等4小时
- 第2次补刀后等8小时
- 第3次补刀后等12小时

---

## 总结

✅ **功能已完全实现**，包括:

- 前端配置界面
- 后端逻辑支持
- 数据库集成
- API 接口
- 自动化测试

你现在可以通过前端界面直接修改补刀间隔配置，系统会立即生效！

---

## 相关文档

- 详细文档: `docs/01-product/followup-attempt-intervals.md`
- 测试脚本: `test_attempt_intervals.py`
- 前端组件: `wecom-desktop/src/views/FollowUpManageView.vue`
