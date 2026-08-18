from __future__ import annotations

from onec_attendance_agent.config import DeviceConfig
from onec_attendance_agent.providers.hikvision import HikvisionProvider
from onec_attendance_agent.providers.mock import MockAttendanceProvider


def build_provider(config: DeviceConfig):
    if config.provider == "mock":
        return MockAttendanceProvider(config)
    if config.provider == "hikvision":
        return HikvisionProvider(config)
    raise ValueError(f"Unsupported provider: {config.provider}")
