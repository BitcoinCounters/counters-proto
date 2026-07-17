"""Unit tests for `counters wallet send` helpers (no network/Core needed).

Covers the two bits of real logic: human->raw quantity conversion and picking
a single source address that holds enough of the asset.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import counters_proto.commands.send as S  # noqa: E402
from counters_proto.commands.send import _find_source, _to_raw_quantity  # noqa: E402


def test_to_raw_quantity_divisible():
    assert _to_raw_quantity("1", True) == 100_000_000
    assert _to_raw_quantity("0.5", True) == 50_000_000
    assert _to_raw_quantity("0.0003131", True) == 31_310


def test_to_raw_quantity_indivisible():
    assert _to_raw_quantity("1", False) == 1
    assert _to_raw_quantity("10", False) == 10


def test_to_raw_quantity_rejects_bad_input():
    for bad in ("0", "-1", "abc"):
        try:
            _to_raw_quantity(bad, True)
            assert False, f"{bad!r} should have raised"
        except ValueError:
            pass
    # fractional amount of an indivisible asset is invalid
    try:
        _to_raw_quantity("1.5", False)
        assert False, "fractional indivisible should have raised"
    except ValueError:
        pass


class _DuckCp:
    def __init__(self, balances):
        self._balances = balances

    def get_address_balances(self, addr):
        return self._balances.get(addr, [])


def _patch_addresses(addrs):
    S._wallet_addresses = lambda btc, wallet: addrs


def test_find_source_returns_first_address_with_enough():
    cp = _DuckCp({
        "bc1pA": [{"asset": "RAREPEPE", "asset_longname": None, "quantity": 3}],
        "bc1pB": [{"asset": "RAREPEPE", "asset_longname": None, "quantity": 10}],
    })
    orig = S._wallet_addresses
    _patch_addresses(["bc1pA", "bc1pB"])
    try:
        addr, have = _find_source(object(), cp, "me", "RAREPEPE", 5)
        assert addr == "bc1pB" and have == 10
        # When none has enough, returns the richest so the caller can report it.
        addr2, have2 = _find_source(object(), cp, "me", "RAREPEPE", 50)
        assert addr2 == "bc1pB" and have2 == 10
        # Unknown asset -> nothing found.
        none_addr, none_have = _find_source(object(), cp, "me", "NOPE", 1)
        assert none_addr is None and none_have == 0
    finally:
        S._wallet_addresses = orig


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ok")
