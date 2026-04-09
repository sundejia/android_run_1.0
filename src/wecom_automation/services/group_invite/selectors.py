"""
Centralized selector keywords for Android group invite flows.
"""

CHAT_INFO_MENU_TEXT_PATTERNS: tuple[str, ...] = ("聊天信息", "chat info", "chat information", "详情")
CHAT_INFO_MENU_DESC_PATTERNS: tuple[str, ...] = ("更多", "menu", "more", "聊天信息", "chat info")
CHAT_INFO_MENU_RESOURCE_PATTERNS: tuple[str, ...] = ("menu", "more", "chat", "info", "titlebar")

ADD_MEMBER_TEXT_PATTERNS: tuple[str, ...] = ("+", "添加成员", "add members", "add member", "邀请成员")
ADD_MEMBER_DESC_PATTERNS: tuple[str, ...] = ("添加成员", "add members", "add member", "邀请成员")
ADD_MEMBER_RESOURCE_PATTERNS: tuple[str, ...] = ("add", "member", "invite")

SEARCH_TEXT_PATTERNS: tuple[str, ...] = ("搜索", "search")
SEARCH_DESC_PATTERNS: tuple[str, ...] = ("搜索", "search")
SEARCH_RESOURCE_PATTERNS: tuple[str, ...] = ("search",)

CONFIRM_GROUP_TEXT_PATTERNS: tuple[str, ...] = ("确定", "确认", "创建群聊", "创建", "完成", "done", "ok")
CONFIRM_GROUP_DESC_PATTERNS: tuple[str, ...] = ("确定", "确认", "创建", "完成", "done", "ok")
CONFIRM_GROUP_RESOURCE_PATTERNS: tuple[str, ...] = ("confirm", "create", "done", "ok")

GROUP_NAME_TEXT_PATTERNS: tuple[str, ...] = ("群聊名称", "群名称", "group name")
GROUP_NAME_RESOURCE_PATTERNS: tuple[str, ...] = ("group_name", "chat_name", "name")
