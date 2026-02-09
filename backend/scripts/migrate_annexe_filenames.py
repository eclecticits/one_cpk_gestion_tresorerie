#!/usr/bin/env python3
from __future__ import annotations

import os
from collections import defaultdict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.requisition import Requisition
from app.models.requisition_annexe import RequisitionAnnexe


def safe_ref(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value or "REQ")
    safe = safe.strip("._-")
    return safe or "REQ"


def resolve_upload_dir() -> str:
    return os.path.abspath(
        settings.upload_dir
        or os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "annexes")
    )


def main() -> int:
    base_dir = resolve_upload_dir()
    os.makedirs(base_dir, exist_ok=True)
    print(f"UPLOAD_DIR={base_dir}")

    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    counters: dict[str, int] = defaultdict(int)
    renamed = 0
    missing = 0

    with Session(engine) as session:
        rows = session.execute(
            select(RequisitionAnnexe, Requisition.reference_numero)
            .join(Requisition, RequisitionAnnexe.requisition_id == Requisition.id)
        ).all()

        for annexe, ref_num in rows:
            ref = ref_num or f"REQ-{annexe.requisition_id}"
            safe = safe_ref(ref)
            counters[safe] += 1
            index = counters[safe]

            old_filename = os.path.basename(annexe.file_path or "")
            if not old_filename:
                missing += 1
                print(f"[missing] annexe {annexe.id} has empty file_path")
                continue

            _, ext = os.path.splitext(old_filename)
            ext = (ext or ".bin").lower()
            new_filename = f"{safe}-annex-{index}{ext}"

            old_path = os.path.join(base_dir, old_filename)
            new_path = os.path.join(base_dir, new_filename)

            if old_filename.startswith(f"{safe}-annex-"):
                # Already in expected format.
                continue

            if os.path.exists(old_path):
                if old_path != new_path:
                    os.rename(old_path, new_path)
                annexe.file_path = new_filename
                renamed += 1
                print(f"[renamed] {old_filename} -> {new_filename}")
            else:
                missing += 1
                print(f"[missing] {old_filename} for annexe {annexe.id}")

        session.commit()

    print(f"Renamed: {renamed}")
    print(f"Missing: {missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
