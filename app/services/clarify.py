"""Klären statt raten (Phase 4): Konsistenzhinweise (Idee 19) und gezielte Rückfragen (Idee 20).

- Konsistenz: Buchungen derselben Gegenpartei wurden in verschiedene Kategorien eingeordnet, oder
  zwei Kategorien heißen fast gleich. Nur Hinweise – übernehmen heißt „ist so gewollt“, es wird
  nichts zusammengeführt oder umgeschrieben.
- Rückfragen: Ein bekannter Anbieter bucht unter mehreren Vertragsreferenzen. Eine kurze Frage
  („getrennte Verträge oder einer?“) klärt das für alle betroffenen Buchungen; die Antwort wird
  als Verträge/Merkmale beim Anbieter gespeichert. Höchstens drei offene Fragen gleichzeitig.
"""

import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlmodel import Session, select

from app.errors import Invalid
from app.models import (
    AliasMatch,
    Category,
    CategorySource,
    Contract,
    Merchant,
    ReviewStatus,
    Suggestion,
    SuggestionKind,
    SuggestionStatus,
    Transaction,
    TransactionKind,
    User,
)
from app.services import analysis, merchants, suggestions
from app.services.recurring import _REFERENCE, normalize_name
from app.services.suggestions import Found, Handler

MAX_OPEN_QUESTIONS = 3


# --- 19 Konsistenz -------------------------------------------------------------------------------


def detect_consistency(session: Session, user: User, today: date) -> list[Found]:
    names = {c.id: c.name for c in session.exec(select(Category).where(Category.user_id == user.id))}
    txs = session.exec(select(Transaction).where(
        Transaction.user_id == user.id, Transaction.review_status == ReviewStatus.CONFIRMED,
        Transaction.category_source == CategorySource.MANUAL, Transaction.kind == TransactionKind.REGULAR,
        Transaction.category_id.is_not(None), Transaction.excluded_at.is_(None),
        Transaction.booking_date >= today - timedelta(days=400),
    )).all()
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for tx in txs:
        key = normalize_name(tx.counterparty or "")
        if len(key) >= 3 and not tx.splits:
            groups[key].append(tx)
    found = []
    for key, items in groups.items():
        counts = Counter(t.category_id for t in items)
        if len(items) < 3 or len(counts) < 2:
            continue
        found.append(Found(
            fingerprint=f"mixed:{key}|{','.join(str(c) for c in sorted(counts))}",
            payload={"type": "mixed_categories", "counterparty": items[-1].counterparty,
                     "category_ids": sorted(counts),
                     "counts": {names.get(c, str(c)): n for c, n in counts.most_common()}},
            evidence={"transactions": [t.id for t in items]},
            reason=f"„{items[-1].counterparty}“ wurde unterschiedlich eingeordnet: "
                   + ", ".join(f"{n}× {names.get(c, c)}" for c, n in counts.most_common()) + ". Absichtlich?",
        ))
    by_norm: dict[str, list[int]] = defaultdict(list)
    for cid, name in names.items():
        by_norm[re.sub(r"[^a-zäöüß]", "", name.casefold())].append(cid)
    for norm, ids in by_norm.items():
        if len(ids) > 1 and norm:
            found.append(Found(
                fingerprint=f"similar:{norm}|{','.join(map(str, sorted(ids)))}",
                payload={"type": "similar_categories", "category_ids": sorted(ids),
                         "names": [names[i] for i in sorted(ids)]},
                evidence={}, reason="Diese Kategorien heißen fast gleich: " + " / ".join(names[i] for i in sorted(ids)),
            ))
    return found


suggestions.register(SuggestionKind.CONSISTENCY, Handler(
    validate=lambda session, user, s: None,
    apply=lambda session, user, s, overrides, actor: ("note", None),  # „gewollt“ – nichts ändern
))


def refresh_consistency(session: Session, user: User, today: date) -> dict[str, int]:
    return suggestions.sync(session, user, SuggestionKind.CONSISTENCY, detect_consistency(session, user, today),
                            "consistency-v1")


# --- 20 Rückfragen -------------------------------------------------------------------------------


def detect_questions(session: Session, user: User, today: date) -> list[Found]:
    resolver = merchants.Resolver(session, user.id)
    txs = session.exec(select(Transaction).where(
        Transaction.user_id == user.id, Transaction.amount < 0, Transaction.excluded_at.is_(None),
        Transaction.booking_date >= today - timedelta(days=400),
    )).all()
    refs: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for tx in txs:
        found = resolver.resolve(tx.counterparty, tx.counterparty_iban, tx.description)
        if found is None or found.contract is not None:
            continue
        match = _REFERENCE.search(tx.description or "")
        if match:
            refs[found.merchant.id][match.group(1)].append(tx.id)
    result = []
    for merchant_id, by_ref in refs.items():
        if len(by_ref) < 2 or sum(len(v) for v in by_ref.values()) < 3:
            continue
        merchant = resolver.merchants[merchant_id]
        references = sorted(by_ref)
        result.append(Found(
            fingerprint=f"refs:{merchant_id}|{'|'.join(r.casefold() for r in references)}",
            payload={
                "type": "contract_split", "merchant_id": merchant_id, "merchant": merchant.name,
                "references": references,
                "question": f"{merchant.name} bucht unter {len(references)} Referenzen ({', '.join(references)}). "
                            "Sind das getrennte Verträge?",
                "options": [{"value": "separate", "label": "Ja, getrennte Verträge"},
                            {"value": "same", "label": "Nein, ein Vertrag"}],
            },
            evidence={"transactions": {r: ids for r, ids in by_ref.items()}},
            reason=f"Die Antwort ordnet {sum(len(v) for v in by_ref.values())} Buchungen zu.",
        ))
    return result[:MAX_OPEN_QUESTIONS]


def _answer(session: Session, user: User, suggestion: Suggestion, overrides: dict, actor: str):
    answer = overrides.get("answer")
    if answer not in ("separate", "same"):
        raise Invalid("Bitte eine Antwort wählen (separate oder same)", code="answer_required")
    merchant = merchants.get_merchant(session, user, suggestion.payload["merchant_id"])
    references = suggestion.payload["references"]
    if answer == "separate":
        for ref in references:
            merchants.add_contract(session, user, merchant, f"{merchant.name} {ref}", ref)
        return "merchant", merchant.id
    contract = merchants.add_contract(session, user, merchant, merchant.name, references[0])
    for ref in references[1:]:
        merchants.add_alias(session, user, merchant, AliasMatch.REFERENCE, ref, contract_id=contract.id)
    return "contract", contract.id


def _open_questions(session: Session, user: User) -> int:
    return len(session.exec(select(Suggestion.id).where(
        Suggestion.user_id == user.id, Suggestion.kind == SuggestionKind.QUESTION,
        Suggestion.status == SuggestionStatus.OPEN)).all())


suggestions.register(SuggestionKind.QUESTION, Handler(validate=lambda session, user, s: None, apply=_answer))


def refresh_questions(session: Session, user: User, today: date) -> dict[str, int]:
    return suggestions.sync(session, user, SuggestionKind.QUESTION, detect_questions(session, user, today),
                            "questions-v1")


analysis.register("consistency", refresh_consistency)
analysis.register("questions", refresh_questions)
_ = (Contract, Merchant, _open_questions)
