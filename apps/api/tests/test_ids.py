import uuid as uuid_module

from app.ids import uuid7


def test_uuid7_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == uuid_module.RFC_4122


def test_uuid7_time_ordered() -> None:
    """Sequentially generated IDs sort in generation order, including
    bursts within the same millisecond (the intra ms sequence counter)."""
    ids = [uuid7() for _ in range(5000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_uuid7_timestamp_is_now() -> None:
    import time

    u = uuid7()
    ts_ms = int.from_bytes(u.bytes[0:6], "big")
    assert abs(ts_ms - time.time_ns() // 1_000_000) < 2_000
