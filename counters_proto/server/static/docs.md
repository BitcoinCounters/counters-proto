<!-- Explorer docs. Edit freely; reload the page to see changes.
     Conventions: "## Title {#anchor}" makes a section (the TOC is generated
     automatically); "> **Bold lead.** text" makes a callout; fenced code
     blocks highlight trailing # comments; numbered/bulleted lists get the
     explorer's copper markers. -->

## What a counter is {#what}

A **Bitcoin counter** is a numbered inscription — a file committed to Bitcoin in witness data and linked to a Counterparty asset. Counters are numbered in order of creation.

Any Counterparty asset can carry a counter — named, unnamed, divisible, new, or existing — and one asset can hold many.

The asset does the heavy lifting: identity, ownership, naming, and transfer are all Counterparty's job. The protocol stays small — it defines only the COUNT envelope, the validity rules, and the numbering.

To mint a counter, include a **valid COUNT envelope** — the inscription data plus the Counterparty asset name — in a transaction. The indexer scans the blockchain, finds every valid inscription, and numbers it; the server renders this explorer and its docs.

## The COUNT envelope {#envelope}

The COUNT envelope is a small Bitcoin script — opcodes in the transaction's witness — that carries the inscription as data:

```
OP_FALSE OP_IF
  OP_PUSH "COUNT"          # marker
  OP_PUSH 0x01            # tag 1 = content type
  OP_PUSH <content_type>  # MIME, e.g. image/png
  OP_PUSH 0x02            # tag 2 = target asset
  OP_PUSH <asset>         # e.g. RAREPEPE or A9542…
  OP_0                    # separator; body begins
  OP_PUSH <file bytes>    # ≤520 bytes per push
OP_ENDIF
<pubkey> OP_CHECKSIG
```

The `OP_FALSE OP_IF … OP_ENDIF` block never runs — it is pure data; `<pubkey> OP_CHECKSIG` is the real spend condition. As a taproot leaf script, it is committed in the commit transaction and revealed in the reveal's witness, where the bytes land on-chain (see Minting). It follows ord's envelope structure, so existing parsers work unchanged.

Four things travel in it — the `COUNT` marker, the MIME type, the **target asset** name, and the file. Naming the asset makes the counter envelope-bound: the indexer trusts the envelope's asset and binds to it (see Validity). No pointer, parent, or metadata; the asset already carries those.

## Ownership {#own}

Whoever holds the Counterparty asset balance owns the counter. Transfer is an ordinary Counterparty send of that asset; the witness file never moves — it stays as permanent provenance pinned to the mint transaction.

## Numbering {#number}

Counters are numbered globally, gap-free, starting at **0**, ordered by block height then position within the block — the same scheme Ordinals uses. Only *valid* counters get a number.

> **Genesis is data-defined.** There is no activation height. Counter #0 is simply the first valid counter the indexer finds on-chain.

## Setup {#setup}

The indexer is the only part that needs backends; the explorer alone runs without them. To index, run two fully-synced nodes and point Counters at them.

**1 · Bitcoin Core.** A synced `bitcoind` with a transaction index and RPC enabled:

```
# bitcoin.conf
txindex=1     # required: look up any tx by id
server=1      # enable JSON-RPC
# auth via the cookie file (default) or rpcuser/rpcpassword
```

**2 · Counterparty Core.** The oracle that decides issuance validity, asset identity, and ownership. Run and sync it (v2 API, default port `4000`) per its official docs: [github.com/CounterpartyXCP/counterparty-core ↗](https://github.com/CounterpartyXCP/counterparty-core). Counters only reads from it — it never reimplements consensus.

**3 · Wire them up.** Tell Counters where the backends are (env vars, or copy `.env.example` to `.env`), then verify both are detected:

```
# point at your nodes (defaults shown)
BTC_RPC_URL=http://127.0.0.1:8332
CP_API_URL=http://127.0.0.1:4000

# confirm bitcoind + Counterparty + index heights line up
counters status

# then index, and serve the explorer
counters index --from-genesis
counters server
```

> **Both nodes must be fully synced.** The indexer never advances past Counterparty's height, so a lagging Core simply slows indexing rather than producing wrong results.

## Minting {#mint}

A mint is a taproot commit/reveal pair, built and broadcast together. The reveal carries the file in its witness and, for a new asset, the Counterparty issuance as a plain `OP_RETURN` (a reinscription onto an existing asset carries no issuance — see below).

```
# create a wallet (prints a seed phrase once)
counters wallet create --name me

# inscribe a file as a free numeric asset…
counters wallet --name me inscribe --file cat.png

# …or as a named asset (costs 0.5 XCP)
counters wallet --name me inscribe --file cat.png --asset MYCOUNTER
```

## Validity {#valid}

A transaction records a counter when all hold:

1. its witness has a well-formed `COUNT` envelope, and **exactly one** is present across the whole transaction;
2. the counter **binds** to an asset (below);
3. that asset is not BTC or XCP.

**Binding is envelope-first.** The envelope names its asset (tag `0x02`), and the counter binds to it when either:

- a Counterparty issuance in the **same transaction successfully creates** that asset — a *creation*; or
- the asset **already exists** and the transaction is authorised by its owner — a *reinscription* (see below).

If the named asset doesn't resolve either way — or a legacy envelope names none — the counter falls back to whatever asset the transaction issues. Otherwise it isn't a counter. Validity depends on Counterparty's verdict, not an explorer's listing — an asset can appear indexed yet be an invalid issuance.

## Reinscriptions {#reinscribe}

A counter can also be attached to an **existing** asset you already own — a *reinscription*. Like every counter, its envelope names the asset (tag `0x02`); what makes it a reinscription is that the asset already exists and the transaction carries **no Counterparty message**. It's authorised on-chain by spending an input from the asset's **owner (issuance-rights holder) as of that block** — *ownership*, not token balance, checked at the height of the inscription so a later transfer can't change the verdict.

Each reinscription is a new, permanently-numbered counter, so one asset can back many. The lowest-numbered counter on an asset is its *original*; later ones are reinscriptions, and a counter's page lists them all.

```
# attach a counter to an asset you own (no new asset, no XCP)
counters wallet --name me inscribe --file v2.png --asset RAREPEPE --reinscribe
```

## Server API {#api}

This explorer reads these endpoints from `counters server`:

- `GET /status` — latest synced block + total counter count
- `GET /counters?before=N&limit=K` — recent counters
- `GET /counter/<number|asset>` — one counter's record
- `GET /block/<height>` — counters minted in a block
- `GET /content/<number>` — the raw file, served with its stored MIME

Point the `API` constant at the top of this file's script at your server and the sample data is replaced by live results.

## Source {#source}

Counters is open source — the indexer, CLI, and this explorer all live in one repository: [github.com/BitcoinCounters/counters-proto ↗](https://github.com/BitcoinCounters/counters-proto).

## Community {#community}

Join the conversation on Telegram: [t.me/BitcoinCounters ↗](https://t.me/BitcoinCounters).
