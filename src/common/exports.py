"""Versioned analytics dataset exports."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)


EXPORT_SCHEMA_VERSION = "analytics.dataset.v1"
METADATA_SUFFIX = ".metadata.json"


class ExportMetadataError(ValueError):
    """Raised when export metadata is missing or inconsistent."""


class UnsupportedSchemaVersion(ExportMetadataError):
    """Raised when a consumer does not support an export schema version."""


def metadata_path_for(data_path: Path) -> Path:
    return Path(str(data_path) + METADATA_SUFFIX)


def validate_schema_version(
    schema_version: str,
    supported_versions: Optional[Set[str]] = None,
) -> None:
    supported = supported_versions or {EXPORT_SCHEMA_VERSION}
    if schema_version not in supported:
        raise UnsupportedSchemaVersion(
            f"Unsupported export schema version: {schema_version}"
        )


def write_dataset_export(
    records: Iterable[Mapping[str, Any]],
    data_path: Path,
    *,
    field_dictionary: Optional[Dict[str, Dict[str, Any]]] = None,
    schema_version: str = EXPORT_SCHEMA_VERSION,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    record_list = _normalize_records(records)
    generated = generated_at or _utc_now()
    fields = field_dictionary or infer_field_dictionary(record_list)
    metadata = {
        "schema_version": schema_version,
        "generated_at": generated,
        "field_dictionary": fields,
        "record_count": len(record_list),
        "data_file": data_path.name,
    }
    payload = {
        "schema_version": schema_version,
        "generated_at": generated,
        "records": record_list,
    }

    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(_to_json(payload), encoding="utf-8")
    metadata_path_for(data_path).write_text(
        _to_json(metadata),
        encoding="utf-8",
    )
    return metadata


def load_dataset_export(
    data_path: Path,
    *,
    supported_versions: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    metadata_path = metadata_path_for(data_path)
    if not metadata_path.exists():
        raise ExportMetadataError(f"Missing export metadata: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    schema_version = metadata.get("schema_version")
    if not isinstance(schema_version, str):
        raise ExportMetadataError("Export metadata is missing schema_version")
    validate_schema_version(schema_version, supported_versions)

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != schema_version:
        raise ExportMetadataError(
            "Export payload schema does not match metadata"
        )

    records = payload.get("records")
    if not isinstance(records, list):
        raise ExportMetadataError("Export payload records must be a list")
    return records, metadata


def infer_field_dictionary(
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    fields: Dict[str, Dict[str, Any]] = {}
    for record in records:
        for name, value in record.items():
            field = fields.setdefault(
                name,
                {"types": set(), "nullable": False},
            )
            if value is None:
                field["nullable"] = True
            else:
                field["types"].add(_json_type(value))

    normalized: Dict[str, Dict[str, Any]] = {}
    for name, field in fields.items():
        types = sorted(field["types"]) or ["null"]
        normalized[name] = {
            "types": types,
            "nullable": field["nullable"],
        }
    return normalized


def _normalize_records(
    records: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("Dataset export records must be mappings")
        normalized.append(dict(record))
    return normalized


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _to_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
