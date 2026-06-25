"""Minimal bitcoind JSON-RPC client.

Uses cookie-file auth by default (the local node has no rpcuser/rpcpassword),
falling back to explicit user/password if configured.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from .config import Config


class BitcoindError(Exception):
    pass


class BitcoindClient:
    def __init__(self, config: Config):
        self.url = config.btc_rpc_url
        self.timeout = config.http_timeout
        self._auth = self._resolve_auth(config)
        self._session = requests.Session()
        self._id = 0

    @staticmethod
    def _resolve_auth(config: Config) -> tuple[str, str]:
        cookie = Path(config.btc_cookie_file)
        if cookie.exists():
            user, _, password = cookie.read_text().strip().partition(":")
            return (user, password)
        if config.btc_rpc_user:
            return (config.btc_rpc_user, config.btc_rpc_password)
        raise BitcoindError(
            f"No bitcoind auth available: cookie file {config.btc_cookie_file} not found "
            "and BTC_RPC_USER not set."
        )

    def _call(
        self,
        method: str,
        params: list[Any] | None = None,
        wallet: str | None = None,
        timeout: float | None = -1.0,
    ) -> Any:
        self._id += 1
        payload = {"jsonrpc": "1.0", "id": self._id, "method": method, "params": params or []}
        # Wallet RPCs are scoped to the /wallet/<name> endpoint.
        url = f"{self.url.rstrip('/')}/wallet/{wallet}" if wallet else self.url
        # timeout=-1 means "use the default"; None means "wait indefinitely"
        # (needed for blocking calls like a full-history importdescriptors rescan).
        effective = self.timeout if timeout == -1.0 else timeout
        try:
            resp = self._session.post(url, json=payload, auth=self._auth, timeout=effective)
        except requests.RequestException as e:
            raise BitcoindError(f"bitcoind RPC request failed: {e}") from e
        if resp.status_code not in (200, 500):
            raise BitcoindError(f"bitcoind RPC HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if data.get("error"):
            err = data["error"]
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else err
            if code == -18 and wallet:
                # -18 is ambiguous ("does not exist OR is not loaded"); check
                # the wallet dir so we give the right remedy.
                try:
                    on_disk = wallet in self.list_wallet_dir()
                except BitcoindError:
                    on_disk = True  # can't tell: assume it exists, suggest load
                if on_disk:
                    raise BitcoindError(
                        f"wallet {wallet!r} exists but is not loaded in Bitcoin Core. "
                        f"Load it with: bitcoin-cli loadwallet {wallet}"
                    )
                raise BitcoindError(
                    f"wallet {wallet!r} does not exist. "
                    f"Create it with: counter wallet create --name {wallet}"
                )
            raise BitcoindError(f"bitcoind RPC error for {method}: {msg}")
        return data["result"]

    def wallet_call(
        self,
        wallet: str,
        method: str,
        params: list[Any] | None = None,
        timeout: float | None = -1.0,
    ) -> Any:
        """Invoke a wallet-scoped RPC against /wallet/<name>."""
        return self._call(method, params, wallet=wallet, timeout=timeout)

    def list_wallet_dir(self) -> list[str]:
        """Names of wallets present in Bitcoin Core's wallet directory (whether
        or not they are currently loaded)."""
        data = self._call("listwalletdir")
        return [w.get("name") for w in (data or {}).get("wallets", [])]

    # --- high-level helpers ------------------------------------------------

    def get_block_count(self) -> int:
        return int(self._call("getblockcount"))

    def get_block_hash(self, height: int) -> str:
        return self._call("getblockhash", [height])

    def get_block(self, block_hash: str, verbosity: int = 2) -> dict:
        """Verbosity 2 returns full tx data including vin[].txinwitness."""
        return self._call("getblock", [block_hash, verbosity])

    def get_block_at_height(self, height: int, verbosity: int = 2) -> dict:
        return self.get_block(self.get_block_hash(height), verbosity)

    def get_raw_transaction(self, txid: str, verbose: bool = True) -> dict:
        """Decoded tx (verbose=True) including vin[].txinwitness and, if mined,
        the 'blockhash'. Requires txindex=1 for non-wallet, non-mempool txs."""
        return self._call("getrawtransaction", [txid, verbose])

    def get_block_header(self, block_hash: str) -> dict:
        """Header object including 'height' and 'confirmations'."""
        return self._call("getblockheader", [block_hash])
