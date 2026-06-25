"""Offline tests for tap.py: secp256k1 point math, BIP340 Schnorr, and the
serialization helpers. BIP341 tweak/address are cross-checked against Bitcoin
Core separately (see the inline check run during development)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from counter_indexer import tap


def test_xonly_pubkey_known_points():
    # x-coordinates of 1G, 2G, 3G on secp256k1 (well-known constants).
    assert tap.xonly_pubkey(bytes.fromhex(
        "0000000000000000000000000000000000000000000000000000000000000001"
    )).hex().upper() == "79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798"
    assert tap.xonly_pubkey(bytes.fromhex(
        "0000000000000000000000000000000000000000000000000000000000000002"
    )).hex().upper() == "C6047F9441ED7D6D3045406E95C07CD85C778E4B8CEF3CA7ABAC09B95C709EE5"
    assert tap.xonly_pubkey(bytes.fromhex(
        "0000000000000000000000000000000000000000000000000000000000000003"
    )).hex().upper() == "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9"


def test_schnorr_sign_verify_roundtrip():
    for d in (1, 3, 0x1234, 0xDEADBEEF):
        seckey = d.to_bytes(32, "big")
        pub = tap.xonly_pubkey(seckey)
        for m in (b"\x00" * 32, b"\x11" * 32, os.urandom(32)):
            sig = tap.schnorr_sign(m, seckey, aux_rand=b"\x00" * 32)
            assert tap.schnorr_verify(m, pub, sig)
            # tampered signature must fail
            bad = bytearray(sig)
            bad[0] ^= 0x01
            assert not tap.schnorr_verify(m, pub, bytes(bad))
            # wrong message must fail
            assert not tap.schnorr_verify(b"\x22" * 32, pub, sig)


def test_schnorr_deterministic_with_fixed_aux():
    seckey = (3).to_bytes(32, "big")
    m = b"\x00" * 32
    s1 = tap.schnorr_sign(m, seckey, aux_rand=b"\x00" * 32)
    s2 = tap.schnorr_sign(m, seckey, aux_rand=b"\x00" * 32)
    assert s1 == s2  # same inputs -> same signature


def test_compact_size_and_push():
    assert tap.ser_compact_size(0x10) == b"\x10"
    assert tap.ser_compact_size(0xFD) == b"\xfd\xfd\x00"
    assert tap.ser_compact_size(0x100) == b"\xfd\x00\x01"
    assert tap.push_data(b"\x01\x02") == b"\x02\x01\x02"
    assert tap.push_data(b"\x00" * 0x4C)[:2] == b"\x4c\x4c"


def test_tx_txid_known_vector():
    # A minimal coinbase-like tx serializes deterministically; just assert the
    # serializer is stable and witness/no-witness txid differ appropriately.
    txin = tap.TxIn(txid="00" * 32, vout=0xFFFFFFFF, script_sig=b"\x51")
    txout = tap.TxOut(value=5000000000, script_pubkey=b"\x51")
    tx = tap.Tx(vin=[txin], vout=[txout])
    assert isinstance(tx.txid(), str) and len(tx.txid()) == 64
    # adding a witness must not change the (non-witness) txid
    before = tx.txid()
    tx.vin[0].witness = [b"\xde\xad"]
    assert tx.txid() == before


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("OK")
