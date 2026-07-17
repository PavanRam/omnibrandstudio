import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SENSITIVE_FIELDS = {
    "password",
    "password_hash",
    "token",
    "key",
    "secret",
    "token_hash",
    "key_hash",
    "totp_secret_enc",
    "api_key",
}


def _scrub(value: dict | None) -> dict | None:
    if value is None:
        return None
    return {k: ("***" if k in SENSITIVE_FIELDS else v) for k, v in value.items()}


async def write_audit(
    db: AsyncConnection,
    entity_type: str,
    action: str,
    actor_id: str | None = None,
    actor_type: str = "user",
    entity_id: str | None = None,
    brand_id: str | None = None,
    org_id: str | None = None,
    before_val: dict | None = None,
    after_val: dict | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    """Append-only audit write. Scrubs SENSITIVE_FIELDS before insert."""
    await db.execute(
        text(
            """
            INSERT INTO audit_log
                (entity_type, entity_id, brand_id, org_id, action, actor_id,
                 actor_type, before_val, after_val, ip_address, request_id)
            VALUES
                (:entity_type, :entity_id, :brand_id, :org_id, :action, :actor_id,
                 :actor_type, :before_val, :after_val, :ip_address, :request_id)
            """
        ),
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "brand_id": brand_id,
            "org_id": org_id,
            "action": action,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "before_val": json.dumps(_scrub(before_val)) if before_val else None,
            "after_val": json.dumps(_scrub(after_val)) if after_val else None,
            "ip_address": ip_address,
            "request_id": request_id,
        },
    )
