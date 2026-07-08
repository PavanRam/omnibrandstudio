import time
from dataclasses import dataclass

from sqlalchemy import text

from core.database import get_db
from core.redis import get_redis


class PromptVariableMissingError(Exception):
    pass


class PromptNotFoundError(Exception):
    pass


@dataclass
class PromptTemplate:
    name: str
    version: str
    system_prompt: str
    user_prompt: str
    variables: list[str]


class PromptService:
    CACHE_TTL = 60  # seconds

    async def get_active(self, name: str, org_id: str | None = None) -> PromptTemplate:
        """Resolution: org-specific ACTIVE -> platform ACTIVE. Redis cache with 60s TTL."""
        redis = get_redis()
        cache_key = f"prompt_active:{name}:{org_id or 'platform'}"
        cached = await redis.get(cache_key)
        if cached:
            import json

            data = json.loads(cached)
            return PromptTemplate(**data)

        async with get_db() as conn:
            row = None
            if org_id is not None:
                result = await conn.execute(
                    text(
                        "SELECT name, version, system_prompt, user_prompt, variables "
                        "FROM prompt_registry WHERE name = :name AND org_id = :org_id "
                        "AND status = 'active' LIMIT 1"
                    ),
                    {"name": name, "org_id": org_id},
                )
                row = result.mappings().first()

            if row is None:
                result = await conn.execute(
                    text(
                        "SELECT name, version, system_prompt, user_prompt, variables "
                        "FROM prompt_registry WHERE name = :name AND org_id IS NULL "
                        "AND status = 'active' LIMIT 1"
                    ),
                    {"name": name},
                )
                row = result.mappings().first()

        if row is None:
            raise PromptNotFoundError(f"No active prompt found for '{name}' (org_id={org_id})")

        template = PromptTemplate(
            name=row["name"],
            version=row["version"],
            system_prompt=row["system_prompt"],
            user_prompt=row["user_prompt"],
            variables=list(row["variables"] or []),
        )

        import json

        await redis.set(
            cache_key,
            json.dumps(template.__dict__),
            ex=self.CACHE_TTL,
        )
        return template

    async def render(
        self, name: str, variables: dict, org_id: str | None = None
    ) -> list[dict]:
        """Returns OpenAI-format messages list. Validates all required
        variables are present before rendering."""
        template = await self.get_active(name, org_id=org_id)
        missing = [v for v in template.variables if v not in variables]
        if missing:
            raise PromptVariableMissingError(
                f"Missing variables for prompt '{name}': {missing}"
            )

        system_content = template.system_prompt.format(**variables)
        user_content = template.user_prompt.format(**variables)
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    async def record_performance(
        self,
        name: str,
        version: str,
        brand_score: float,
        latency_ms: int,
        approved: bool,
    ) -> None:
        """Rolling average update: invocation_count, avg_brand_score, avg_latency_ms, approval_rate."""
        async with get_db() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE prompt_registry SET
                        invocation_count = invocation_count + 1,
                        avg_brand_score = COALESCE(
                            (avg_brand_score * invocation_count + :brand_score)
                            / (invocation_count + 1),
                            :brand_score
                        ),
                        avg_latency_ms = COALESCE(
                            (avg_latency_ms * invocation_count + :latency_ms)
                            / (invocation_count + 1),
                            :latency_ms
                        ),
                        approval_rate = COALESCE(
                            (approval_rate * invocation_count + :approved)
                            / (invocation_count + 1),
                            :approved
                        )
                    WHERE name = :name AND version = :version
                    """
                ),
                {
                    "name": name,
                    "version": version,
                    "brand_score": brand_score,
                    "latency_ms": latency_ms,
                    "approved": 1.0 if approved else 0.0,
                },
            )
            await conn.commit()
