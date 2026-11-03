from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.config import get_settings
from app.deps import CurrentUser, SessionDep
from app.models import ReviewStatus
from app.schemas.rule import (
    AiRetryResult,
    AiStatus,
    ApplyResult,
    BulkConfirm,
    ConfirmAllResult,
    ReviewConfirm,
    ReviewPage,
    RuleCreate,
    RulePreview,
    RulePreviewRequest,
    RuleRead,
    RuleSuggestion,
    RuleUpdate,
)
from app.schemas.transaction import TransactionRead
from app.services import ai_review, review, rules
from app.services.categorization import RuleSet, apply_rules
from app.services.transactions import get_transaction

router = APIRouter()


# --- Regeln -------------------------------------------------------------------


@router.get("/mapping-rules", response_model=list[RuleRead], tags=["Regeln"])
def list_rules(session: SessionDep, user: CurrentUser):
    """In Prüfreihenfolge: kleinste `priority` zuerst, bei Gleichstand die ältere Regel."""
    return rules.list_rules(session, user)


@router.post("/mapping-rules", response_model=RuleRead, status_code=201, tags=["Regeln"])
def create_rule(data: RuleCreate, session: SessionDep, user: CurrentUser):
    rule = rules.create_rule(session, user, data)
    session.commit()
    return rule


@router.post("/mapping-rules/preview", response_model=RulePreview, tags=["Regeln"])
def preview(data: RulePreviewRequest, session: SessionDep, user: CurrentUser):
    """Welche Regeln treffen auf einen Text bzw. eine Buchung zu – und welche gewinnt?"""
    description, counterparty = data.description, data.counterparty
    if data.transaction_id is not None:
        tx = get_transaction(session, user, data.transaction_id)
        description, counterparty = tx.description, tx.counterparty
    ruleset = RuleSet(session, user.id)
    return {
        "matching": ruleset.matching(description, counterparty),
        "winner": ruleset.winner(description, counterparty),
    }


@router.post("/mapping-rules/apply", response_model=ApplyResult, tags=["Regeln"])
def apply(session: SessionDep, user: CurrentUser, dry_run: bool = True):
    """Regeln rückwirkend anwenden. Standard ist die Vorschau (`dry_run=true`) mit
    Trefferzahl; manuell oder über Kredite kategorisierte Buchungen bleiben unberührt."""
    result = apply_rules(session, user, dry_run=dry_run)
    if not dry_run:
        session.commit()
    return result


@router.get("/mapping-rules/{rule_id}", response_model=RuleRead, tags=["Regeln"])
def get_rule(rule_id: int, session: SessionDep, user: CurrentUser):
    return rules.get_rule(session, user, rule_id)


@router.patch("/mapping-rules/{rule_id}", response_model=RuleRead, tags=["Regeln"])
def update_rule(rule_id: int, data: RuleUpdate, session: SessionDep, user: CurrentUser):
    rule = rules.update_rule(session, user, rules.get_rule(session, user, rule_id), data.changes())
    session.commit()
    return rule


@router.delete("/mapping-rules/{rule_id}", status_code=204, tags=["Regeln"])
def delete_rule(rule_id: int, session: SessionDep, user: CurrentUser):
    rules.delete_rule(session, rules.get_rule(session, user, rule_id))
    session.commit()
    return Response(status_code=204)


# --- Prüfliste ----------------------------------------------------------------


@router.get("/review", response_model=ReviewPage, tags=["Prüfliste"])
def list_review(
    session: SessionDep,
    user: CurrentUser,
    status: ReviewStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Ungeklärte und automatisch kategorisierte Buchungen, inkl. vorgeschlagener Kreditraten."""
    return review.list_review(session, user, status, limit, offset)


@router.post("/review/bulk-confirm", tags=["Prüfliste"])
def bulk_confirm(data: BulkConfirm, session: SessionDep, user: CurrentUser):
    """Mehrere Buchungen bestätigen – alles oder nichts."""
    count = review.bulk_confirm(session, user, data.transaction_ids, data)
    session.commit()
    return {"confirmed": count}


@router.post("/review/confirm-all", response_model=ConfirmAllResult, tags=["Prüfliste"])
def confirm_all(session: SessionDep, user: CurrentUser):
    """Alle automatisch zugeordneten Buchungen (Regel/KI) mit der vorgeschlagenen Kategorie bestätigen."""
    result = review.confirm_all_suggestions(session, user)
    session.commit()
    return result


@router.get("/review/ai", response_model=AiStatus, tags=["Prüfliste"])
def ai_status(session: SessionDep, user: CurrentUser):
    """Ob die lokale KI eingerichtet und erreichbar ist und wie viele Buchungen sie noch prüft."""
    settings = get_settings()
    enabled = bool(settings.ai_url)
    return AiStatus(
        enabled=enabled,
        model=settings.ai_model if enabled else None,
        reachable=ai_review.reachable() if enabled else None,
        pending=ai_review.pending_count(session, user),
    )


@router.post("/review/ai/retry", response_model=AiRetryResult, tags=["Prüfliste"])
def ai_retry(session: SessionDep, user: CurrentUser):
    """Offene Buchungen, zu denen die KI nichts gefunden hat, erneut vorlegen."""
    queued = ai_review.retry(session, user)
    session.commit()
    return AiRetryResult(queued=queued)


@router.post("/review/{transaction_id}/confirm", response_model=TransactionRead, tags=["Prüfliste"])
def confirm(transaction_id: int, data: ReviewConfirm, session: SessionDep, user: CurrentUser):
    tx = review.confirm(session, user, get_transaction(session, user, transaction_id), data)
    session.commit()
    return tx


@router.post("/review/{transaction_id}/suggest-rule", response_model=RuleSuggestion, tags=["Prüfliste"])
def suggest_rule(transaction_id: int, session: SessionDep, user: CurrentUser):
    """Regelvorschlag aus einer Buchung (ohne Ziffern/Referenzen) – zum Bearbeiten, nicht gespeichert."""
    return review.suggest_rule(session, user, get_transaction(session, user, transaction_id))
