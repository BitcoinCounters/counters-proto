# Counterparty Inscriptions Indexer (Bitcoin Counters) — MVP

Indexes **Bitcoin Counters**: files stored in Bitcoin witness data (a `COUNT`
envelope) and bound to a Counterparty asset minted in the same transaction.

This is the MVP: **parse → join → number → store**, plus a tip-follow loop.
Reorg renumbering and a read/serve API are deliberately out of scope for now.

## How it works

For each block (ascending):

1. **Parse** — scan every input's witness for a `COUNT` envelope
   (`OP_FALSE OP_IF "COUNT" <0x01 content_type> <0x00> <body…> OP_ENDIF …`).
2. **Join** — a tx with **exactly one** valid envelope is matched against
   Counterparty Core's issuances for that block.
3. **Validate (via Core, the oracle)** — keep it only if the issuance is
   `status == "valid"`, is the asset's **first/creation** issuance
   (`asset_events` contains `creation`), and the asset is not `BTC`/`XCP`.
4. **Number & store** — assign the next gap-free number (from 0), write the
   file to a content-addressed blob store, and insert the record into SQLite.

We never reimplement Counterparty consensus — Core decides issuance validity,
asset identity, and ownership.

## Requirements

- Python 3.10+
- A synced **bitcoind** with `txindex=1` (RPC reachable; cookie auth supported)
- A synced **Counterparty Core** v2 API

```bash
pip install -e .          # installs deps + the `counters` console command
```

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `BTC_RPC_URL` | `http://127.0.0.1:8332` | bitcoind JSON-RPC URL |
| `BTC_COOKIE_FILE` | `~/.bitcoin/.cookie` | bitcoind cookie (preferred auth) |
| `BTC_RPC_USER` / `BTC_RPC_PASSWORD` | — | fallback if no cookie |
| `CP_API_URL` | `http://127.0.0.1:4000` | Counterparty Core v2 API |
| `COUNTER_DATA_DIR` | `data/` | SQLite + blobs location |
| `COUNTER_START_HEIGHT` | `709632` | first block to scan (taproot activation) |
| `COUNTER_CONFIRMATIONS` | `0` | blocks behind tip to stay |
| `COUNTER_POLL_INTERVAL` | `15` | seconds between tip polls in `run` |

> Counters require a taproot script-path reveal, so none can exist before
> taproot activation (mainnet block 709632) — that's the default first-time
> scan floor. Set `COUNTER_START_HEIGHT` higher (near the tip) for fast test
> iteration; numbering within a fixed range is identical either way.
>
> **To rescan from scratch, delete the data dir first** (`rm -rf data`).
> Stored sync progress always takes precedence over `COUNTER_START_HEIGHT`,
> so the start height only applies on a fresh database.

## Usage

Invoke as `counters <command>` after `pip install -e .`, or equivalently
`python -m counters <command>`.

```bash
# --- indexing ---
counters index -v                                  # continuously sync + follow the tip
counters sync --stop-at 720000                     # one-shot catch-up (bounded for tests)

# --- reads (need only a synced index) ---
counters status                                    # bitcoind / Counterparty / index heights
counters list                                      # 20 most recent
counters list --recent 50
counters list --owner bc1p...                      # by mint-time owner
counters list --block 800000-800100                # by block range
counters info 0                                    # metadata by number
counters info RAREPEPE                             # ...or by asset name / longname
counters info 0 --json                             # metadata as JSON
counters info 0 --raw > cat.png                     # stream the file bytes
counters info 0 --save cat.png                      # write the file to disk
counters validate <txid>                           # is this tx a counter, and why / why not

# --- web explorer + read-only JSON API ---
counters server                                    # http://127.0.0.1:8080
counters server --host 0.0.0.0 --port 8080         # bind publicly / pick a port

# --- wallet (taproot BIP86, bc1p; keys held by Bitcoin Core) ---
counters wallet --name mywallet create             # new wallet; prints a 12-word seed ONCE
counters wallet --name mywallet restore            # re-import from a seed (read on stdin) + rescan
counters wallet --name mywallet receive            # next taproot (bc1p) address
counters wallet --name mywallet balance            # BTC + aggregated Counterparty balances
counters wallet --name mywallet inscriptions       # counters held by the wallet

# mint a counter from a file (commit + reveal). --dry-run builds, signs, and
# package-validates both txs WITHOUT broadcasting (prints raw hex + cost).
counters wallet --name mywallet inscribe --file cat.png --dry-run
counters wallet --name mywallet inscribe --file cat.png                    # free numeric asset
counters wallet --name mywallet inscribe --file cat.png --asset ZOMBIEPEPES # named (0.5 XCP)
counters wallet --name mywallet inscribe --file cat.png --fee-rate 8 --commit-fee-rate 4
```

> The 12-word seed is the only backup and is shown once at create time. The
> keys are imported into a Bitcoin Core descriptor wallet, which holds them and
> does all signing; this tool never touches private keys after derivation.
> `--name` defaults to `counter`.

## Tests

```bash
python -m pytest            # if pytest installed
python tests/test_envelope.py   # zero-dependency runner
```

## Layout

```
counters/
  config.py         protocol constants + env-driven Config
  bitcoind.py       JSON-RPC client (cookie auth, getblock witnesses)
  envelope.py       script tokenizer + COUNT envelope parser
  counterparty.py   Core v2 client (the oracle)
  store.py          SQLite schema + content-hash blob store + queries
  builder.py        COUNT leaf script + P2TR commit-address derivation
  tap.py            BIP340 Schnorr + BIP341/342 taproot + tx serializer
  bip32.py          BIP32/BIP86 derivation (pure-Python RIPEMD160 + ecdsa)
  progress.py       ord-style progress bar
  __main__.py       CLI command tree (parser + dispatch)
  indexer/          the indexing engine
    indexer.py      pipeline + run loops
  commands/         CLI command handlers
    read.py         status / info / list / validate
    wallet.py       create / restore / receive / balance / inscriptions
    inscribe.py     mint flow: compose issuance + build/sign commit & reveal
    serve.py        server command entry point
  server/           web explorer + read-only JSON API
    app.py          stdlib HTTP server (static SPA + /counters /counter /content)
    static/         index.html + logos/favicon (served assets)
pyproject.toml      installs the `counters` console command
docs/               protocol + CLI reference PDFs
tests/
  test_envelope.py  parser unit tests
```

## Not yet implemented (v2+)

- `send` — transfer a counter (Counterparty asset) via compose + Core sign
- Reorg detection + renumbering with a finality depth
- Frozen marker/genesis height + canonical test vectors

> `inscribe` is implemented (commit/reveal + OP_RETURN issuance). Every mint is
> package-validated with `testmempoolaccept` before any funds move; `--dry-run`
> stops there and prints the raw hex.
