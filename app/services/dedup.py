"""Dublettenprüfung beim Import – lieber nachfragen als still verwerfen oder doppelt buchen.

Reihenfolge je Zeile (in Dateireihenfolge):
1. Bekannte Bank-ID → Dublette; gleiche ID mit abweichenden Daten → Konflikt (ambiguous).
2. Gleicher Fingerprint wie eine früher importierte Buchung → ambiguous („fingerprint“).
3. Ähnliche Buchung (gleicher Betrag; gleicher Tag bei importierten, ±3 Tage bei
   manuell erfassten Buchungen) → ambiguous („similar“).
4. Sonst neu.
Jede vorhandene Buchung wird höchstens einer Zeile zugeordnet. Mehrere echte, gleiche
Zahlungen in einer Datei bleiben so erhalten; Treffer ohne Bank-ID entscheidet der Nutzer.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, select

from app.importers.base import ParsedRow, fingerprint
from app.models import Account, Transaction
from app.models.imports import MatchKind, RowDecision, TransactionImportLink

MANUAL_DATE_WINDOW = timedelta(days=3)


@dataclass
class Classification:
    decision: str
    fingerprint: str
    match_kind: str | None = None
    matched_transaction_id: int | None = None
    note: str | None = None


class Classifier:
    def __init__(self, session: Session, namespace: str):
        self.session = session
        self.namespace = namespace
        self.consumed: set[int] = set()
        self.seen_ids: set[tuple[int, str]] = set()

    def classify(self, row: ParsedRow, account: Account) -> Classification:
        fp = fingerprint(row.booking_date, row.amount, row.description, row.counterparty)
        if row.amount == 0:
            return Classification(RowDecision.SKIPPED, fp, note="Betrag 0 – nicht übernommen")
        if row.booking_date < account.opening_balance_date:
            return Classification(
                RowDecision.BEFORE_OPENING, fp,
                note="Vor dem Stichtag des Kontos – vermutlich schon im Anfangssaldo enthalten",
            )
        if row.external_id:
            result = self._by_external_id(row, account, fp)
            if result:
                return result
        return self._by_fingerprint(row, account, fp) or self._similar(row, account, fp) or Classification(
            RowDecision.NEW, fp
        )

    def _take(self, tx_id: int) -> int:
        self.consumed.add(tx_id)
        return tx_id

    def _by_external_id(self, row: ParsedRow, account: Account, fp: str) -> Classification | None:
        key = (account.id, row.external_id)
        if key in self.seen_ids:
            return Classification(
                RowDecision.AMBIGUOUS, fp, MatchKind.EXTERNAL_ID,
                note="Bank-ID kommt in der Datei mehrfach vor",
            )
        self.seen_ids.add(key)
        link = self.session.exec(
            select(TransactionImportLink).where(
                TransactionImportLink.account_id == account.id,
                TransactionImportLink.id_namespace == self.namespace,
                TransactionImportLink.external_id == row.external_id,
            )
        ).first()
        if link is None:
            return None
        tx = self.session.get(Transaction, link.transaction_id)
        self._take(tx.id)
        if tx.booking_date == row.booking_date and tx.amount == row.amount:
            return Classification(RowDecision.DUPLICATE, fp, MatchKind.EXTERNAL_ID, tx.id)
        return Classification(
            RowDecision.AMBIGUOUS, fp, MatchKind.EXTERNAL_ID, tx.id,
            note="Gleiche Bank-ID, aber abweichendes Datum oder abweichender Betrag",
        )

    def _other_bank_id(self, tx_id: int, external_id: str | None) -> bool:
        """Buchung trägt nachweislich eine andere Bank-ID → sicher nicht dieselbe."""
        if not external_id:
            return False
        return self.session.exec(
            select(TransactionImportLink.id).where(
                TransactionImportLink.transaction_id == tx_id,
                TransactionImportLink.id_namespace == self.namespace,
                TransactionImportLink.external_id.is_not(None),
                TransactionImportLink.external_id != external_id,
            )
        ).first() is not None

    def _by_fingerprint(self, row: ParsedRow, account: Account, fp: str) -> Classification | None:
        tx_ids = self.session.exec(
            select(TransactionImportLink.transaction_id)
            .where(TransactionImportLink.account_id == account.id, TransactionImportLink.fingerprint == fp)
            .distinct()
            .order_by(TransactionImportLink.transaction_id)
        )
        for tx_id in tx_ids:
            if tx_id not in self.consumed and not self._other_bank_id(tx_id, row.external_id):
                return Classification(
                    RowDecision.AMBIGUOUS, fp, MatchKind.FINGERPRINT, self._take(tx_id),
                    note="Gleiche Buchung wurde bereits importiert (Text, Betrag und Tag gleich)",
                )
        return None

    def _similar(self, row: ParsedRow, account: Account, fp: str) -> Classification | None:
        candidates = list(
            self.session.exec(
                select(Transaction).where(
                    Transaction.account_id == account.id,
                    Transaction.amount == row.amount,
                    Transaction.booking_date.between(
                        row.booking_date - MANUAL_DATE_WINDOW, row.booking_date + MANUAL_DATE_WINDOW
                    ),
                )
            )
        )
        if not candidates:
            return None
        linked = set(
            self.session.exec(
                select(TransactionImportLink.transaction_id).where(
                    TransactionImportLink.transaction_id.in_([tx.id for tx in candidates])
                )
            )
        )
        best = None
        for tx in candidates:
            if tx.id in self.consumed or self._other_bank_id(tx.id, row.external_id):
                continue
            if tx.id in linked and tx.booking_date != row.booking_date:
                continue  # importierte Buchungen: nur gleicher Tag
            distance = abs((tx.booking_date - row.booking_date).days)
            if best is None or (distance, tx.id) < best[0]:
                best = ((distance, tx.id), tx)
        if best is None:
            return None
        tx = best[1]
        origin = "importierte" if tx.id in linked else "manuell erfasste"
        return Classification(
            RowDecision.AMBIGUOUS, fp, MatchKind.SIMILAR, self._take(tx.id),
            note=f"Mögliche Dublette: {origin} Buchung mit gleichem Betrag am {tx.booking_date:%d.%m.%Y}",
        )
