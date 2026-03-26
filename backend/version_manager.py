import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")
QUEUE_DIR   = os.path.join(os.path.dirname(__file__), "queue")


@dataclass
class VersionMeta:
    version: str
    created_at: str
    policy_hash: str
    policy_snapshot: str
    config_snapshot: dict
    equation_count: int = 0
    java_file_count: int = 0
    status: str = "generating"


class VersionManager:
    def next_version(self) -> str:
        if not os.path.isdir(OUTPUTS_DIR):
            return "v1"
        existing = [
            d for d in os.listdir(OUTPUTS_DIR)
            if d.startswith("v") and d[1:].isdigit() and os.path.isdir(os.path.join(OUTPUTS_DIR, d))
        ]
        if not existing:
            return "v1"
        nums = [int(d[1:]) for d in existing]
        return f"v{max(nums) + 1}"

    def create_version(self, policy_text: str, cfg) -> VersionMeta:
        version = self.next_version()

        # Create output dirs
        os.makedirs(os.path.join(OUTPUTS_DIR, version, "equations"), exist_ok=True)
        os.makedirs(os.path.join(OUTPUTS_DIR, version, "java"), exist_ok=True)

        # Create queue dirs
        queue_root = os.path.join(QUEUE_DIR, version)
        for subdir in ("pending", "processing", "done", "failed"):
            os.makedirs(os.path.join(queue_root, subdir), exist_ok=True)

        policy_hash = hashlib.sha256(policy_text.encode()).hexdigest()

        # Build config snapshot (exclude non-serialisable fields)
        config_snapshot = {
            k: v for k, v in cfg.__dict__.items()
            if isinstance(v, (str, int, float, bool, list, dict, type(None)))
        }

        meta = VersionMeta(
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            policy_hash=policy_hash,
            policy_snapshot=policy_text,
            config_snapshot=config_snapshot,
        )
        self._write_meta(version, meta)
        return meta

    def update_meta(self, version: str, **kwargs):
        meta = self.get_meta(version)
        for k, v in kwargs.items():
            if hasattr(meta, k):
                setattr(meta, k, v)
        self._write_meta(version, meta)

    def list_versions(self) -> list[VersionMeta]:
        if not os.path.isdir(OUTPUTS_DIR):
            return []
        versions = []
        for d in os.listdir(OUTPUTS_DIR):
            if d.startswith("v") and d[1:].isdigit():
                meta_path = os.path.join(OUTPUTS_DIR, d, "meta.json")
                if os.path.exists(meta_path):
                    versions.append(self._read_meta(meta_path))
        versions.sort(key=lambda m: m.created_at, reverse=True)
        return versions

    def get_meta(self, version: str) -> VersionMeta:
        meta_path = os.path.join(OUTPUTS_DIR, version, "meta.json")
        return self._read_meta(meta_path)

    def equations_dir(self, version: str) -> str:
        return os.path.join(OUTPUTS_DIR, version, "equations")

    def java_dir(self, version: str) -> str:
        return os.path.join(OUTPUTS_DIR, version, "java")

    def archive_java(self, version: str) -> str | None:
        """Move all .java files to java_archive/run_NNN/. Returns archive path or None if nothing to archive."""
        java_dir = self.java_dir(version)
        if not os.path.isdir(java_dir):
            return None
        files = [f for f in os.listdir(java_dir) if f.endswith(".java")]
        if not files:
            return None
        archive_base = os.path.join(OUTPUTS_DIR, version, "java_archive")
        os.makedirs(archive_base, exist_ok=True)
        existing_runs = [d for d in os.listdir(archive_base) if d.startswith("run_")]
        next_num = len(existing_runs) + 1
        archive_dir = os.path.join(archive_base, f"run_{next_num:03d}")
        os.makedirs(archive_dir)
        for f in files:
            shutil.move(os.path.join(java_dir, f), os.path.join(archive_dir, f))
        return archive_dir

    def list_java_archives(self, version: str) -> list[dict]:
        """Return archive runs with file counts, newest first."""
        archive_base = os.path.join(OUTPUTS_DIR, version, "java_archive")
        if not os.path.isdir(archive_base):
            return []
        runs = sorted(
            (d for d in os.listdir(archive_base) if d.startswith("run_")),
            reverse=True,
        )
        return [
            {"run": r, "files": len([f for f in os.listdir(os.path.join(archive_base, r)) if f.endswith(".java")])}
            for r in runs
        ]

    def queue_root(self, version: str) -> str:
        return os.path.join(QUEUE_DIR, version)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _meta_path(self, version: str) -> str:
        return os.path.join(OUTPUTS_DIR, version, "meta.json")

    def _write_meta(self, version: str, meta: VersionMeta):
        with open(self._meta_path(version), "w", encoding="utf-8") as f:
            json.dump(asdict(meta), f, indent=2)

    def _read_meta(self, path: str) -> VersionMeta:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return VersionMeta(**data)
