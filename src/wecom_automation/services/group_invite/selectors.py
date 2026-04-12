"""
Centralized selector keywords for Android group invite flows.

These patterns are designed to work across different WeCom versions (5.0.x)
where resource IDs change with every build. Text and contentDescription
patterns are the most reliable; resource patterns serve as supplementary hints.
"""

CHAT_INFO_MENU_TEXT_PATTERNS: tuple[str, ...] = (
    "聊天信息",
    "chat info",
    "chat information",
    "详情",
    "chat details",
    "聊天详情",
)
CHAT_INFO_MENU_DESC_PATTERNS: tuple[str, ...] = (
    "更多",
    "menu",
    "more",
    "聊天信息",
    "chat info",
    "chat details",
    "详情",
    "options",
    "设置",
)
CHAT_INFO_MENU_RESOURCE_PATTERNS: tuple[str, ...] = (
    "menu",
    "more",
    "chat",
    "info",
    "titlebar",
    "option",
    "detail",
    "right",
    "action",
)

ADD_MEMBER_TEXT_PATTERNS: tuple[str, ...] = (
    "+",
    "添加成员",
    "add members",
    "add member",
    "邀请成员",
    "添加",
    "add",
    "invite",
)
ADD_MEMBER_DESC_PATTERNS: tuple[str, ...] = (
    "添加成员",
    "add members",
    "add member",
    "邀请成员",
    "添加",
    "add",
    "invite",
)
ADD_MEMBER_RESOURCE_PATTERNS: tuple[str, ...] = ("add", "member", "invite", "plus")

SEARCH_TEXT_PATTERNS: tuple[str, ...] = ("搜索", "search", "Search")
SEARCH_DESC_PATTERNS: tuple[str, ...] = ("搜索", "search", "Search")
SEARCH_RESOURCE_PATTERNS: tuple[str, ...] = ("search", "query", "find")

CONFIRM_GROUP_TEXT_PATTERNS: tuple[str, ...] = (
    "确定",
    "确认",
    "创建群聊",
    "创建",
    "完成",
    "done",
    "ok",
    "OK",
    "confirm",
    "create",
    "建群",
)
CONFIRM_GROUP_DESC_PATTERNS: tuple[str, ...] = (
    "确定",
    "确认",
    "创建",
    "完成",
    "done",
    "ok",
    "confirm",
    "create",
)
CONFIRM_GROUP_RESOURCE_PATTERNS: tuple[str, ...] = (
    "confirm",
    "create",
    "done",
    "ok",
    "submit",
    "complete",
    "finish",
)

GROUP_NAME_TEXT_PATTERNS: tuple[str, ...] = ("群聊名称", "群名称", "group name", "群名")
GROUP_NAME_RESOURCE_PATTERNS: tuple[str, ...] = ("group_name", "chat_name", "name", "title")
