from __future__ import annotations

import argparse
import json
import logging
import socket
import urllib.request
from pathlib import Path

from onec_attendance_agent.config import load_config
from onec_attendance_agent.credentials import prompt_and_store_credentials
from onec_attendance_agent.providers import build_provider
from onec_attendance_agent.sync.worker import AttendanceSyncWorker


def _line(label: str, state: str, value: object | None = None) -> str:
    suffix = "" if value is None else f"       {value}"
    return f"{label:<12} {state:<8}{suffix}"


def _print_device_result(device, result: dict) -> None:
    print("ONEC Attendance Agent 0.2.0")
    print()
    print(f"Device : {device.id}")
    print(f"Model configured : {device.configured_model or 'DS-K1A8603MF-B'}")
    print(f"Host : {device.host}")
    print(f"Port : {device.port}")
    print()
    print(_line("TCP", "OK" if result.get("tcp_reachable") else "FAILED", f"{result.get('tcp_latency_ms')} ms" if result.get("tcp_latency_ms") is not None else None))
    http_status = result.get("http_status") if result.get("http_reachable") else result.get("https_status")
    print(_line("HTTP", "OK" if result.get("http_reachable") or result.get("https_reachable") else "UNKNOWN", http_status))
    if result.get("authentication_ok"):
        auth_state = "OK"
    elif result.get("authentication_required"):
        auth_state = "REQUIRED"
    else:
        auth_state = "UNKNOWN"
    print(_line("Auth", auth_state, result.get("authentication_method")))
    if result.get("device_info_ok") is True:
        print(_line("DeviceInfo", "OK"))
    isapi = result.get("isapi_supported")
    print(_line("ISAPI", "AVAILABLE" if isapi is True else "UNAVAILABLE" if isapi is False else "UNKNOWN"))
    if result.get("detected_model"):
        print(_line("Model", str(result["detected_model"])))
    if result.get("firmware_version"):
        print(_line("Firmware", str(result["firmware_version"])))
    print()
    print("Result:")
    print(result.get("status") or "UNKNOWN")


def main() -> None:
    parser = argparse.ArgumentParser(prog="onec-attendance-agent")
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="command", required=True)
    enroll = sub.add_parser("enroll")
    enroll.add_argument("--enrollment-url", required=True)
    enroll.add_argument("--enrollment-token", required=True)
    enroll.add_argument("--out", required=True)
    sub.add_parser("status")
    sub.add_parser("sync")
    sub.add_parser("run")
    test = sub.add_parser("test-device")
    test.add_argument("device_id")
    probe = sub.add_parser("probe-device")
    probe.add_argument("device_id")
    store_credentials = sub.add_parser("store-credentials")
    store_credentials.add_argument("device_id")
    store_credentials.add_argument("--username")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "enroll":
        payload = json.dumps(
            {
                "enrollment_token": args.enrollment_token,
                "hostname": socket.gethostname(),
                "agent_version": "0.2.0",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            args.enrollment_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            enrolled = json.loads(response.read().decode("utf-8"))
        config = {
            "agent": {
                "id": enrolled["agent_id"],
                "name": enrolled["agent_id"],
                "site": enrolled.get("site") or "",
                "sync_interval_seconds": 10,
                "timezone": "Africa/Kinshasa",
            },
            "onec_smart": {
                "api_base_url": enrolled["api_base_url"],
                "token": enrolled["agent_token"],
                "timeout_seconds": 15,
            },
            "storage": {
                "sqlite_path": "./onec_attendance_agent.sqlite3",
            },
            "devices": enrolled["devices"],
        }
        Path(args.out).write_text(json.dumps(config, indent=2), encoding="utf-8")
        print({"agent_id": enrolled["agent_id"], "config": args.out, "devices": [item["id"] for item in enrolled["devices"]]})
        return

    if args.command == "store-credentials":
        path = prompt_and_store_credentials(args.device_id, args.username)
        print({"device_id": args.device_id, "credential_ref": f"local:{args.device_id}", "path": str(path)})
        return

    if not args.config:
        raise SystemExit("--config is required")
    config = load_config(args.config)
    worker = AttendanceSyncWorker(config)

    if args.command == "status":
        print({"agent_id": config.agent_id, "pending": worker.queue.pending_count(), "devices": [d.id for d in config.devices]})
    elif args.command in {"test-device", "probe-device"}:
        device = next((d for d in config.devices if d.id == args.device_id), None)
        if device is None:
            raise SystemExit(f"Unknown device: {args.device_id}")
        provider = build_provider(device)
        result = provider.test_connection() if args.command == "test-device" else provider.probe_capabilities()
        _print_device_result(device, result)
    elif args.command == "sync":
        worker.collect_once()
        worker.sync_once()
        worker.commands_once()
        worker.heartbeat_once()
    elif args.command == "run":
        worker.run_forever()


if __name__ == "__main__":
    main()
