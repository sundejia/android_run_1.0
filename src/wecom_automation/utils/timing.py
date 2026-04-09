"""
人类行为模拟延迟

提供随机化的延迟来模拟人类操作行为，帮助避免被检测为自动化操作。
"""

import random
from dataclasses import dataclass


@dataclass
class TimingConfig:
    """
    延迟配置

    Attributes:
        tap_delay: 点击后延迟范围 (min, max)
        scroll_delay: 滚动后延迟范围 (min, max)
        type_delay: 输入后延迟范围 (min, max)
        user_switch_delay: 切换用户延迟范围 (min, max)
        read_delay: 阅读消息延迟范围 (min, max)
        scroll_distance: 滚动距离范围 (min, max)
    """

    tap_delay: tuple[float, float] = (0.5, 2.0)
    scroll_delay: tuple[float, float] = (1.0, 3.0)
    type_delay: tuple[float, float] = (0.3, 1.0)
    user_switch_delay: tuple[float, float] = (3.0, 5.0)
    read_delay: tuple[float, float] = (1.0, 2.0)
    scroll_distance: tuple[int, int] = (500, 700)


class HumanTiming:
    """
    人类行为模拟延迟

    提供各种操作的随机延迟时间，模拟人类操作行为。

    Usage:
        timing = HumanTiming(multiplier=1.0)
        delay = timing.get_tap_delay()
        await asyncio.sleep(delay)

    Attributes:
        multiplier: 延迟倍数，>1 更慢，<1 更快
        config: 延迟配置
    """

    def __init__(self, multiplier: float = 1.0, config: TimingConfig = None):
        """
        初始化

        Args:
            multiplier: 延迟倍数 (>1 更慢, <1 更快)
            config: 自定义延迟配置
        """
        self.multiplier = max(0.1, multiplier)  # 最小0.1，防止太快
        self.config = config or TimingConfig()

    def _get_delay(self, range_tuple: tuple[float, float]) -> float:
        """
        获取随机延迟

        Args:
            range_tuple: (最小值, 最大值)

        Returns:
            随机延迟秒数
        """
        min_val, max_val = range_tuple
        return random.uniform(min_val, max_val) * self.multiplier

    def get_tap_delay(self) -> float:
        """
        获取点击后延迟 (默认 0.5-2.0s)

        Returns:
            延迟秒数
        """
        return self._get_delay(self.config.tap_delay)

    def get_scroll_delay(self) -> float:
        """
        获取滚动后延迟 (默认 1.0-3.0s)

        Returns:
            延迟秒数
        """
        return self._get_delay(self.config.scroll_delay)

    def get_type_delay(self) -> float:
        """
        获取输入后延迟 (默认 0.3-1.0s)

        Returns:
            延迟秒数
        """
        return self._get_delay(self.config.type_delay)

    def get_user_switch_delay(self) -> float:
        """
        获取切换用户延迟 (默认 3.0-5.0s)

        Returns:
            延迟秒数
        """
        return self._get_delay(self.config.user_switch_delay)

    def get_read_delay(self) -> float:
        """
        获取阅读消息延迟 (默认 1.0-2.0s)

        Returns:
            延迟秒数
        """
        return self._get_delay(self.config.read_delay)

    def get_scroll_distance(self) -> int:
        """
        获取随机滚动距离 (默认 500-700 像素)

        Returns:
            滚动距离像素
        """
        min_dist, max_dist = self.config.scroll_distance
        return int(random.randint(min_dist, max_dist) * self.multiplier)

    def get_delay_by_type(self, delay_type: str) -> float:
        """
        根据类型获取延迟

        Args:
            delay_type: 延迟类型 (tap, scroll, type, user_switch, read)

        Returns:
            延迟秒数

        Raises:
            ValueError: 未知的延迟类型
        """
        delay_methods = {
            "tap": self.get_tap_delay,
            "scroll": self.get_scroll_delay,
            "type": self.get_type_delay,
            "user_switch": self.get_user_switch_delay,
            "read": self.get_read_delay,
        }

        if delay_type not in delay_methods:
            raise ValueError(f"Unknown delay type: {delay_type}")

        return delay_methods[delay_type]()
