import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class QueueItem:
    id: str
    equations: list
    batch_number: int
    created_at: str
    status: str
    error: str | None = None


class QueueManager:
    def __init__(self, version: str, version_mgr):
        self._root = version_mgr.queue_root(version)
        # Ensure subdirs exist (version_mgr.create_version creates them, but
        # QueueManager may be instantiated for existing versions too)
        for subdir in ("pending", "processing", "done", "failed"):
            os.makedirs(os.path.join(self._root, subdir), exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def enqueue(self, equations: list, batch_number: int) -> QueueItem:
        item = QueueItem(
            id=str(uuid.uuid4()),
            equations=equations,
            batch_number=batch_number,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )
        self._write(item, "pending")
        return item

    def dequeue(self) -> QueueItem | None:
        pending_dir = os.path.join(self._root, "pending")
        files = sorted(
            f for f in os.listdir(pending_dir) if f.endswith(".json")
        )
        if not files:
            return None
        filename = files[0]
        item = self._read(os.path.join(pending_dir, filename))
        item.status = "processing"
        # Move atomically: write to processing, then remove from pending
        self._write(item, "processing")
        os.remove(os.path.join(pending_dir, filename))
        return item

    def mark_done(self, item: QueueItem):
        self._move(item, from_dir="processing", to_dir="done", status="done")

    def mark_failed(self, item: QueueItem, error: str):
        item.error = error
        self._move(item, from_dir="processing", to_dir="failed", status="failed")

    def retry_failed(self) -> int:
        failed_dir = os.path.join(self._root, "failed")
        files = [f for f in os.listdir(failed_dir) if f.endswith(".json")]
        for filename in files:
            item = self._read(os.path.join(failed_dir, filename))
            item.status = "pending"
            item.error = None
            self._write(item, "pending")
            os.remove(os.path.join(failed_dir, filename))
        return len(files)

    def counts(self) -> dict:
        result = {}
        for subdir in ("pending", "processing", "done", "failed"):
            d = os.path.join(self._root, subdir)
            result[subdir] = len([f for f in os.listdir(d) if f.endswith(".json")])
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _path(self, item_id: str, subdir: str) -> str:
        return os.path.join(self._root, subdir, f"{item_id}.json")

    def _write(self, item: QueueItem, subdir: str):
        with open(self._path(item.id, subdir), "w", encoding="utf-8") as f:
            json.dump(asdict(item), f, indent=2)

    def _read(self, path: str) -> QueueItem:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return QueueItem(**data)

    def _move(self, item: QueueItem, from_dir: str, to_dir: str, status: str):
        item.status = status
        self._write(item, to_dir)
        src = self._path(item.id, from_dir)
        if os.path.exists(src):
            os.remove(src)
