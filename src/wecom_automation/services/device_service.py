"""
Device discovery utilities built on top of ADB.

This module enumerates connected Android devices by invoking `adb devices -l`
and optionally enriches each entry with additional metadata from
`adb -s <serial> shell getprop`.
"""

from __future__ import annotations

import asyncio
import os
import platform
import re
import shutil

from wecom_automation.core.config import Config
from wecom_automation.core.exceptions import DeviceConnectionError
from wecom_automation.core.logging import get_logger
from wecom_automation.core.models import DeviceInfo


class DeviceDiscoveryService:
    """Enumerate Android devices using the local ADB installation."""

    PROP_MAPPINGS: dict[str, str] = {
        "ro.product.manufacturer": "manufacturer",
        "ro.product.brand": "brand",
        "ro.product.model": "model",
        "ro.product.device": "device",
        "ro.product.name": "product",
        "ro.build.version.release": "android_version",
        "ro.build.version.sdk": "sdk_version",
        "ro.build.version.security_patch": "security_patch",
        "ro.build.id": "build_id",
        "ro.hardware": "hardware",
        "ro.product.cpu.abi": "abi",
    }

    EXTRA_PROP_KEYS = [
        "ro.product.cpu.abi2",
        "ro.board.platform",
        "ro.boot.hardware",
        "ro.bootloader",
        "ro.build.characteristics",
        "ro.serialno",
        "ro.boot.serialno",
    ]

    def __init__(
        self,
        config: Config | None = None,
        *,
        adb_path: str | None = None,
    ):
        self.config = config or Config()
        # Determine adb_path: use provided, then env var, then default
        if adb_path:
            self.adb_path = adb_path
        else:
            env_adb = os.environ.get("ADB_PATH")
            if env_adb:
                self.adb_path = env_adb
            else:
                # Default: use "adb" on Unix/Mac, "adb.exe" on Windows
                self.adb_path = shutil.which("adb")
        self.logger = get_logger("wecom_automation.devices")

    async def list_devices(
        self,
        include_properties: bool = True,
        include_runtime_stats: bool = False,
        verbose: bool = False,
    ) -> list[DeviceInfo]:
        """
        Enumerate connected devices.

        Args:
            include_properties: When True, fetch extended metadata via getprop.
        """
        raw = await self._run_adb(["devices", "-l"])
        devices = self._parse_devices_output(raw)
        self.logger.info("Detected {} device(s)", len(devices))

        if include_properties and devices:
            await self._populate_device_properties(devices)
        if include_runtime_stats and devices:
            await self._populate_runtime_stats(devices, verbose=verbose)

        return devices

    async def _populate_device_properties(self, devices: list[DeviceInfo]) -> None:
        tasks = [self._fetch_and_merge_props(device) for device in devices if device.is_online]
        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for device, result in zip((d for d in devices if d.is_online), results, strict=False):
            if isinstance(result, Exception):
                self.logger.warning("Failed to fetch properties for {}: {}", device.serial, result)

    async def _fetch_and_merge_props(self, device: DeviceInfo) -> None:
        raw_props = await self._run_adb(["-s", device.serial, "shell", "getprop"])
        props = self._parse_getprop_output(raw_props)
        self._apply_properties(device, props)

    async def _populate_runtime_stats(
        self,
        devices: list[DeviceInfo],
        *,
        verbose: bool = False,
    ) -> None:
        for device in devices:
            if not device.is_online:
                continue
            if verbose:
                self.logger.info("Collecting runtime stats for {}", device.serial)
            try:
                screen_resolution, screen_density = await self._get_screen_info(device.serial)
                device.screen_resolution = screen_resolution or device.screen_resolution
                device.screen_density = screen_density or device.screen_density
                device.memory_total = await self._get_memory_info(device.serial) or device.memory_total
                battery_level, battery_status = await self._get_battery_info(device.serial)
                device.battery_level = battery_level or device.battery_level
                device.battery_status = battery_status or device.battery_status
                device.usb_debugging = await self._get_usb_debugging(device.serial)
                device.wifi_mac = await self._get_wifi_mac(device.serial) or device.wifi_mac
                device.internal_storage = await self._get_storage_info(device.serial) or device.internal_storage
            except DeviceConnectionError as exc:
                self.logger.debug("Skipping runtime stats for {}: {}", device.serial, exc)

    def _apply_properties(self, device: DeviceInfo, props: dict[str, str]) -> None:
        for prop_name, attr_name in self.PROP_MAPPINGS.items():
            value = props.get(prop_name)
            if not value:
                continue

            current = getattr(device, attr_name, None)
            if current and attr_name in {"model", "device", "product"}:
                # Preserve values already supplied by `adb devices -l`
                continue
            setattr(device, attr_name, value)

        extra = {key: props[key] for key in self.EXTRA_PROP_KEYS if props.get(key)}
        if extra:
            device.extra_props.update(extra)

    async def _run_adb(self, args: list[str]) -> str:
        cmd = [self.adb_path, *args]
        self.logger.debug("Running command: {}", " ".join(cmd))

        # On Windows, asyncio.create_subprocess_exec may not work with uvicorn's event loop
        # Use synchronous subprocess in a thread pool for cross-platform compatibility
        if platform.system() == "Windows":
            return await self._run_adb_sync(cmd)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            # Provide helpful error message for Windows
            error_msg = f"ADB executable not found: {self.adb_path}"
            if platform.system() == "Windows":
                error_msg += (
                    "\n\nPlease ensure ADB is installed and available in your PATH, "
                    "or set the ADB_PATH environment variable to the full path of adb.exe"
                )
            raise DeviceConnectionError(
                "ADB executable not found",
                context={"adb_path": self.adb_path},
                original_error=exc,
            ) from exc

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            # Try UTF-8 first, fallback to system default encoding with error handling
            try:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
            except (UnicodeDecodeError, AttributeError):
                try:
                    stderr_text = stderr.decode("cp1252", errors="replace").strip()
                except (UnicodeDecodeError, AttributeError):
                    stderr_text = str(stderr)[:200]  # Fallback to string representation
            raise DeviceConnectionError(
                "ADB command failed",
                context={
                    "command": " ".join(cmd),
                    "stderr": stderr_text,
                },
            )

        # Try UTF-8 first, fallback to system default encoding with error handling
        try:
            return stdout.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            try:
                return stdout.decode("cp1252", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                # Last resort: use system default encoding
                return stdout.decode(errors="replace")

    async def _run_adb_sync(self, cmd: list[str]) -> str:
        """
        Run ADB command using synchronous subprocess in a thread pool.
        This is used on Windows where asyncio subprocess support may be limited.
        """
        import subprocess

        def _run_sync():
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
                )
                return result.returncode, result.stdout, result.stderr
            except FileNotFoundError as exc:
                raise DeviceConnectionError(
                    "ADB executable not found",
                    context={"adb_path": cmd[0]},
                    original_error=exc,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise DeviceConnectionError(
                    "ADB command timed out",
                    context={"command": " ".join(cmd)},
                    original_error=exc,
                ) from exc

        returncode, stdout, stderr = await asyncio.to_thread(_run_sync)

        if returncode != 0:
            try:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
            except (UnicodeDecodeError, AttributeError):
                try:
                    stderr_text = stderr.decode("cp1252", errors="replace").strip()
                except (UnicodeDecodeError, AttributeError):
                    stderr_text = str(stderr)[:200]
            raise DeviceConnectionError(
                "ADB command failed",
                context={
                    "command": " ".join(cmd),
                    "stderr": stderr_text,
                },
            )

        try:
            return stdout.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            try:
                return stdout.decode("cp1252", errors="replace")
            except (UnicodeDecodeError, AttributeError):
                return stdout.decode(errors="replace")

    async def _run_shell(self, serial: str, *command: str) -> str:
        if not serial:
            raise DeviceConnectionError("Serial is required for shell commands")
        return await self._run_adb(["-s", serial, "shell", *command])

    @staticmethod
    def _parse_devices_output(output: str) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("List of devices"):
                continue
            if stripped.startswith("* "):
                # Ignore daemon status messages
                continue
            info = DeviceDiscoveryService._parse_device_line(stripped)
            if info:
                devices.append(info)
        return devices

    @staticmethod
    def _parse_device_line(line: str) -> DeviceInfo | None:
        parts = line.split()
        if len(parts) < 2:
            return None

        serial, state = parts[0], parts[1]
        extras: dict[str, str] = {}
        for token in parts[2:]:
            if ":" not in token:
                continue
            key, value = token.split(":", 1)
            extras[key] = value

        transport_val = extras.get("transport_id")
        try:
            transport_id = int(transport_val) if transport_val else None
        except ValueError:
            transport_id = None

        known_keys = {"product", "model", "device", "transport_id", "usb", "features"}
        extra_props = {key: value for key, value in extras.items() if key not in known_keys}

        return DeviceInfo(
            serial=serial,
            state=state,
            product=extras.get("product"),
            model=extras.get("model"),
            device=extras.get("device"),
            transport_id=transport_id,
            usb=extras.get("usb"),
            features=extras.get("features"),
            extra_props=extra_props,
        )

    @staticmethod
    def _parse_getprop_output(output: str) -> dict[str, str]:
        props: dict[str, str] = {}
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped.startswith("[") or "]: [" not in stripped:
                continue
            try:
                key_part, value_part = stripped.split("]:", 1)
            except ValueError:
                continue
            key = key_part.strip("[]")
            value = value_part.strip()
            if value.startswith("[") and value.endswith("]"):
                value = value[1:-1]
            props[key] = value
        return props

    async def _get_screen_info(self, serial: str) -> tuple[str | None, str | None]:
        resolution = None
        density = None
        try:
            output = await self._run_shell(serial, "wm", "size")
            match = re.search(r"Physical size:\s*([0-9]+x[0-9]+)", output)
            if match:
                resolution = match.group(1)
        except DeviceConnectionError:
            pass

        try:
            output = await self._run_shell(serial, "wm", "density")
            match = re.search(r"Physical density:\s*([0-9]+)", output)
            if match:
                density = match.group(1)
        except DeviceConnectionError:
            pass

        return resolution, density

    async def _get_memory_info(self, serial: str) -> str | None:
        try:
            output = await self._run_shell(serial, "cat", "/proc/meminfo")
        except DeviceConnectionError:
            return None
        match = re.search(r"MemTotal:\s+(\d+)\s+kB", output)
        if not match:
            return None
        mem_kb = int(match.group(1))
        mem_gb = mem_kb / (1024 * 1024)
        return f"{mem_gb:.2f} GB"

    async def _get_battery_info(self, serial: str) -> tuple[str | None, str | None]:
        try:
            output = await self._run_shell(serial, "dumpsys", "battery")
        except DeviceConnectionError:
            return None, None
        level_match = re.search(r"level:\s*(\d+)", output)
        status_match = re.search(r"status:\s*(\d+)", output)
        level = f"{level_match.group(1)}%" if level_match else None
        status_map = {
            "1": "Unknown",
            "2": "Charging",
            "3": "Discharging",
            "4": "Not charging",
            "5": "Full",
        }
        status = status_map.get(status_match.group(1), None) if status_match else None
        return level, status

    async def _get_usb_debugging(self, serial: str) -> bool | None:
        try:
            value = await self._run_shell(serial, "getprop", "ro.debuggable")
        except DeviceConnectionError:
            return None
        cleaned = value.strip()
        if cleaned in {"0", "1"}:
            return cleaned == "1"
        return None

    async def _get_wifi_mac(self, serial: str) -> str | None:
        try:
            output = await self._run_shell(serial, "ip", "link", "show", "wlan0")
            match = re.search(r"link/ether\s+([0-9a-fA-F:]{17})", output)
            if match:
                return match.group(1).lower()
        except DeviceConnectionError:
            pass
        try:
            fallback = await self._run_shell(serial, "getprop", "persist.sys.wifi.macaddress")
            fallback = fallback.strip()
            if fallback:
                return fallback
        except DeviceConnectionError:
            pass
        return None

    async def _get_storage_info(self, serial: str) -> str | None:
        try:
            output = await self._run_shell(serial, "df", "-h", "/data")
        except DeviceConnectionError:
            return None
        lines = [line for line in output.splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        parts = lines[-1].split()
        if len(parts) < 4:
            return None
        # Filesystem Size Used Avail Use% Mounted_on
        return f"{parts[3]} available of {parts[1]}"

    async def get_device(
        self,
        serial: str,
        *,
        include_properties: bool = True,
        include_runtime_stats: bool = False,
    ) -> DeviceInfo | None:
        devices = await self.list_devices(
            include_properties=include_properties,
            include_runtime_stats=include_runtime_stats,
        )
        return next((d for d in devices if d.serial == serial), None)
