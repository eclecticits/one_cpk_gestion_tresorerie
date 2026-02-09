#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.requisition_annexe import RequisitionAnnexe


def annexe_fs_path(file_path: str | None, base_dir: str) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/static/"):
        rel_path = file_path.replace("/static/", "", 1)
        return os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "static", rel_path)
        )
    filename = os.path.basename(file_path)
    return os.path.abspath(os.path.join(base_dir, filename))


def main() -> int:
    base_dir = settings.upload_dir or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "annexes")
    )
    base_dir = os.path.abspath(base_dir)
    print(f"UPLOAD_DIR={base_dir}")

    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    missing = []
    total = 0

    with Session(engine) as session:
        rows = session.execute(select(RequisitionAnnexe)).scalars().all()
        for annexe in rows:
            total += 1
            fs_path = annexe_fs_path(annexe.file_path, base_dir)
            if not fs_path or not os.path.exists(fs_path):
                missing.append((str(annexe.id), annexe.file_path, annexe.filename))

    print(f"Total annexes: {total}")
    print(f"Missing files: {len(missing)}")
    if missing:
        print("Missing list:")
        for annexe_id, file_path, filename in missing:
            print(f"- {annexe_id} | {file_path} | {filename}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
