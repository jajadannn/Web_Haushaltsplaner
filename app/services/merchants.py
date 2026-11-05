"""Anbieter und Verträge hinter wechselnden Buchungstexten (Idee 09).

Zuordnung einer Buchung über bestätigte Merkmale in fester Reihenfolge: IBAN, Referenz im
Verwendungszweck, Name der Gegenpartei. Ein Vertrag wird über seine Referenz erkannt. Die
Originaltexte der Buchungen bleiben unverändert. Zahlungsdienstleister (PayPal …) gelten nur
zusammen mit einer Vertragsreferenz als bestimmter Vertrag.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlmodel import Session, select

from app.errors import Invalid
from app.models import AliasMatch, Contract, Merchant, MerchantAlias, MerchantKind, Transaction, User
from app.services.common import flush_or_conflict, get_owned
from app.services.iban import normalize_iban

_UNIQUE = {
    "uq_merchant_user_id_name": "Ein Anbieter mit diesem Namen existiert bereits",
    "uq_merchant_alias_user_id_match_type_value": "Dieses Merkmal ist bereits einem Anbieter zugeordnet",
}


def normalize(match_type: str, value: str) -> str:
    if match_type == AliasMatch.IBAN:
        return normalize_iban(value)
    return " ".join(value.casefold().split())


def _contains(text: str, reference: str) -> bool:
    """Referenz als ganzes Merkmal im Text – „1234“ trifft nicht „12345“."""
    return re.search(rf"(?<![0-9a-z]){re.escape(reference)}(?![0-9a-z])", text) is not None


@dataclass
class Resolved:
    merchant: Merchant
    contract: Contract | None


class Resolver:
    """Lädt die Merkmale eines Profils einmal und ordnet viele Buchungen schnell zu."""

    def __init__(self, session: Session, user_id: int):
        self.merchants = {m.id: m for m in session.exec(select(Merchant).where(Merchant.user_id == user_id))}
        self.contracts = list(session.exec(select(Contract).where(Contract.user_id == user_id)))
        self.aliases: dict[tuple[str, str], MerchantAlias] = {
            (a.match_type, a.value): a
            for a in session.exec(select(MerchantAlias).where(MerchantAlias.user_id == user_id))
        }
        self.references = [(a, a.value) for a in self.aliases.values() if a.match_type == AliasMatch.REFERENCE]

    def resolve(self, counterparty: str | None, iban: str | None, description: str | None) -> Resolved | None:
        text = (description or "").casefold()
        references = [a for a, value in self.references if value and _contains(text, value)]
        alias = None
        if iban:
            alias = self.aliases.get((AliasMatch.IBAN, normalize_iban(iban)))
        if alias is None and references:
            # mehrere Referenzen verschiedener Anbieter: mehrdeutig, nicht raten
            if len({a.merchant_id for a in references}) == 1:
                alias = references[0]
        if alias is None and counterparty:
            alias = self.aliases.get((AliasMatch.NAME, normalize(AliasMatch.NAME, counterparty)))
        if alias is None:
            return None
        merchant = self.merchants[alias.merchant_id]
        if alias.contract_id is not None:
            contract_ids = {alias.contract_id}
        else:
            # alle Vertragsmerkmale des Anbieters: Vertragsreferenz und zusätzliche Referenz-Aliasse
            contract_ids = {c.id for c in self.contracts
                            if c.merchant_id == merchant.id and c.reference and _contains(text, c.reference.casefold())}
            contract_ids |= {a.contract_id for a in references
                             if a.merchant_id == merchant.id and a.contract_id is not None}
        contract = next((c for c in self.contracts if c.id in contract_ids), None) if len(contract_ids) == 1 else None
        return Resolved(merchant, contract)

    def group(self, counterparty: str | None, iban: str | None, description: str | None) -> tuple[str, str] | None:
        """(Gruppenschlüssel, Anzeigename) für die Fixkostenerkennung – oder None (unbekannt/unbestimmt)."""
        found = self.resolve(counterparty, iban, description)
        if found is None:
            return None
        if found.contract is not None:
            return f"alias:{found.merchant.id}:{found.contract.id}", found.contract.label
        if found.merchant.kind == MerchantKind.PAYMENT_PROVIDER:
            return "", ""  # Zahlungsdienstleister ohne Vertragsreferenz: nicht zuordenbar
        return f"alias:{found.merchant.id}", found.merchant.name


def merchant_ids(session: Session, user_id: int, txs: Sequence[Transaction]) -> dict[int, int]:
    resolver = Resolver(session, user_id)
    result = {}
    for tx in txs:
        found = resolver.resolve(tx.counterparty, tx.counterparty_iban, tx.description)
        if found is not None:
            result[tx.id] = found.merchant.id
    return result


# --- Verwaltung ----------------------------------------------------------------------------------


def list_merchants(session: Session, user: User) -> list[Merchant]:
    return list(session.exec(select(Merchant).where(Merchant.user_id == user.id).order_by(Merchant.name)))


def get_merchant(session: Session, user: User, merchant_id: int) -> Merchant:
    return get_owned(session, Merchant, merchant_id, user.id, "Anbieter")


def create_merchant(session: Session, user: User, name: str, kind: str = MerchantKind.MERCHANT) -> Merchant:
    merchant = Merchant(user_id=user.id, name=name.strip(), kind=kind)
    session.add(merchant)
    flush_or_conflict(session, _UNIQUE)
    return merchant


def update_merchant(session: Session, merchant: Merchant, changes: dict) -> Merchant:
    for key, value in changes.items():
        setattr(merchant, key, value)
    flush_or_conflict(session, _UNIQUE)
    return merchant


def delete_merchant(session: Session, merchant: Merchant) -> None:
    session.delete(merchant)
    session.flush()


def add_alias(session: Session, user: User, merchant: Merchant, match_type: str, value: str,
              contract_id: int | None = None, confirmed: bool = True, source: str = "user") -> MerchantAlias:
    normalized = normalize(match_type, value)
    if len(normalized) < 2:
        raise Invalid("Merkmal ist zu kurz", code="alias_too_short")
    if contract_id is not None:
        contract = get_owned(session, Contract, contract_id, user.id, "Vertrag")
        if contract.merchant_id != merchant.id:
            raise Invalid("Vertrag gehört zu einem anderen Anbieter", code="contract_mismatch")
    alias = MerchantAlias(user_id=user.id, merchant_id=merchant.id, contract_id=contract_id, match_type=match_type,
                          value=normalized, confirmed=confirmed, source=source)
    session.add(alias)
    flush_or_conflict(session, _UNIQUE)
    return alias


def list_aliases(session: Session, merchant: Merchant) -> list[MerchantAlias]:
    return list(session.exec(select(MerchantAlias).where(MerchantAlias.merchant_id == merchant.id)
                             .order_by(MerchantAlias.match_type, MerchantAlias.value)))


def delete_alias(session: Session, user: User, alias_id: int) -> None:
    session.delete(get_owned(session, MerchantAlias, alias_id, user.id, "Merkmal"))
    session.flush()


def add_contract(session: Session, user: User, merchant: Merchant, label: str, reference: str | None) -> Contract:
    if reference is not None:
        reference = reference.strip()
        if len(reference) < 3:
            raise Invalid("Referenz ist zu kurz", code="reference_too_short")
    contract = Contract(user_id=user.id, merchant_id=merchant.id, label=label.strip(), reference=reference)
    session.add(contract)
    session.flush()
    if reference:
        add_alias(session, user, merchant, AliasMatch.REFERENCE, reference, contract_id=contract.id)
    return contract


def list_contracts(session: Session, merchant: Merchant) -> list[Contract]:
    return list(session.exec(select(Contract).where(Contract.merchant_id == merchant.id).order_by(Contract.label)))


def delete_contract(session: Session, user: User, contract_id: int) -> None:
    session.delete(get_owned(session, Contract, contract_id, user.id, "Vertrag"))
    session.flush()


_REF = re.compile(r"[A-Za-z0-9-]{4,}")
