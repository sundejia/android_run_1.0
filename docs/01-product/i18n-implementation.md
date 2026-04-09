# 前端国际化 (i18n) 集中式系统实现方案

## 概述

为 WeCom Desktop 实现集中式国际化系统，包含：

- 后端翻译存储与 API
- 客户端翻译应用
- 语言偏好持久化
- 动态语言切换

### ✅ 前置工作已完成

**页面英文化**：所有前端页面已经统一调整为纯英文界面，包括：

- `SidecarView.vue` - 状态消息、按钮标签
- `StreamerDetailView.vue` - 表单标签
- `SettingsView.vue` - 设置项
- `FollowUpView.vue` - 状态提示
- `CustomerDetailView.vue` - 字段标签
- `BlacklistView.vue` - 表头、操作按钮
- 其他组件

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Vue 3)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ LanguageSwitch│  │   useI18n()  │  │  <template>          │   │
│  │   Component   │  │  Composable  │  │  {{ $t('key') }}     │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│         └─────────────────┼──────────────────────┘               │
│                           ▼                                      │
│              ┌────────────────────────┐                          │
│              │   i18n Store (Pinia)   │                          │
│              │  - currentLanguage     │                          │
│              │  - translations        │                          │
│              │  - t(key, params)      │                          │
│              └───────────┬────────────┘                          │
└──────────────────────────┼──────────────────────────────────────┘
                           │ API Calls
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   /a../03-impl-and-arch/key-modules/*                        │    │
│  │  GET  /language         - 获取当前语言                    │    │
│  │  PUT  /language         - 设置语言                        │    │
│  │  GET  /translations     - 获取所有翻译                    │    │
│  │  GET  /translations/{category} - 获取分类翻译             │    │
│  └───────────────────────────┬─────────────────────────────┘    │
│                              │                                   │
│  ┌───────────────────────────▼─────────────────────────────┐    │
│  │              Translations Module                         │    │
│  │  translations.py - 翻译字典存储                          │    │
│  │  get_translation(lang, category, key)                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│  ┌───────────────────────────▼─────────────────────────────┐    │
│  │              Database (SQLite)                           │    │
│  │  system_settings: key, value, updated_at                │    │
│  │  - 持久化语言偏好                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 阶段一：后端翻译存储

### 1.1 目录结构

```
wecom-desktop/backend/
├── i18n/
│   ├── __init__.py           # 导出翻译函数
│   └── translations.py       # 翻译字典存储
├── routers/
│   └── i18n.py               # 翻译 API 端点
└── models/
    └── system_settings.py    # 系统设置模型
```

### 1.2 翻译存储模块

**文件**: `wecom-desktop/backend/i18n/translations.py`

```python
"""
集中式翻译存储

所有翻译按语言和分类组织，便于维护和查找。
"""

from typing import Any, Dict, Optional

# 支持的语言列表
SUPPORTED_LANGUAGES = {
    "en": "English",
    "zh-CN": "简体中文",
}

DEFAULT_LANGUAGE = "en"

# 翻译字典
TRANSLATIONS: Dict[str, Dict[str, Dict[str, str]]] = {
    "en": {
        # 通用 UI 元素
        "common": {
            "save": "Save",
            "cancel": "Cancel",
            "confirm": "Confirm",
            "delete": "Delete",
            "edit": "Edit",
            "add": "Add",
            "search": "Search",
            "loading": "Loading...",
            "error": "Error",
            "success": "Success",
            "warning": "Warning",
            "no_data": "No data available",
            "actions": "Actions",
            "status": "Status",
            "name": "Name",
            "type": "Type",
            "time": "Time",
            "date": "Date",
            "refresh": "Refresh",
            "close": "Close",
            "back": "Back",
            "next": "Next",
            "previous": "Previous",
            "submit": "Submit",
            "reset": "Reset",
            "yes": "Yes",
            "no": "No",
        },

        # 导航菜单
        "nav": {
            "dashboard": "Dashboard",
            "devices": "Devices",
            "customers": "Customers",
            "kefus": "Agents",
            "streamers": "Streamers",
            "settings": "Settings",
            "followup": "Follow-up",
            "blacklist": "Blacklist",
            "sidecar": "Sidecar",
            "logs": "Logs",
            "resources": "Resources",
        },

        # 仪表盘页面
        "dashboard": {
            "title": "Dashboard",
            "total_customers": "Total Customers",
            "messages_today": "Messages Today",
            "ai_replies": "AI Replies",
            "engagement_rate": "Engagement Rate",
            "active_devices": "Active Devices",
            "recent_activity": "Recent Activity",
        },

        # Sidecar 页面
        "sidecar": {
            "ready_to_send": "Ready to send, {seconds}s countdown available",
            "sending": "Sending...",
            "sent": "Sent",
            "send_failed": "Send failed",
            "editing_paused": "Editing, countdown paused",
            "edit_done": "Edit done, click Resume to continue",
            "no_content": "No content to send",
            "countdown_started": "Countdown started, sending in {seconds}s",
            "sending_immediate": "Countdown 0, sending immediately",
            "operator_edited": "Operator edited AI reply (original: {original}, new: {new})",
            "operator_approved": "Operator approved AI reply",
            "sent_and_saved": "Sent and saved",
            "sent_not_saved": "Sent (not saved to database)",
            "ai_learning_improved": "AI Learning: Prompt auto-improved",
            "ai_learning_suggestion": "AI Learning: New suggestion available (check settings)",
            "voice_skipped": "User sent voice, skipped and blacklisted",
            "human_requested": "User requested human agent, skipped and blacklisted",
            "send": "Send",
            "start": "Start",
            "pause": "Pause",
            "resume": "Resume",
            "stop": "Stop",
            "test_message": "Test message",
        },

        # 媒体相关
        "media": {
            "image": "Image",
            "image_unavailable": "Image unavailable",
            "video": "Video",
            "voice": "Voice",
            "preview_image": "Preview image",
            "click_to_close": "Click anywhere to close",
        },

        # 设置页面
        "settings": {
            "title": "Settings",
            "language": "Language",
            "theme": "Theme",
            "ai_config": "AI Configuration",
            "email_notification": "Email Notification",
            "suggestion_empty": "Suggestion content cannot be empty",
            "save_success": "Settings saved successfully",
            "save_failed": "Failed to save settings",
        },

        # 客服信息
        "streamer": {
            "gender": "Gender",
            "age": "Age",
            "location": "Location",
            "height": "Height (cm)",
            "weight": "Weight (kg)",
            "education": "Education",
            "occupation": "Occupation",
            "interests": "Interests",
            "social_platforms": "Social Platforms",
            "notes": "Notes",
            "male": "Male",
            "female": "Female",
            "other": "Other",
            "high_school": "High School",
            "associate": "Associate",
            "bachelor": "Bachelor",
            "master": "Master",
            "phd": "PhD",
        },

        # Follow-up 页面
        "followup": {
            "title": "Follow-up System",
            "scanning": "Scanning...",
            "paused": "Paused",
            "running": "Running",
            "stopped": "Stopped",
            "start_scan": "Start Scan",
            "stop_scan": "Stop Scan",
            "scan_interval": "Scan Interval",
            "seconds": "seconds",
        },

        # 黑名单页面
        "blacklist": {
            "title": "Blacklist",
            "add": "Add to Blacklist",
            "remove": "Remove from Blacklist",
            "reason": "Reason",
            "added_at": "Added At",
            "added_by": "Added By",
            "customer_name": "Customer Name",
            "channel": "Channel",
            "confirm_remove": "Are you sure you want to remove this user from blacklist?",
        },

        # 客户页面
        "customers": {
            "title": "Customers",
            "total": "Total Customers",
            "new_today": "New Today",
            "last_message": "Last Message",
            "message_count": "Message Count",
            "view_detail": "View Detail",
            "conversation_history": "Conversation History",
        },

        # 设备页面
        "devices": {
            "title": "Devices",
            "online": "Online",
            "offline": "Offline",
            "connected": "Connected",
            "disconnected": "Disconnected",
            "serial": "Serial Number",
            "model": "Model",
            "sync_now": "Sync Now",
            "last_sync": "Last Sync",
        },

        # 错误消息
        "errors": {
            "network_error": "Network error, please try again",
            "server_error": "Server error, please contact support",
            "not_found": "Resource not found",
            "unauthorized": "Please login first",
            "validation_error": "Validation error",
            "unknown_error": "Unknown error occurred",
        },

        # 成功消息
        "success": {
            "saved": "Saved successfully",
            "deleted": "Deleted successfully",
            "updated": "Updated successfully",
            "sent": "Sent successfully",
        },

        # 数据库列名（表格表头）
        "columns": {
            "id": "ID",
            "name": "Name",
            "created_at": "Created At",
            "updated_at": "Updated At",
            "status": "Status",
            "message": "Message",
            "sender": "Sender",
            "content": "Content",
            "timestamp": "Timestamp",
        },
    },

    # =========================================================================
    # 简体中文
    # =========================================================================
    "zh-CN": {
        "common": {
            "save": "保存",
            "cancel": "取消",
            "confirm": "确认",
            "delete": "删除",
            "edit": "编辑",
            "add": "添加",
            "search": "搜索",
            "loading": "加载中...",
            "error": "错误",
            "success": "成功",
            "warning": "警告",
            "no_data": "暂无数据",
            "actions": "操作",
            "status": "状态",
            "name": "名称",
            "type": "类型",
            "time": "时间",
            "date": "日期",
            "refresh": "刷新",
            "close": "关闭",
            "back": "返回",
            "next": "下一步",
            "previous": "上一步",
            "submit": "提交",
            "reset": "重置",
            "yes": "是",
            "no": "否",
        },

        "nav": {
            "dashboard": "仪表盘",
            "devices": "设备",
            "customers": "客户",
            "kefus": "客服",
            "streamers": "主播",
            "settings": "设置",
            "followup": "跟进系统",
            "blacklist": "黑名单",
            "sidecar": "消息助手",
            "logs": "日志",
            "resources": "资源",
        },

        "dashboard": {
            "title": "仪表盘",
            "total_customers": "客户总数",
            "messages_today": "今日消息",
            "ai_replies": "AI回复数",
            "engagement_rate": "互动率",
            "active_devices": "在线设备",
            "recent_activity": "最近活动",
        },

        "sidecar": {
            "ready_to_send": "准备发送消息，可选择 {seconds} 秒倒计时",
            "sending": "正在发送...",
            "sent": "已发送",
            "send_failed": "发送失败",
            "editing_paused": "编辑中，倒计时已暂停",
            "edit_done": "编辑完成，点击 Resume 继续",
            "no_content": "没有内容可以发送",
            "countdown_started": "倒计时开始，{seconds} 秒后发送",
            "sending_immediate": "倒计时为0，正在立即发送",
            "operator_edited": "操作员编辑了AI回复 (原长度: {original}, 新长度: {new})",
            "operator_approved": "操作员批准了AI回复",
            "sent_and_saved": "已发送并保存",
            "sent_not_saved": "已发送（未保存到数据库）",
            "ai_learning_improved": "AI学习: 已自动改进提示词",
            "ai_learning_suggestion": "AI学习: 新建议可用（在设置中查看）",
            "voice_skipped": "用户发语音，已跳过并加入黑名单",
            "human_requested": "用户要求转人工，已跳过并加入黑名单",
            "send": "发送",
            "start": "开始",
            "pause": "暂停",
            "resume": "继续",
            "stop": "停止",
            "test_message": "测试消息",
        },

        "media": {
            "image": "图片",
            "image_unavailable": "图片不可用",
            "video": "视频",
            "voice": "语音",
            "preview_image": "预览图片",
            "click_to_close": "点击任意位置关闭",
        },

        "settings": {
            "title": "设置",
            "language": "语言",
            "theme": "主题",
            "ai_config": "AI 配置",
            "email_notification": "邮件通知",
            "suggestion_empty": "建议内容不能为空",
            "save_success": "设置保存成功",
            "save_failed": "设置保存失败",
        },

        "streamer": {
            "gender": "性别",
            "age": "年龄",
            "location": "所在地",
            "height": "身高 (cm)",
            "weight": "体重 (kg)",
            "education": "学历",
            "occupation": "职业",
            "interests": "兴趣",
            "social_platforms": "社交平台",
            "notes": "备注",
            "male": "男",
            "female": "女",
            "other": "其他",
            "high_school": "高中",
            "associate": "大专",
            "bachelor": "本科",
            "master": "硕士",
            "phd": "博士",
        },

        "followup": {
            "title": "跟进系统",
            "scanning": "扫描中...",
            "paused": "已暂停",
            "running": "运行中",
            "stopped": "已停止",
            "start_scan": "开始扫描",
            "stop_scan": "停止扫描",
            "scan_interval": "扫描间隔",
            "seconds": "秒",
        },

        "blacklist": {
            "title": "黑名单",
            "add": "加入黑名单",
            "remove": "移出黑名单",
            "reason": "原因",
            "added_at": "添加时间",
            "added_by": "添加者",
            "customer_name": "客户名称",
            "channel": "渠道",
            "confirm_remove": "确定要将此用户移出黑名单吗？",
        },

        "customers": {
            "title": "客户管理",
            "total": "客户总数",
            "new_today": "今日新增",
            "last_message": "最后消息",
            "message_count": "消息数量",
            "view_detail": "查看详情",
            "conversation_history": "对话历史",
        },

        "devices": {
            "title": "设备管理",
            "online": "在线",
            "offline": "离线",
            "connected": "已连接",
            "disconnected": "已断开",
            "serial": "序列号",
            "model": "型号",
            "sync_now": "立即同步",
            "last_sync": "上次同步",
        },

        "errors": {
            "network_error": "网络错误，请重试",
            "server_error": "服务器错误，请联系技术支持",
            "not_found": "资源未找到",
            "unauthorized": "请先登录",
            "validation_error": "验证错误",
            "unknown_error": "发生未知错误",
        },

        "success": {
            "saved": "保存成功",
            "deleted": "删除成功",
            "updated": "更新成功",
            "sent": "发送成功",
        },

        "columns": {
            "id": "ID",
            "name": "名称",
            "created_at": "创建时间",
            "updated_at": "更新时间",
            "status": "状态",
            "message": "消息",
            "sender": "发送者",
            "content": "内容",
            "timestamp": "时间戳",
        },
    },
}


def get_translation(
    lang: str,
    category: str,
    key: str,
    fallback: Optional[str] = None,
    **params
) -> str:
    """
    获取单个翻译

    Args:
        lang: 语言代码 (如 'en', 'zh-CN')
        category: 分类 (如 'common', 'sidecar')
        key: 翻译键名
        fallback: 未找到时的回退文本
        **params: 插值参数

    Returns:
        翻译后的文本

    Example:
        get_translation('zh-CN', 'sidecar', 'countdown_started', seconds=10)
        # 返回: "倒计时开始，10 秒后发送"
    """
    # 尝试获取指定语言的翻译
    translation = TRANSLATIONS.get(lang, {}).get(category, {}).get(key)

    # 回退到默认语言
    if translation is None and lang != DEFAULT_LANGUAGE:
        translation = TRANSLATIONS.get(DEFAULT_LANGUAGE, {}).get(category, {}).get(key)

    # 使用 fallback
    if translation is None:
        translation = fallback or f"{category}.{key}"

    # 处理插值参数
    if params and isinstance(translation, str):
        try:
            translation = translation.format(**params)
        except KeyError:
            pass

    return translation


def get_all_translations(lang: str) -> Dict[str, Dict[str, str]]:
    """获取指定语言的所有翻译"""
    translations = TRANSLATIONS.get(lang, {})
    if not translations and lang != DEFAULT_LANGUAGE:
        translations = TRANSLATIONS.get(DEFAULT_LANGUAGE, {})
    return translations


def get_category_translations(lang: str, category: str) -> Dict[str, str]:
    """获取指定语言和分类的翻译"""
    return get_all_translations(lang).get(category, {})


def get_supported_languages() -> Dict[str, str]:
    """获取支持的语言列表"""
    return SUPPORTED_LANGUAGES
```

### 1.3 语言偏好持久化

**文件**: `wecom-desktop/backend/models/system_settings.py`

```python
"""
系统设置模型

用于持久化保存系统配置，包括语言偏好。
"""

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional

from ..i18n.translations import DEFAULT_LANGUAGE


class SystemSettingsModel:
    """系统设置数据库模型"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent.parent / "wecom_data.db"
        self._db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """确保设置表存在"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """获取设置值"""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            return row[0] if row else default

    def set(self, key: str, value: str) -> bool:
        """设置值"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.now().isoformat()))
            conn.commit()
            return True

    def get_language(self) -> str:
        """获取语言设置"""
        return self.get("language", DEFAULT_LANGUAGE)

    def set_language(self, language: str) -> bool:
        """设置语言"""
        return self.set("language", language)
```

### 1.4 API 端点

**文件**: `wecom-desktop/backend/routers/i18n.py`

```python
"""
国际化 API 端点
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from ..i18n.translations import (
    get_all_translations,
    get_category_translations,
    get_supported_languages,
    DEFAULT_LANGUAGE,
)
from ..models.system_settings import SystemSettingsModel

router = APIRouter(prefix../03-impl-and-arch/key-modules/settings", tags=["i18n"])

settings_model = SystemSettingsModel()


class LanguageRequest(BaseModel):
    language: str


class LanguageResponse(BaseModel):
    current: str
    supported: Dict[str, str]
    default: str


class TranslationsResponse(BaseModel):
    language: str
    translations: Dict[str, Any]


@router.get("/language", response_model=LanguageResponse)
async def get_language():
    """获取当前语言设置"""
    return LanguageResponse(
        current=settings_model.get_language(),
        supported=get_supported_languages(),
        default=DEFAULT_LANGUAGE,
    )


@router.put("/language")
async def set_language(request: LanguageRequest):
    """设置语言"""
    supported = get_supported_languages()
    if request.language not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {request.language}. "
                   f"Supported: {list(supported.keys())}"
        )

    settings_model.set_language(request.language)
    return {
        "success": True,
        "language": request.language,
        "message": f"Language changed to {supported[request.language]}"
    }


@router.get("/translations", response_model=TranslationsResponse)
async def get_translations(lang: Optional[str] = None):
    """获取所有翻译"""
    if lang is None:
        lang = settings_model.get_language()

    return TranslationsResponse(
        language=lang,
        translations=get_all_translations(lang),
    )


@router.get("/translations/{category}")
async def get_translations_by_category(category: str, lang: Optional[str] = None):
    """获取指定分类的翻译"""
    if lang is None:
        lang = settings_model.get_language()

    translations = get_category_translations(lang, category)
    if not translations:
        raise HTTPException(
            status_code=404,
            detail=f"Category '{category}' not found"
        )

    return {
        "language": lang,
        "category": category,
        "translations": translations,
    }
```

---

## 阶段二：前端集成

### 2.1 目录结构

```
wecom-desktop/src/
├── stores/
│   └── i18n.ts              # Pinia i18n store
├── composables/
│   └── useI18n.ts           # i18n 组合式 API
├── components/
│   └── LanguageSwitch.vue   # 语言切换组件
└── plugins/
    └── i18n.ts              # i18n 插件注册
```

### 2.2 Pinia Store

**文件**: `src/stores/i18n.ts`

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

interface Translations {
  [category: string]: {
    [key: string]: string
  }
}

interface SupportedLanguages {
  [code: string]: string
}

export const useI18nStore = defineStore('i18n', () => {
  // State
  const currentLanguage = ref<string>('en')
  const translations = ref<Translations>({})
  const supportedLanguages = ref<SupportedLanguages>({})
  const isLoaded = ref(false)

  // Getters
  const languageName = computed(() => {
    return supportedLanguages.value[currentLanguage.value] || currentLanguage.value
  })

  // Actions
  async function loadLanguage(): Promise<void> {
    try {
      // 获取语言设置
      const langResponse = await fetch('/a../03-impl-and-arch/key-modules/language')
      const langData = await langResponse.json()

      currentLanguage.value = langData.current
      supportedLanguages.value = langData.supported

      // 获取翻译
      const transResponse = await fetch(
        `/a../03-impl-and-arch/key-modules/translations?lang=${langData.current}`
      )
      const transData = await transResponse.json()

      translations.value = transData.translations
      isLoaded.value = true

      // 更新 HTML lang 属性
      document.documentElement.lang = currentLanguage.value
    } catch (error) {
      console.error('Failed to load translations:', error)
    }
  }

  async function setLanguage(lang: string): Promise<boolean> {
    try {
      const response = await fetch('/a../03-impl-and-arch/key-modules/language', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: lang }),
      })

      if (!response.ok) {
        throw new Error('Failed to set language')
      }

      // 重新加载翻译
      await loadLanguage()
      return true
    } catch (error) {
      console.error('Failed to set language:', error)
      return false
    }
  }

  /**
   * 翻译函数
   *
   * @param keyPath - 点分隔的键路径，如 'common.save' 或 'sidecar.sending'
   * @param params - 插值参数对象
   * @param fallback - 回退文本
   */
  function t(keyPath: string, params?: Record<string, any>, fallback?: string): string {
    const [category, ...keyParts] = keyPath.split('.')
    const key = keyParts.join('.')

    let translation = translations.value[category]?.[key]

    if (translation === undefined) {
      console.warn(`Translation not found: ${keyPath}`)
      return fallback || keyPath
    }

    // 处理插值
    if (params) {
      Object.entries(params).forEach(([param, value]) => {
        translation = translation.replace(`{${param}}`, String(value))
      })
    }

    return translation
  }

  return {
    // State
    currentLanguage,
    translations,
    supportedLanguages,
    isLoaded,
    // Getters
    languageName,
    // Actions
    loadLanguage,
    setLanguage,
    t,
  }
})
```

### 2.3 组合式 API

**文件**: `src/composables/useI18n.ts`

```typescript
import { useI18nStore } from '@/stores/i18n'
import { storeToRefs } from 'pinia'

/**
 * i18n 组合式 API
 *
 * @example
 * const { t, currentLanguage, setLanguage } = useI18n()
 *
 * // 在模板中
 * {{ t('common.save') }}
 * {{ t('sidecar.countdown_started', { seconds: 10 }) }}
 */
export function useI18n() {
  const store = useI18nStore()
  const { currentLanguage, supportedLanguages, languageName, isLoaded } = storeToRefs(store)

  return {
    // Refs
    currentLanguage,
    supportedLanguages,
    languageName,
    isLoaded,
    // Functions
    t: store.t,
    loadLanguage: store.loadLanguage,
    setLanguage: store.setLanguage,
  }
}

/**
 * 获取本地化日期格式
 */
export function useLocaleDate() {
  const { currentLanguage } = useI18n()

  function formatDate(isoString: string): string {
    const date = new Date(isoString)
    const locale = currentLanguage.value === 'zh-CN' ? 'zh-CN' : 'en-US'
    return date.toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return { formatDate }
}
```

### 2.4 语言切换组件

**文件**: `src/components/LanguageSwitch.vue`

```vue
<template>
  <div class="language-switch">
    <select v-model="selectedLanguage" @change="handleChange" class="language-select">
      <option v-for="(name, code) in supportedLanguages" :key="code" :value="code">
        {{ name }}
      </option>
    </select>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'

const { currentLanguage, supportedLanguages, setLanguage, loadLanguage, isLoaded } = useI18n()

const selectedLanguage = ref(currentLanguage.value)
const isChanging = ref(false)

// 初始化加载
onMounted(async () => {
  if (!isLoaded.value) {
    await loadLanguage()
    selectedLanguage.value = currentLanguage.value
  }
})

// 监听外部变化
watch(currentLanguage, (newLang) => {
  selectedLanguage.value = newLang
})

async function handleChange() {
  if (isChanging.value) return

  isChanging.value = true
  try {
    const success = await setLanguage(selectedLanguage.value)
    if (!success) {
      // 恢复之前的选择
      selectedLanguage.value = currentLanguage.value
    }
  } finally {
    isChanging.value = false
  }
}
</script>

<style scoped>
.language-switch {
  display: inline-block;
}

.language-select {
  padding: 6px 12px;
  font-size: 14px;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 6px;
  background: var(--bg-color, #fff);
  color: var(--text-color, #333);
  cursor: pointer;
  outline: none;
  transition: border-color 0.2s;
}

.language-select:hover {
  border-color: var(--primary-color, #409eff);
}

.language-select:focus {
  border-color: var(--primary-color, #409eff);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.2);
}
</style>
```

### 2.5 应用入口注册

**文件**: `src/main.ts`

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useI18nStore } from './stores/i18n'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// 初始化 i18n
const i18nStore = useI18nStore()
i18nStore.loadLanguage().then(() => {
  app.mount('#app')
})
```

---

## 阶段三：组件迁移

### 3.1 模板中使用

```vue
<template>
  <!-- 简单翻译 -->
  <h1>{{ t('dashboard.title') }}</h1>
  <button>{{ t('common.save') }}</button>

  <!-- 带参数的翻译 -->
  <p>{{ t('sidecar.countdown_started', { seconds: countdown }) }}</p>

  <!-- 带回退的翻译 -->
  <span>{{ t('some.missing.key', undefined, 'Default Text') }}</span>
</template>

<script setup lang="ts">
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const countdown = ref(10)
</script>
```

### 3.2 脚本中使用

```typescript
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

function showStatus() {
  panel.statusMessage = t('sidecar.sending')
}

function handleError() {
  alert(t('errors.network_error'))
}
```

---

## 任务清单

### 阶段一：后端实现

| 任务 | 文件                                | 内容               |
| ---- | ----------------------------------- | ------------------ |
| 1.1  | `backend/i18n/__init__.py`          | 创建模块入口       |
| 1.2  | `backend/i18n/translations.py`      | 翻译字典和辅助函数 |
| 1.3  | `backend/models/system_settings.py` | 系统设置模型       |
| 1.4  | `backend/routers/i18n.py`           | API 端点           |
| 1.5  | `backend/main.py`                   | 注册路由           |

### 阶段二：前端实现

| 任务 | 文件                                | 内容         |
| ---- | ----------------------------------- | ------------ |
| 2.1  | `src/stores/i18n.ts`                | Pinia store  |
| 2.2  | `src/composables/useI18n.ts`        | 组合式 API   |
| 2.3  | `src/components/LanguageSwitch.vue` | 语言切换组件 |
| 2.4  | `src/main.ts`                       | 初始化集成   |

### 阶段三：组件迁移

| 任务 | 文件                | 工作量             |
| ---- | ------------------- | ------------------ |
| 3.1  | `SidecarView.vue`   | 大（50+ 处）       |
| 3.2  | `SettingsView.vue`  | 中（添加语言切换） |
| 3.3  | `FollowUpView.vue`  | 中                 |
| 3.4  | `BlacklistView.vue` | 小                 |
| 3.5  | `DashboardView.vue` | 中                 |
| 3.6  | 其他组件            | 小                 |

---

## 添加新语言或翻译键

### 添加新语言

1. 在 `SUPPORTED_LANGUAGES` 添加语言代码
2. 在 `TRANSLATIONS` 添加完整的语言字典
3. 复制现有语言作为模板
4. 翻译所有键值

### 添加新翻译键

1. 在所有语言的对应分类中添加键值
2. 保持键名一致
3. 使用 snake_case 命名

```python
# 所有语言都要添加
"en": {
    "new_category": {
        "new_key": "English text",
    }
},
"zh-CN": {
    "new_category": {
        "new_key": "中文文本",
    }
}
```

---

## 成功标准

- ✅ 所有 UI 文本可翻译
- ✅ 语言偏好跨会话持久化
- ✅ 翻译自动加载和应用
- ✅ 缺失翻译优雅回退
- ✅ 易于添加新语言
- ✅ 易于添加新翻译键
- ✅ 无需刷新页面即可切换语言

---

**创建时间**: 2026-01-21
**更新时间**: 2026-01-21
**状态**:

- ✅ 前置工作（页面英文化）- 已完成
- ⏳ 阶段一（后端翻译存储）- 待实施
- ⏳ 阶段二（前端集成）- 待实施
- ⏳ 阶段三（组件迁移）- 待实施
