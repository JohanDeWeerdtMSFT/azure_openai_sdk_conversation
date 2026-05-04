#!/usr/bin/env python3
"""Export Home Assistant conversation-exposed entities.

Reads Home Assistant .storage registry files and outputs only entities exposed to
conversation assistants. Optionally enriches with last known state from
core.restore_state.

Usage examples:
  python scripts/export_exposed_entities.py
  python scripts/export_exposed_entities.py --ha-config /config
  python scripts/export_exposed_entities.py --format csv --output exposed_entities.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any


CONTROLLABLE_DOMAINS = {
    "light",
    "switch",
    "fan",
    "climate",
    "cover",
    "lock",
    "media_player",
    "vacuum",
    "scene",
    "script",
    "button",
}


def _load_storage_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        raise RuntimeError(f"Failed to parse JSON file: {path} ({err})") from err


def _extract_entities_payload(doc: dict[str, Any]) -> list[dict[str, Any]]:
    # Current HA storage shape is usually: {"data": {"entities": [...]}}
    # but keep this defensive to survive shape changes.
    data = doc.get("data") if isinstance(doc, dict) else None
    if isinstance(data, dict):
        entities = data.get("entities")
        if isinstance(entities, list):
            return entities
    return []


def _extract_areas_payload(doc: dict[str, Any]) -> list[dict[str, Any]]:
    data = doc.get("data") if isinstance(doc, dict) else None
    if isinstance(data, dict):
        areas = data.get("areas")
        if isinstance(areas, list):
            return areas
    return []


def _extract_devices_payload(doc: dict[str, Any]) -> list[dict[str, Any]]:
    data = doc.get("data") if isinstance(doc, dict) else None
    if isinstance(data, dict):
        devices = data.get("devices")
        if isinstance(devices, list):
            return devices
    return []


def _extract_restore_states(doc: dict[str, Any]) -> dict[str, str]:
    # Usually: {"data": [{"state": {"entity_id": "...", "state": "..."}}, ...]}
    out: dict[str, str] = {}
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        st = item.get("state")
        if not isinstance(st, dict):
            continue
        entity_id = st.get("entity_id")
        state = st.get("state")
        if isinstance(entity_id, str) and isinstance(state, str):
            out[entity_id] = state
    return out


def _is_exposed(entity_entry: dict[str, Any]) -> bool:
    options = entity_entry.get("options")
    if not isinstance(options, dict):
        return False

    conv_opts = options.get("conversation")
    if not isinstance(conv_opts, dict):
        return False

    # HA has used both names in different places/versions.
    if "should_expose" in conv_opts:
        return bool(conv_opts.get("should_expose"))
    if "expose" in conv_opts:
        return bool(conv_opts.get("expose"))
    return False


def _domain_of(entity_id: str) -> str:
    if "." not in entity_id:
        return ""
    return entity_id.split(".", 1)[0]


def _infer_controllable(domain: str) -> str:
    return "yes" if domain in CONTROLLABLE_DOMAINS else "no"


def _infer_safety(domain: str, controllable: str) -> str:
    if controllable == "no":
        return "safe"
    if domain in {"lock", "cover", "climate"}:
        return "caution"
    return "caution"


def build_rows(ha_config: Path) -> list[dict[str, str]]:
    storage_dir = ha_config / ".storage"

    entity_doc = _load_storage_json(storage_dir / "core.entity_registry")
    area_doc = _load_storage_json(storage_dir / "core.area_registry")
    device_doc = _load_storage_json(storage_dir / "core.device_registry")
    restore_doc = _load_storage_json(storage_dir / "core.restore_state")

    entities = _extract_entities_payload(entity_doc)
    areas = _extract_areas_payload(area_doc)
    devices = _extract_devices_payload(device_doc)
    restore_states = _extract_restore_states(restore_doc)

    area_map = {
        a.get("area_id"): a.get("name", "")
        for a in areas
        if isinstance(a, dict) and isinstance(a.get("area_id"), str)
    }

    device_area_map = {
        d.get("id"): d.get("area_id")
        for d in devices
        if isinstance(d, dict) and isinstance(d.get("id"), str)
    }

    rows: list[dict[str, str]] = []

    for ent in entities:
        if not isinstance(ent, dict):
            continue
        if not _is_exposed(ent):
            continue

        entity_id = str(ent.get("entity_id", "")).strip()
        if not entity_id:
            continue

        domain = _domain_of(entity_id)
        friendly_name = str(ent.get("name") or entity_id)

        aliases: list[str] = []
        opts = ent.get("options")
        if isinstance(opts, dict):
            conv_opts = opts.get("conversation")
            if isinstance(conv_opts, dict):
                raw_aliases = conv_opts.get("aliases", [])
                if isinstance(raw_aliases, list):
                    aliases = [str(a) for a in raw_aliases if str(a).strip()]

        area_id = ent.get("area_id")
        if not area_id:
            device_id = ent.get("device_id")
            if device_id:
                area_id = device_area_map.get(device_id)
        area_name = str(area_map.get(area_id, ""))

        last_state = restore_states.get(entity_id, "")
        controllable = _infer_controllable(domain)
        safety = _infer_safety(domain, controllable)

        row = {
            "entity_id": entity_id,
            "friendly_name": friendly_name,
            "domain": domain,
            "area": area_name,
            "aliases": ", ".join(aliases),
            "typical_states": last_state,
            "controllable": controllable,
            "safety_level": safety,
        }
        rows.append(row)

    rows.sort(key=lambda r: (r["area"], r["entity_id"]))
    return rows


def write_json(rows: list[dict[str, str]], output: Path) -> None:
    output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    fieldnames = [
        "entity_id",
        "friendly_name",
        "domain",
        "area",
        "aliases",
        "typical_states",
        "controllable",
        "safety_level",
    ]
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export HA conversation-exposed entities")
    parser.add_argument(
        "--ha-config",
        default=os.getenv("HA_CONFIG", "/config"),
        help="Home Assistant config directory (default: /config or HA_CONFIG env)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output file path (default: exposed_entities.json or .csv in current dir)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ha_config = Path(args.ha_config)

    if not ha_config.exists():
        print(f"ERROR: HA config directory not found: {ha_config}", file=sys.stderr)
        return 2

    rows = build_rows(ha_config)

    default_name = "exposed_entities.json" if args.format == "json" else "exposed_entities.csv"
    output = Path(args.output) if args.output else Path.cwd() / default_name

    if args.format == "json":
        write_json(rows, output)
    else:
        write_csv(rows, output)

    print(f"Exported {len(rows)} exposed entities to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
