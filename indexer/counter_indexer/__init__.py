"""Counterparty Inscriptions (Bitcoin Counters) indexer.

MVP: scan Bitcoin witnesses for a "COUNTER" envelope, join with a successful
first issuance reported by Counterparty Core, assign a global sequential
number, and store the record + file content.

Architecture rule: do NOT reimplement Counterparty consensus. Counterparty
Core is the oracle for issuance validity, asset identity, and ownership. This
package owns only witness parsing, the join, and numbering.
"""

__version__ = "0.1.0"
