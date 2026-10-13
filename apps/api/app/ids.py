"""UUIDv7 generation (RFC 9562).

Time ordered UUIDs: the first 48 bits are a Unix millisecond timestamp,
so primary keys are roughly insertion ordered. This keeps B tree indexes
dense (new rows append to the right side) instead of the random write
amplification UUIDv4 keys cause. Pure stdlib; no dependency.
"""

import os
import time
import uuid

_last: tuple[int, int] = (0, 0)


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7. Monotonic within a process for same millisecond."""
    global _last
    ts_ms = time.time_ns() // 1_000_000

    # 12 bit intra millisecond sequence in rand_a keeps same ms IDs ordered.
    last_ts, last_seq = _last
    seq = last_seq + 1 if ts_ms == last_ts else int.from_bytes(os.urandom(2)) & 0x07FF
    if seq > 0x0FFF:  # sequence exhausted within one ms; borrow next ms
        ts_ms += 1
        seq = 0
    _last = (ts_ms, seq)

    b = bytearray(16)
    b[0:6] = ts_ms.to_bytes(6, "big")
    b[6] = 0x70 | ((seq >> 8) & 0x0F)  # version 7 + seq high nibble
    b[7] = seq & 0xFF
    tail = os.urandom(8)
    b[8] = (tail[0] & 0x3F) | 0x80  # RFC variant
    b[9:16] = tail[1:8]
    return uuid.UUID(bytes=bytes(b))
