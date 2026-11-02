"""Regeln: Kategorien automatisch zuordnen, ohne manuelle Entscheidungen zu überschreiben.

- `contains` (Standard): Teiltext, ohne Groß-/Kleinschreibung (außer `case_sensitive`).
- `regex`: regulärer Ausdruck über das Paket `regex` mit hartem Zeitlimit und begrenzter
  Textlänge – Kompilieren allein schützt nicht vor extrem langsamen Mustern.
- Bei mehreren Treffern gewinnt die Regel mit der kleinsten (priority, id).
- Angewendet wird nur auf reguläre, ungeteilte Buchungen ohne manuelle oder Kredit-Kategorie.
"""

import logging
import re
from dataclasses import dataclass

import regex
from sqlalchemy import not_
from sqlmodel import Session, exists, select

from app.errors import Invalid
from app.models import (
    Category,
    CategorySource,
    MappingRule,
    MatchField,
    MatchType,
    ReviewStatus,
    Transaction,
    TransactionKind,
    TransactionSplit,
    User,
)

log = logging.getLogger("finanzplaner.rules")
REGEX_TIMEOUT_SECONDS = 0.05
MAX_TEXT_LENGTH = 1000


def compile_pattern(pattern: str, match_type: str, case_sensitive: bool):
    if match_type != MatchType.REGEX:
        return None
    try:
        return regex.compile(pattern, 0 if case_sensitive else regex.IGNORECASE)
    except regex.error as exc:
        raise Invalid(f"Ungültiger regulärer Ausdruck: {exc}", code="invalid_regex") from exc


def rule_text(rule: MappingRule, description: str | None, counterparty: str | None) -> str:
    parts = {
        MatchField.DESCRIPTION: [description],
        MatchField.COUNTERPARTY: [counterparty],
        MatchField.ANY: [description, counterparty],
    }[rule.match_field]
    return " ".join(p for p in parts if p)[:MAX_TEXT_LENGTH]


@dataclass
class CompiledRule:
    rule: MappingRule
    compiled: object | None

    def matches(self, description: str | None, counterparty: str | None) -> bool:
        text = rule_text(self.rule, description, counterparty)
        if not text:
            return False
        if self.compiled is None:
            if self.rule.case_sensitive:
                return self.rule.pattern in text
            return self.rule.pattern.casefold() in text.casefold()
        try:
            return self.compiled.search(text, timeout=REGEX_TIMEOUT_SECONDS) is not None
        except TimeoutError:
            log.warning("Regel %s: Zeitlimit überschritten – als kein Treffer gewertet", self.rule.id)
            return False


class RuleSet:
    """Aktive Regeln eines Profils mit aktiver Zielkategorie, in Prüfreihenfolge."""

    def __init__(self, session: Session, user_id: int, rules: list[MappingRule] | None = None):
        if rules is None:
            rules = list(
                session.exec(
                    select(MappingRule)
                    .join(Category, Category.id == MappingRule.target_category_id)
                    .where(MappingRule.user_id == user_id, MappingRule.active, Category.active)
                    .order_by(MappingRule.priority, MappingRule.id)
                )
            )
        self.rules = [
            CompiledRule(r, compile_pattern(r.pattern, r.match_type, r.case_sensitive)) for r in rules
        ]

    def matching(self, description: str | None, counterparty: str | None) -> list[MappingRule]:
        return [c.rule for c in self.rules if c.matches(description, counterparty)]

    def winner(self, description: str | None, counterparty: str | None) -> MappingRule | None:
        return next((c.rule for c in self.rules if c.matches(description, counterparty)), None)


def _apply(tx: Transaction, rule: MappingRule) -> None:
    tx.category_id = rule.target_category_id
    tx.category_source = CategorySource.RULE
    tx.applied_rule_id = rule.id
    tx.review_status = ReviewStatus.AUTO_CATEGORIZED


def categorize_new(session: Session, user: User, transactions: list[Transaction]) -> int:
    """Für frisch importierte Buchungen; liefert die Anzahl kategorisierter Buchungen."""
    rules = RuleSet(session, user.id)
    count = 0
    for tx in transactions:
        if tx.kind != TransactionKind.REGULAR or tx.category_source != CategorySource.NONE or tx.splits:
            continue
        rule = rules.winner(tx.description, tx.counterparty)
        if rule is not None:
            _apply(tx, rule)
            count += 1
    session.flush()
    return count


def candidates_query(user: User):
    """Buchungen, die Regeln (neu) zuordnen dürfen: nie manuell oder über Kredite kategorisiert."""
    return select(Transaction).where(
        Transaction.user_id == user.id,
        Transaction.kind == TransactionKind.REGULAR,
        Transaction.category_source.in_([CategorySource.NONE, CategorySource.RULE]),
        Transaction.excluded_at.is_(None),
        not_(exists().where(TransactionSplit.transaction_id == Transaction.id)),
    )


def apply_rules(session: Session, user: User, *, dry_run: bool, sample_size: int = 20) -> dict:
    """Rückwirkend anwenden: zuerst als Vorschau (dry_run), dann atomar."""
    rules = RuleSet(session, user.id)
    changes = []
    for tx in session.exec(candidates_query(user).order_by(Transaction.booking_date.desc(), Transaction.id.desc())):
        rule = rules.winner(tx.description, tx.counterparty)
        if rule is None or (tx.category_id == rule.target_category_id and tx.applied_rule_id == rule.id):
            continue
        changes.append((tx, rule))
    sample = [
        {
            "transaction_id": tx.id,
            "booking_date": tx.booking_date,
            "description": tx.description,
            "old_category_id": tx.category_id,
            "new_category_id": rule.target_category_id,
            "rule_id": rule.id,
        }
        for tx, rule in changes[:sample_size]
    ]
    if not dry_run:
        for tx, rule in changes:
            _apply(tx, rule)
        session.flush()
    return {"dry_run": dry_run, "affected": len(changes), "sample": sample}


_NOISE = re.compile(
    r"\b(EREF|KREF|MREF|CRED|SVWZ|ABWA|ABWE|IBAN|BIC)\+\S*|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b|\S*\d\S*",
    re.IGNORECASE,
)


def suggest_pattern(description: str, counterparty: str | None) -> tuple[str, str]:
    """Vorschlag (Muster, Feld) aus einer Buchung – ohne Ziffern, Datumsangaben und Referenzen."""
    source, field = (counterparty, MatchField.COUNTERPARTY) if counterparty else (description, MatchField.DESCRIPTION)
    words = [w for w in _NOISE.sub(" ", source).split() if len(w) > 1][:4]
    pattern = " ".join(words)
    if len(pattern) < 3:
        words = [w for w in _NOISE.sub(" ", description).split() if len(w) > 1][:4]
        pattern, field = " ".join(words), MatchField.DESCRIPTION
    return pattern, field
