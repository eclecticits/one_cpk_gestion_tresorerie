from __future__ import annotations

import logging
import time

from onec_attendance_agent.config import AgentConfig
from onec_attendance_agent.providers import build_provider
from onec_attendance_agent.storage.sqlite_queue import SQLitePunchQueue
from onec_attendance_agent.sync.client import OnecSmartClient, is_network_error

logger = logging.getLogger("onec_attendance_agent")


class AttendanceSyncWorker:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.queue = SQLitePunchQueue(config.sqlite_path)
        self.client = OnecSmartClient(config)
        self.providers = [build_provider(device) for device in config.devices]

    def collect_once(self) -> None:
        for provider in self.providers:
            try:
                for event in provider.fetch_events():
                    self.queue.enqueue(event)
                logger.info("device_collect device_id=%s pending=%s", provider.device_id, self.queue.pending_count())
            except Exception as exc:
                logger.warning("device_collect_failed device_id=%s reason=%s", provider.device_id, exc)

    def sync_once(self) -> None:
        rows = self.queue.pending(100)
        if not rows:
            return
        try:
            self.client.send_events(rows)
        except Exception as exc:
            for row in rows:
                self.queue.mark_error(row["id"], str(exc))
            if is_network_error(exc):
                logger.warning("sync_network_error pending=%s reason=%s", len(rows), exc)
                return
            raise
        self.queue.mark_synced([row["id"] for row in rows])
        logger.info("sync_ok count=%s", len(rows))

    def heartbeat_once(self) -> None:
        devices = []
        for provider in self.providers:
            try:
                info = provider.get_device_info()
                devices.append({"device_id": provider.device_id, "pending_count": self.queue.pending_count(), **info})
            except Exception as exc:
                devices.append({"device_id": provider.device_id, "status": "SYNC_ERROR", "last_error": str(exc)})
        self.client.heartbeat(devices, pending_count=self.queue.pending_count())

    def commands_once(self) -> None:
        commands = self.client.claim_commands()
        providers = {provider.device_id: provider for provider in self.providers}
        for command in commands:
            try:
                command_type = command.get("command_type")
                if command_type not in {"TEST_DEVICE", "PROBE_DEVICE"}:
                    self.client.send_command_result(command["id"], "FAILED", error="Commande non supportee")
                    continue
                payload = command.get("payload_json") or {}
                device_id = payload.get("device_id")
                provider = providers.get(device_id)
                if provider is None:
                    self.client.send_command_result(command["id"], "FAILED", error=f"Pointeuse inconnue: {device_id}")
                    continue
                # Les commandes appareil ne lisent que l'hote/port configure dans l'agent local.
                probe = provider.test_connection() if command_type == "TEST_DEVICE" else provider.probe_capabilities()
                status = "SUCCESS" if probe.get("tcp_reachable") else "FAILED"
                self.client.send_command_result(command["id"], status, result=probe, error=probe.get("error"))
            except Exception as exc:
                logger.warning("command_failed command_id=%s reason=%s", command.get("id"), exc)
                try:
                    self.client.send_command_result(command["id"], "FAILED", error=str(exc))
                except Exception:
                    logger.warning("command_result_failed command_id=%s", command.get("id"))

    def run_forever(self) -> None:
        while True:
            self.collect_once()
            self.sync_once()
            self.commands_once()
            try:
                self.heartbeat_once()
            except Exception as exc:
                logger.warning("heartbeat_failed reason=%s", exc)
            time.sleep(self.config.sync_interval_seconds)
