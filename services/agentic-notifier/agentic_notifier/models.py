from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    priority: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    context: str = ""
    message_body: str | None = None
    agent_recommendation: str = ""
    minimum_user_action: str = ""
    reply_format: str = ""
    unblocked_work_remaining: list[str] = Field(default_factory=list)
    dedupe_key: str | None = None
    expects_reply: bool = True
    dry_run: bool = False


class NotifyResponse(BaseModel):
    ok: bool
    request_id: str
    sent: bool
    dry_run: bool
    deduped: bool
    message_preview: str
