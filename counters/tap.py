"""Taproot primitives for building/signing the reveal transaction.

Self-contained (no libsecp256k1 / no PSBT lib) implementations of:
  - BIP340 Schnorr sign/verify over secp256k1,
  - BIP341 key tweak, P2TR scriptPubKey, control block, bech32m address,
  - BIP342 tapscript sighash (script-path, SIGHASH_DEFAULT),
  - a minimal Bitcoin transaction serializer.

We only ever sign the inscription's script-path input with an ephemeral key we
generate here; the wallet input is signed by Bitcoin Core. Verified against the
official BIP340/341 test vectors (see tests/test_tap.py).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# --- secp256k1 ---------------------------------------------------------------

_p = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_G = (_Gx, _Gy)

Point = tuple  # (x, y) or None for the point at infinity


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    if p1[0] == p2[0] and (p1[1] != p2[1]):
        return None
    if p1 == p2:
        lam = (3 * p1[0] * p1[0] * pow(2 * p1[1] % _p, _p - 2, _p)) % _p
    else:
        lam = ((p2[1] - p1[1]) * pow((p2[0] - p1[0]) % _p, _p - 2, _p)) % _p
    x3 = (lam * lam - p1[0] - p2[0]) % _p
    y3 = (lam * (p1[0] - x3) - p1[1]) % _p
    return (x3, y3)


def _point_mul(p, n):
    r = None
    while n:
        if n & 1:
            r = _point_add(r, p)
        p = _point_add(p, p)
        n >>= 1
    return r


def _has_even_y(p) -> bool:
    return p[1] % 2 == 0


def _lift_x(x: int):
    if x >= _p:
        return None
    y_sq = (pow(x, 3, _p) + 7) % _p
    y = pow(y_sq, (_p + 1) // 4, _p)
    if pow(y, 2, _p) != y_sq:
        return None
    return (x, y if y % 2 == 0 else _p - y)


def _bytes32(x: int) -> bytes:
    return x.to_bytes(32, "big")


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def xonly_pubkey(seckey: bytes) -> bytes:
    """x-only public key (32 bytes) for a 32-byte secret."""
    d0 = _int(seckey)
    if not (1 <= d0 <= _n - 1):
        raise ValueError("invalid secret key")
    p = _point_mul(_G, d0)
    return _bytes32(p[0])


def _seckey_even(seckey: bytes) -> int:
    d0 = _int(seckey)
    p = _point_mul(_G, d0)
    return d0 if _has_even_y(p) else _n - d0


# --- BIP340 Schnorr ----------------------------------------------------------

def schnorr_sign(msg: bytes, seckey: bytes, aux_rand: bytes = b"\x00" * 32) -> bytes:
    d0 = _int(seckey)
    if not (1 <= d0 <= _n - 1):
        raise ValueError("invalid secret key")
    P = _point_mul(_G, d0)
    d = d0 if _has_even_y(P) else _n - d0
    t = (d ^ _int(_tagged_hash("BIP0340/aux", aux_rand))).to_bytes(32, "big")
    rand = _tagged_hash("BIP0340/nonce", t + _bytes32(P[0]) + msg)
    k0 = _int(rand) % _n
    if k0 == 0:
        raise ValueError("nonce is zero")
    R = _point_mul(_G, k0)
    k = k0 if _has_even_y(R) else _n - k0
    e = _int(_tagged_hash("BIP0340/challenge", _bytes32(R[0]) + _bytes32(P[0]) + msg)) % _n
    sig = _bytes32(R[0]) + _bytes32((k + e * d) % _n)
    if not schnorr_verify(msg, _bytes32(P[0]), sig):
        raise ValueError("internal: produced invalid signature")
    return sig


def schnorr_verify(msg: bytes, pubkey: bytes, sig: bytes) -> bool:
    if len(pubkey) != 32 or len(sig) != 64:
        return False
    P = _lift_x(_int(pubkey))
    if P is None:
        return False
    r = _int(sig[:32])
    s = _int(sig[32:])
    if r >= _p or s >= _n:
        return False
    e = _int(_tagged_hash("BIP0340/challenge", sig[:32] + pubkey + msg)) % _n
    R = _point_add(_point_mul(_G, s), _point_mul(P, _n - e))
    if R is None or not _has_even_y(R) or R[0] != r:
        return False
    return True


# --- BIP341 taproot ----------------------------------------------------------

LEAF_VERSION_TAPSCRIPT = 0xC0


def tapleaf_hash(script: bytes, leaf_version: int = LEAF_VERSION_TAPSCRIPT) -> bytes:
    return _tagged_hash("TapLeaf", bytes([leaf_version]) + ser_script(script))


def taproot_tweak_pubkey(internal_xonly: bytes, merkle_root: bytes) -> tuple[int, bytes]:
    """Return (parity_bit, tweaked_xonly_pubkey)."""
    t = _int(_tagged_hash("TapTweak", internal_xonly + merkle_root))
    if t >= _n:
        raise ValueError("invalid tweak")
    P = _lift_x(_int(internal_xonly))
    Q = _point_add(P, _point_mul(_G, t))
    return (Q[1] & 1, _bytes32(Q[0]))


def taproot_tweak_seckey(seckey: bytes, merkle_root: bytes) -> bytes:
    """Tweaked secret for a key-path spend of the same output (unused for the
    inscription leaf, but handy for completeness/tests)."""
    d = _seckey_even(seckey)
    P = _point_mul(_G, d)
    t = _int(_tagged_hash("TapTweak", _bytes32(P[0]) + merkle_root))
    return _bytes32((d + t) % _n)


def control_block(internal_xonly: bytes, merkle_root: bytes,
                  leaf_version: int = LEAF_VERSION_TAPSCRIPT) -> bytes:
    parity, _ = taproot_tweak_pubkey(internal_xonly, merkle_root)
    return bytes([leaf_version | parity]) + internal_xonly


def p2tr_script_pubkey(output_xonly: bytes) -> bytes:
    # OP_1 (0x51) PUSH32 <xonly>
    return bytes([0x51, 0x20]) + output_xonly


# --- bech32 / bech32m (BIP173/350) ------------------------------------------

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= generator[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def encode_segwit_address(hrp: str, witver: int, witprog: bytes) -> str:
    const = 0x2BC830A3 if witver else 1  # bech32m for v1+, bech32 for v0
    data = [witver] + _convertbits(list(witprog), 8, 5)
    values = _hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ const
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in data + checksum)


def p2tr_address(output_xonly: bytes, hrp: str = "bc") -> str:
    return encode_segwit_address(hrp, 1, output_xonly)


# --- script / tx serialization ----------------------------------------------

def ser_compact_size(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def ser_script(script: bytes) -> bytes:
    return ser_compact_size(len(script)) + script


def push_data(data: bytes) -> bytes:
    """Minimal-ish script push (covers our needs: 0..520 byte chunks)."""
    n = len(data)
    if n < 0x4C:
        return bytes([n]) + data
    if n <= 0xFF:
        return bytes([0x4C, n]) + data
    if n <= 0xFFFF:
        return bytes([0x4D]) + n.to_bytes(2, "little") + data
    return bytes([0x4E]) + n.to_bytes(4, "little") + data


@dataclass
class TxIn:
    txid: str           # big-endian hex (as shown by explorers / RPC)
    vout: int
    sequence: int = 0xFFFFFFFF
    witness: list[bytes] = field(default_factory=list)
    script_sig: bytes = b""


@dataclass
class TxOut:
    value: int          # satoshis
    script_pubkey: bytes


def _ser_txin_outpoint(txin: "TxIn") -> bytes:
    return bytes.fromhex(txin.txid)[::-1] + txin.vout.to_bytes(4, "little")


@dataclass
class Tx:
    vin: list
    vout: list
    version: int = 2
    locktime: int = 0

    def has_witness(self) -> bool:
        return any(i.witness for i in self.vin)

    def serialize(self, force_witness: bool | None = None) -> bytes:
        witness = self.has_witness() if force_witness is None else force_witness
        out = self.version.to_bytes(4, "little")
        if witness:
            out += b"\x00\x01"
        out += ser_compact_size(len(self.vin))
        for i in self.vin:
            out += _ser_txin_outpoint(i)
            out += ser_script(i.script_sig)
            out += i.sequence.to_bytes(4, "little")
        out += ser_compact_size(len(self.vout))
        for o in self.vout:
            out += o.value.to_bytes(8, "little") + ser_script(o.script_pubkey)
        if witness:
            for i in self.vin:
                out += ser_compact_size(len(i.witness))
                for item in i.witness:
                    out += ser_script(item)
        out += self.locktime.to_bytes(4, "little")
        return out

    def txid(self) -> str:
        ser = self.serialize(force_witness=False)
        return hashlib.sha256(hashlib.sha256(ser).digest()).digest()[::-1].hex()


# --- BIP341/342 sighash (script-path, SIGHASH_DEFAULT) ----------------------

def taproot_script_path_sighash(
    tx: "Tx",
    input_index: int,
    prevout_values: list,
    prevout_scripts: list,
    tapleaf: bytes,
    hash_type: int = 0x00,
) -> bytes:
    """Signature hash for a tapscript (script-path) spend with SIGHASH_DEFAULT.

    prevout_values / prevout_scripts give the amount (sats) and scriptPubKey for
    EVERY input of tx (taproot commits to all of them).
    """
    sha_prevouts = hashlib.sha256(
        b"".join(_ser_txin_outpoint(i) for i in tx.vin)
    ).digest()
    sha_amounts = hashlib.sha256(
        b"".join(v.to_bytes(8, "little") for v in prevout_values)
    ).digest()
    sha_scriptpubkeys = hashlib.sha256(
        b"".join(ser_script(s) for s in prevout_scripts)
    ).digest()
    sha_sequences = hashlib.sha256(
        b"".join(i.sequence.to_bytes(4, "little") for i in tx.vin)
    ).digest()
    sha_outputs = hashlib.sha256(
        b"".join(o.value.to_bytes(8, "little") + ser_script(o.script_pubkey) for o in tx.vout)
    ).digest()

    spend_type = 2  # 0 (no annex) * 2 + 1 (script path)
    msg = bytes([0x00])  # epoch
    msg += bytes([hash_type])
    msg += tx.version.to_bytes(4, "little")
    msg += tx.locktime.to_bytes(4, "little")
    msg += sha_prevouts + sha_amounts + sha_scriptpubkeys + sha_sequences + sha_outputs
    msg += bytes([spend_type])
    msg += input_index.to_bytes(4, "little")
    # script-path extension
    msg += tapleaf + bytes([0x00]) + (0xFFFFFFFF).to_bytes(4, "little")
    return _tagged_hash("TapSighash", msg)
