from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_pyinstaller(name: str) -> Path:
    if shutil.which("pyinstaller") is None:
        raise SystemExit("PyInstaller is not installed; install it before building the agent binary.")
    subprocess.run(
        [
            "pyinstaller",
            "--clean",
            "--onefile",
            "--name",
            name,
            str(ROOT / "onec_attendance_agent" / "cli.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    exe = ROOT / "dist" / (f"{name}.exe" if platform.system().lower() == "windows" else name)
    if not exe.is_file():
        raise SystemExit(f"Expected binary was not produced: {exe}")
    return exe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", choices=["windows", "linux"], required=True)
    parser.add_argument("--architecture", default="x64", choices=["x64"])
    args = parser.parse_args()

    expected_host = "windows" if platform.system().lower() == "windows" else "linux"
    if args.platform != expected_host:
        raise SystemExit(f"Build {args.platform} on a {args.platform} host or CI runner; current host is {expected_host}.")

    binary_name = "onec-attendance-agent"
    exe = run_pyinstaller(binary_name)
    out_dir = DIST / f"{args.version}-{args.platform}-{args.architecture}"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (f"{binary_name}.exe" if args.platform == "windows" else binary_name)
    shutil.copy2(exe, target)

    if args.platform == "windows":
        for item in [ROOT / "packaging" / "windows" / "WinSW-x64.exe", ROOT / "packaging" / "windows" / "onec-attendance-agent.xml"]:
            if item.is_file():
                shutil.copy2(item, out_dir / item.name)
    else:
        shutil.copy2(ROOT / "packaging" / "linux" / "onec-attendance-agent.service", out_dir / "onec-attendance-agent.service")

    print(
        {
            "version": args.version,
            "platform": args.platform,
            "architecture": args.architecture,
            "path": str(target),
            "sha256": sha256(target),
            "file_size": target.stat().st_size,
        }
    )


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
