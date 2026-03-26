import hashlib
import json
import os
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
