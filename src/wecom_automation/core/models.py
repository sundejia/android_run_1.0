"""
Data models for WeCom Automation.

This module defines the core data structures used throughout the application.
All models are immutable dataclasses for safety and clarity.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class KefuInfo:
    """
    Information about the 客服 (Customer Service Representative).

    This represents the logged-in WeCom user, typically visible
    when the interface is folded to show the profile panel.

    Attributes:
        name: The 客服 name (e.g., "wgz小号")
        department: Department or organization name (e.g., "302实验室")
        verification_status: Verification status (e.g., "未认证")
    """

    name: str
    department: str | None = None
    verification_status: str | None = None

    def __str__(self) -> str:
        parts = [f"客服: {self.name}"]
        if self.department:
            parts.append(f"Dept: {self.department}")
        if self.verification_status:
            parts.append(f"Status: {self.verification_status}")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class AvatarInfo:
    """
    Information about a user's avatar image.

    Attributes:
        bounds: UI bounds string in format "[x1,y1][x2,y2]"
        resource_id: Android resource ID of the avatar element
        content_description: Accessibility content description
        screenshot_path: Path to saved avatar image file
        x1, y1, x2, y2: Parsed coordinate values
    """

    bounds: str | None = None
    resource_id: str | None = None
    content_description: str | None = None
    screenshot_path: str | None = None

    # Parsed bounds for cropping
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0

    def __str__(self) -> str:
        if self.screenshot_path:
            return f"Avatar(saved: {self.screenshot_path})"
        if self.bounds:
            return f"Avatar({self.bounds})"
        return "Avatar(not found)"

    def parse_bounds(self) -> bool:
        """
        Parse the bounds string into x1, y1, x2, y2 coordinates.

        Returns:
            True if parsing was successful, False otherwise
        """
        if not self.bounds:
            return False
        try:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", self.bounds)
            if match:
                self.x1, self.y1, self.x2, self.y2 = map(int, match.groups())
                return True
        except (ValueError, AttributeError):
            pass
        return False

    @property
    def width(self) -> int:
        """Get avatar width in pixels."""
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        """Get avatar height in pixels."""
        return self.y2 - self.y1

    @property
    def is_valid(self) -> bool:
        """Check if avatar has valid bounds."""
        return self.width > 0 and self.height > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class DeviceInfo:
    """
    Information about a connected Android device.

    Attributes:
        serial: Device serial reported by ADB (USB, emulator, or TCP endpoint)
        state: Connection state (device, unauthorized, offline, etc.)
        product/model/device: Identifiers reported by `adb devices -l`
        transport_id: ADB transport ID (useful for debugging)
        usb: USB bus location string (if available)
        features: Feature flags reported by ADB
        manufacturer/brand/android_version/sdk_version/...: Populated from getprop
        extra_props: Any additional properties collected from getprop
    """

    serial: str
    state: str
    product: str | None = None
    model: str | None = None
    device: str | None = None
    transport_id: int | None = None
    usb: str | None = None
    features: str | None = None
    manufacturer: str | None = None
    brand: str | None = None
    android_version: str | None = None
    sdk_version: str | None = None
    hardware: str | None = None
    abi: str | None = None
    security_patch: str | None = None
    build_id: str | None = None
    screen_resolution: str | None = None
    screen_density: str | None = None
    memory_total: str | None = None
    battery_level: str | None = None
    battery_status: str | None = None
    usb_debugging: bool | None = None
    wifi_mac: str | None = None
    internal_storage: str | None = None
    extra_props: dict[str, str] = field(default_factory=dict)

    @property
    def is_online(self) -> bool:
        """Return True when the device is ready for commands."""
        return self.state == "device"

    @property
    def connection_type(self) -> str:
        """
        Determine how the device is connected.

        Returns one of: "tcp", "emulator", "usb", or "unknown".
        """
        if self.serial.startswith("emulator-"):
            return "emulator"
        if ":" in self.serial:
            host, _, port = self.serial.partition(":")
            if port.isdigit():
                return "tcp"
            # Fall through when serial contains colon but not tcp style
        if self.usb:
            return "usb"
        return "usb" if self.serial else "unknown"

    @property
    def ip_address(self) -> str | None:
        """Extract IP address when connection is TCP-based."""
        if self.connection_type == "tcp":
            return self.serial.split(":", 1)[0]
        return None

    @property
    def tcp_port(self) -> int | None:
        """Extract TCP port for network-connected devices."""
        if self.connection_type == "tcp":
            try:
                return int(self.serial.split(":", 1)[1])
            except (IndexError, ValueError):
                return None
        return None

    @property
    def endpoint(self) -> str:
        """Human-readable endpoint description."""
        if self.connection_type == "tcp":
            return f"{self.ip_address}:{self.tcp_port}"
        if self.usb:
            return f"USB({self.usb})"
        if self.connection_type == "emulator":
            return "Emulator"
        return "USB"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary including computed fields."""
        data = asdict(self)
        data["connection_type"] = self.connection_type
        data["is_online"] = self.is_online
        data["ip_address"] = self.ip_address
        data["tcp_port"] = self.tcp_port
        data["endpoint"] = self.endpoint
        return data


@dataclass
class MessageEntry:
    """
    Represents a single conversation entry in the Messages tab.

    This is the basic unit extracted from the UI tree, containing
    information about a single row in the conversation list.
    """

    title: str
    snippet: str | None = None
    timestamp: str | None = None

    def format(self, index: int) -> str:
        """Format the entry for display."""
        details = [value for value in (self.snippet, self.timestamp) if value]
        if details:
            return f"{index}. {self.title} - {' | '.join(details)}"
        return f"{index}. {self.title}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class UserDetail:
    """
    Detailed information about a user in the Private Chats list.

    This model contains all 5 fields required for the task:
    1. Avatar - User's profile picture information
    2. Name - Contact/user name
    3. Channel - Message source (e.g., @WeChat)
    4. Last message date - When the last message was sent
    5. Message preview - Preview of the latest message

    Attributes:
        name: Contact/user name (required)
        channel: Message source (e.g., @WeChat)
        last_message_date: Date/time of last message
        message_preview: Preview of latest message content
        avatar: Avatar image information
        droidrun_index: DroidRun overlay index for reliable tapping
        _raw_index: Internal index for tracking (not serialized)
    """

    name: str
    channel: str | None = None
    last_message_date: str | None = None
    message_preview: str | None = None
    avatar: AvatarInfo | None = None
    droidrun_index: int | None = None

    # Internal tracking (excluded from serialization)
    _raw_index: int = field(default=-1, repr=False, compare=False)

    def unique_key(self) -> str:
        """
        Generate a unique key for deduplication.

        Combines name and channel to create a unique identifier,
        since the same person might appear multiple times from
        different channels.
        """
        return f"{self.name}|{self.channel or ''}"

    def format(self, index: int) -> str:
        """Format the entry for display as a detailed view."""
        droidrun_str = str(self.droidrun_index) if self.droidrun_index is not None else "None"
        lines = [
            f"\n{'=' * 60}",
            f"User #{index}",
            f"{'=' * 60}",
            f"  1. Avatar:        {self.avatar or 'Not found'}",
            f"  2. Name:          {self.name}",
            f"  3. Channel:       {self.channel or 'None'}",
            f"  4. Date:          {self.last_message_date or 'None'}",
            f"  5. Preview:       {self.message_preview or 'None'}",
            f"  6. DroidRun Index: {droidrun_str}",
        ]
        return "\n".join(lines)

    def format_table_row(self, index: int) -> str:
        """Format as a table row."""
        avatar_status = "✓" if self.avatar and self.avatar.is_valid else "✗"
        return (
            f"| {index:3} | {avatar_status:^6} | {self.name[:20]:<20} | "
            f"{(self.channel or '-')[:10]:<10} | "
            f"{(self.last_message_date or '-')[:12]:<12} | "
            f"{(self.message_preview or '-')[:30]:<30} |"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "channel": self.channel,
            "last_message_date": self.last_message_date,
            "message_preview": self.message_preview,
            "avatar": self.avatar.to_dict() if self.avatar else None,
            "droidrun_index": self.droidrun_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserDetail:
        """Create UserDetail from dictionary."""
        avatar_data = data.get("avatar")
        avatar = AvatarInfo(**avatar_data) if avatar_data else None
        return cls(
            name=data["name"],
            channel=data.get("channel"),
            last_message_date=data.get("last_message_date"),
            message_preview=data.get("message_preview"),
            avatar=avatar,
            droidrun_index=data.get("droidrun_index"),
        )

    def merge_with(self, other: UserDetail) -> UserDetail:
        """
        Merge this entry with another, filling in missing fields.

        This is useful when the same user is partially visible
        in different scroll positions.

        Args:
            other: Another UserDetail with potentially more complete data

        Returns:
            A new UserDetail with combined data
        """
        return UserDetail(
            name=self.name,
            channel=self.channel or other.channel,
            last_message_date=self.last_message_date or other.last_message_date,
            message_preview=self.message_preview or other.message_preview,
            avatar=self.avatar or other.avatar,
            droidrun_index=self.droidrun_index or other.droidrun_index,
            _raw_index=self._raw_index,
        )


@dataclass
class ExtractionResult:
    """
    Result of a user list extraction operation.

    Contains the extracted users along with metadata about
    the extraction process for monitoring and debugging.
    """

    users: list[UserDetail]
    extraction_time: datetime = field(default_factory=datetime.now)
    total_scrolls: int = 0
    duration_seconds: float = 0.0
    success: bool = True
    error_message: str | None = None

    @property
    def total_count(self) -> int:
        """Get total number of extracted users."""
        return len(self.users)

    def format_table(self) -> str:
        """Format all users as a table."""
        if not self.users:
            return "No users found."

        header = f"| {'#':^3} | {'Avatar':^6} | {'Name':<20} | {'Channel':<10} | {'Date':<12} | {'Preview':<30} |"
        separator = "-" * len(header)

        lines = [
            separator,
            header,
            separator,
        ]

        for idx, user in enumerate(self.users, start=1):
            lines.append(user.format_table_row(idx))

        lines.append(separator)
        lines.append(f"Total: {self.total_count} users")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "extraction_time": self.extraction_time.isoformat(),
            "total_count": self.total_count,
            "total_scrolls": self.total_scrolls,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "error_message": self.error_message,
            "users": [user.to_dict() for user in self.users],
        }


@dataclass
class ImageInfo:
    """
    Information about an image in a conversation message.

    Attributes:
        bounds: UI bounds string in format "[x1,y1][x2,y2]"
        resource_id: Android resource ID of the image element
        content_description: Accessibility content description
        local_path: Path to downloaded image file
        x1, y1, x2, y2: Parsed coordinate values
    """

    bounds: str | None = None
    resource_id: str | None = None
    content_description: str | None = None
    local_path: str | None = None

    # Parsed bounds for cropping
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0

    def __str__(self) -> str:
        if self.local_path:
            return f"Image(saved: {self.local_path})"
        if self.bounds:
            return f"Image({self.bounds})"
        return "Image(not found)"

    def parse_bounds(self) -> bool:
        """
        Parse the bounds string into x1, y1, x2, y2 coordinates.

        Returns:
            True if parsing was successful, False otherwise
        """
        if not self.bounds:
            return False
        try:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", self.bounds)
            if match:
                self.x1, self.y1, self.x2, self.y2 = map(int, match.groups())
                return True
        except (ValueError, AttributeError):
            pass
        return False

    @property
    def width(self) -> int:
        """Get image width in pixels."""
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        """Get image height in pixels."""
        return self.y2 - self.y1

    @property
    def is_valid(self) -> bool:
        """Check if image has valid bounds."""
        return self.width > 0 and self.height > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class ConversationMessage:
    """
    Represents a single message in a conversation.

    Attributes:
        content: Text content of the message (None for image-only messages)
        timestamp: Time the message was sent (e.g., "AM 1:41", "11/24")
        is_self: True if this message was sent by the current user
        message_type: Type of message ("text", "image", "voice", "video", "file", "system", etc.)
        image: Image information for image messages
        voice_duration: Duration string for voice messages (e.g., "2\"")
        video_duration: Duration string for video messages (e.g., "00:45", "1:23")
        sender_name: Name of the sender (for group chats)
        sender_avatar: Avatar info for the sender
        raw_bounds: Raw bounds of the message container for deduplication
    """

    content: str | None = None
    timestamp: str | None = None
    is_self: bool = False
    message_type: str = "text"
    image: ImageInfo | None = None
    voice_duration: str | None = None
    voice_local_path: str | None = None  # Path to downloaded voice file (WAV)
    video_duration: str | None = None
    video_local_path: str | None = None  # Path to downloaded video file
    sender_name: str | None = None
    sender_avatar: AvatarInfo | None = None
    raw_bounds: str | None = None

    # Internal tracking (excluded from serialization)
    _raw_index: int = field(default=-1, repr=False, compare=False)
    # Sequence number for identical messages at same timestamp (0-indexed)
    _sequence: int = field(default=0, repr=False, compare=False)

    def unique_key(self) -> str:
        """
        Generate a stable key for deduplication across scrolls.

        The key combines: direction | message_type | content[:80] | sequence

        NOTE: We intentionally DO NOT include timestamp in the key because:
        - Timestamp is propagated from separators during extraction
        - The same message can get different timestamps across scroll passes
          depending on which separator is visible
        - Using sequence number allows distinguishing identical messages

        This allows:
        - Same message to be deduplicated even if extracted with different timestamps
        - Multiple identical messages to be distinct (via sequence)
        """
        # Direction part
        dir_part = "self" if self.is_self else "other"

        # Type part
        type_part = self.message_type

        # Content part (truncated to keep keys manageable)
        if self.message_type == "voice":
            # For voice, include duration and transcription
            content_part = f"{self.voice_duration or ''}/{self.content or ''}"[:80]
        elif self.message_type == "video":
            # For video, include duration and dimensions if available
            if self.image and self.image.bounds:
                match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", self.image.bounds)
                if match:
                    x1, y1, x2, y2 = map(int, match.groups())
                    content_part = f"video_{self.video_duration or ''}_{x2 - x1}x{y2 - y1}"
                else:
                    content_part = f"video_{self.video_duration or ''}"
            else:
                content_part = f"video_{self.video_duration or ''}"
        elif self.message_type == "image" and self.image and self.image.bounds:
            # For images, use dimensions as pseudo-content
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", self.image.bounds)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                content_part = f"{x2 - x1}x{y2 - y1}"
            else:
                content_part = "img"
        else:
            content_part = (self.content or "")[:80]

        # Include sequence to distinguish identical messages
        # Sequence is assigned during extraction based on order of appearance
        seq_part = str(self._sequence) if self._sequence > 0 else ""

        return f"{dir_part}|{type_part}|{content_part}|{seq_part}"

    def format(self, index: int) -> str:
        """Format the message for display."""
        sender = "Me" if self.is_self else (self.sender_name or "Other")
        time_str = f"[{self.timestamp}]" if self.timestamp else ""

        if self.message_type == "image":
            content = f"[Image: {self.image}]"
        elif self.message_type == "video":
            content = f"[Video: {self.video_duration or '?'}]"
        elif self.message_type == "voice":
            # Include transcription if available
            if self.content:
                content = f'[Voice: {self.voice_duration or "?"}] "{self.content}"'
            else:
                content = f"[Voice: {self.voice_duration or '?'}]"
        elif self.message_type == "system":
            return f"{index}. {time_str} ** {self.content} **"
        else:
            content = self.content or "[Empty]"

        return f"{index}. {time_str} {sender}: {content}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "content": self.content,
            "timestamp": self.timestamp,
            "is_self": self.is_self,
            "message_type": self.message_type,
            "sender_name": self.sender_name,
        }
        if self.image:
            result["image"] = self.image.to_dict()
        if self.voice_duration:
            result["voice_duration"] = self.voice_duration
        if self.voice_local_path:
            result["voice_local_path"] = self.voice_local_path
        if self.video_duration:
            result["video_duration"] = self.video_duration
        if self.sender_avatar:
            result["sender_avatar"] = self.sender_avatar.to_dict()
        return result


@dataclass
class ConversationExtractionResult:
    """
    Result of a conversation message extraction operation.

    Contains all messages from a conversation along with metadata.
    """

    messages: list[ConversationMessage]
    contact_name: str | None = None
    contact_channel: str | None = None
    extraction_time: datetime = field(default_factory=datetime.now)
    total_scrolls: int = 0
    duration_seconds: float = 0.0
    success: bool = True
    error_message: str | None = None
    images_downloaded: int = 0
    videos_downloaded: int = 0
    voices_downloaded: int = 0

    @property
    def total_count(self) -> int:
        """Get total number of extracted messages."""
        return len(self.messages)

    @property
    def text_count(self) -> int:
        """Get number of text messages."""
        return sum(1 for m in self.messages if m.message_type == "text")

    @property
    def image_count(self) -> int:
        """Get number of image messages."""
        return sum(1 for m in self.messages if m.message_type == "image")

    @property
    def video_count(self) -> int:
        """Get number of video messages."""
        return sum(1 for m in self.messages if m.message_type == "video")

    @property
    def voice_count(self) -> int:
        """Get number of voice messages."""
        return sum(1 for m in self.messages if m.message_type == "voice")

    @property
    def self_count(self) -> int:
        """Get number of messages sent by self."""
        return sum(1 for m in self.messages if m.is_self)

    @property
    def other_count(self) -> int:
        """Get number of messages from others."""
        return sum(1 for m in self.messages if not m.is_self and m.message_type != "system")

    def format_summary(self) -> str:
        """Format a summary of the extraction."""
        lines = [
            f"{'=' * 60}",
            f"Conversation with: {self.contact_name or 'Unknown'}",
            f"Channel: {self.contact_channel or 'N/A'}",
            f"{'=' * 60}",
            f"Total messages: {self.total_count}",
            f"  - Text messages: {self.text_count}",
            f"  - Image messages: {self.image_count}",
            f"  - Video messages: {self.video_count}",
            f"  - Voice messages: {self.voice_count}",
            f"  - From self: {self.self_count}",
            f"  - From other: {self.other_count}",
            f"Images downloaded: {self.images_downloaded}",
            f"Videos downloaded: {self.videos_downloaded}",
            f"Voices downloaded: {self.voices_downloaded}",
            f"Total scrolls: {self.total_scrolls}",
            f"Duration: {self.duration_seconds:.2f}s",
            f"{'=' * 60}",
        ]
        return "\n".join(lines)

    def format_messages(self) -> str:
        """Format all messages for display."""
        if not self.messages:
            return "No messages found."

        lines = [self.format_summary(), ""]
        for idx, msg in enumerate(self.messages, start=1):
            lines.append(msg.format(idx))

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "contact_name": self.contact_name,
            "contact_channel": self.contact_channel,
            "extraction_time": self.extraction_time.isoformat(),
            "total_count": self.total_count,
            "text_count": self.text_count,
            "image_count": self.image_count,
            "self_count": self.self_count,
            "other_count": self.other_count,
            "total_scrolls": self.total_scrolls,
            "duration_seconds": self.duration_seconds,
            "images_downloaded": self.images_downloaded,
            "success": self.success,
            "error_message": self.error_message,
            "messages": [msg.to_dict() for msg in self.messages],
        }
