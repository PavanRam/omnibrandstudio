"""
Centralised ID generation helpers.

All public IDs use UUIDv7 (RFC 9562) — monotonically increasing within the
same millisecond, so they are naturally sortable and B-tree friendly.
"""
from __future__ import annotations

import os
import time
import uuid as _uuid_mod


def new_uuid7() -> str:
    """Return a new UUIDv7 string.

    Layout (128 bits, big-endian per RFC 9562):

      bits 127-80 : unix_ts_ms  (48-bit millisecond timestamp)
      bits  79-76 : ver = 7
      bits  75-64 : rand_a      (12 random bits)
      bits  63-62 : var = 0b10  (RFC 4122 variant)
      bits  61-0  : rand_b      (62 random bits)
    """
    ts_ms = int(time.time() * 1_000) & 0xFFFF_FFFF_FFFF  # 48 bits
    rnd = int.from_bytes(os.urandom(10), "big")            # 80 bits → use 74
    rand_a = (rnd >> 68) & 0xFFF                           # top-12
    rand_b = rnd & 0x3FFF_FFFF_FFFF_FFFF                   # bottom-62
    val = (
        (ts_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(_uuid_mod.UUID(int=val))


def new_request_id() -> str:
    """Return a new UUIDv7 for use as an HTTP X-Request-ID."""
    return new_uuid7()


def new_campaign_id() -> str:
    """Return a new UUIDv7 for use as a campaign primary key."""
    return new_uuid7()


def is_valid_uuid(value: str) -> bool:
    """Return True when *value* is a well-formed UUID (any version)."""
    try:
        _uuid_mod.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
