"""Instance inventory (config/instances.yaml). Stands in for ec2:DescribeInstances in the PoC."""
from __future__ import annotations

from pathlib import Path

import yaml

from opsagent.config import get_settings
from opsagent.schemas.triage import InstanceDetails


def load_inventory() -> dict:
    """Load the inventory yaml named by `get_settings().inventory_path`.

    Always returns a dict with `instances` and `repositories` keys (empty when the file is missing or malformed).
    """
    path = get_settings().inventory_path
    data: object = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("instances", {})
    data.setdefault("repositories", {})
    if not isinstance(data["instances"], dict):
        data["instances"] = {}
    if not isinstance(data["repositories"], dict):
        data["repositories"] = {}
    return data


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def lookup_instance(instance_id: str, region: str | None = None) -> InstanceDetails:
    """Describe an instance from the inventory.

    Returns `source="inventory"` with type, memory, vcpus, swap, region, tags and units when the id is known;
    otherwise `source="unknown"` carrying only the id (and the region passed in, if any).
    """
    entry = load_inventory()["instances"].get(instance_id)
    if not isinstance(entry, dict):
        return InstanceDetails(instance_id=instance_id, region=region, source="unknown")

    tags_raw = entry.get("tags") or {}
    tags = {str(k): str(v) for k, v in tags_raw.items()} if isinstance(tags_raw, dict) else {}
    units_raw = entry.get("units") or {}
    units = {str(k): dict(v or {}) for k, v in units_raw.items()} if isinstance(units_raw, dict) else {}

    return InstanceDetails(
        instance_id=instance_id,
        instance_type=entry.get("instance_type"),
        total_memory_mb=_as_int(entry.get("total_memory_mb")),
        vcpus=_as_int(entry.get("vcpus")),
        swap_mb=_as_int(entry.get("swap_mb")),
        region=entry.get("region") or region,
        tags=tags,
        units=units,
        source="inventory",
    )


def repository_for(app: str) -> Path | None:
    """Path of the repository mapped to an `app` tag, resolved against the project root; None if unmapped."""
    if not app:
        return None
    repo = load_inventory()["repositories"].get(app)
    if not isinstance(repo, dict) or not repo.get("path"):
        return None
    return get_settings().resolve(Path(str(repo["path"])))
