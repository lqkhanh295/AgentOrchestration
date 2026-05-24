import json

import pytest

from src.common.exports import (
    EXPORT_SCHEMA_VERSION,
    ExportMetadataError,
    UnsupportedSchemaVersion,
    infer_field_dictionary,
    load_dataset_export,
    metadata_path_for,
    write_dataset_export,
)


def test_write_dataset_export_includes_schema_metadata(tmp_path):
    data_path = tmp_path / "analytics.json"

    metadata = write_dataset_export(
        [{"task_id": "task-1", "duration_ms": 12, "error": None}],
        data_path,
        generated_at="2026-05-24T02:23:00Z",
    )

    assert data_path.exists()
    assert metadata_path_for(data_path).exists()
    assert metadata["schema_version"] == EXPORT_SCHEMA_VERSION
    assert metadata["generated_at"] == "2026-05-24T02:23:00Z"
    assert metadata["record_count"] == 1
    assert metadata["field_dictionary"]["task_id"]["types"] == ["string"]
    assert metadata["field_dictionary"]["error"]["nullable"] is True


def test_load_dataset_export_rejects_missing_metadata(tmp_path):
    data_path = tmp_path / "analytics.json"
    data_path.write_text('{"records": []}\n', encoding="utf-8")

    with pytest.raises(ExportMetadataError):
        load_dataset_export(data_path)


def test_load_dataset_export_rejects_unsupported_schema_version(tmp_path):
    data_path = tmp_path / "analytics.json"
    write_dataset_export([{"task_id": "task-1"}], data_path)
    metadata_path = metadata_path_for(data_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = "analytics.dataset.v99"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersion):
        load_dataset_export(data_path)


def test_load_dataset_export_rejects_payload_metadata_mismatch(tmp_path):
    data_path = tmp_path / "analytics.json"
    write_dataset_export([{"task_id": "task-1"}], data_path)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "analytics.dataset.v99"
    data_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExportMetadataError):
        load_dataset_export(data_path)


def test_infer_field_dictionary_tracks_types_and_nullability():
    fields = infer_field_dictionary(
        [
            {"task_id": "task-1", "duration_ms": 12, "error": None},
            {"task_id": "task-2", "duration_ms": 1.5, "error": "timeout"},
        ]
    )

    assert fields["task_id"] == {
        "types": ["string"],
        "nullable": False,
    }
    assert fields["duration_ms"] == {
        "types": ["integer", "number"],
        "nullable": False,
    }
    assert fields["error"] == {
        "types": ["string"],
        "nullable": True,
    }
