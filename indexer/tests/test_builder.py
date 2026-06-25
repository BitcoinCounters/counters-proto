"""The COUNT leaf we build must parse back to the same content via the indexer's
own parser — this is the round-trip that guarantees what we inscribe is exactly
what the indexer will read."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from counter_indexer import builder
from counter_indexer.envelope import find_counter_envelopes


def _roundtrip(content_type: bytes, body: bytes):
    insc = builder.build_inscription(content_type, body, seckey=(5).to_bytes(32, "big"))
    envs = find_counter_envelopes(insc.leaf)
    assert len(envs) == 1, f"expected 1 envelope, got {len(envs)}"
    assert envs[0].content_type == content_type
    assert envs[0].body == body
    return insc


def test_roundtrip_small():
    _roundtrip(b"image/png", b"\x89PNG\r\n\x1a\nhello world")


def test_roundtrip_empty_body():
    _roundtrip(b"text/plain", b"")


def test_roundtrip_multichunk():
    # > 520 bytes forces multiple pushes; the parser must concatenate them.
    body = os.urandom(520 * 3 + 17)
    insc = _roundtrip(b"application/octet-stream", body)
    # exercises chunking explicitly
    assert builder.chunk_body(body)[0] == body[:520]
    assert len(builder.chunk_body(body)) == 4
    assert insc.commit_address.startswith("bc1p")


def test_commit_address_and_control_block_shapes():
    insc = builder.build_inscription(b"text/plain", b"hi", seckey=(9).to_bytes(32, "big"))
    assert insc.commit_address.startswith("bc1p")
    assert len(insc.commit_script_pubkey) == 34  # OP_1 PUSH32 <32>
    assert insc.commit_script_pubkey[:2] == b"\x51\x20"
    assert insc.control_block[1:] == insc.reveal_xonly  # internal key == reveal key
    assert insc.control_block[0] in (0xC0, 0xC1)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("OK")
