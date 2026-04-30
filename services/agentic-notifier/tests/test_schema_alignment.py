import json
from pathlib import Path

from agentic_notifier.models import NotifyRequest


def test_human_request_schema_tracks_notify_request_model() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    schema = json.loads((repo_root / "schemas" / "human_request.schema.json").read_text())

    model_fields = NotifyRequest.model_fields
    schema_fields = set(schema["properties"])
    required_fields = {
        name for name, field in model_fields.items() if field.is_required()
    }

    assert schema["additionalProperties"] is False
    assert set(model_fields) == schema_fields
    assert set(schema["required"]) == required_fields
    assert "runtime Pydantic model is authoritative" in schema["description"]
