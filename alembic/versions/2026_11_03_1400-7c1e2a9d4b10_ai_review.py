"""Lokale KI in der Prüfliste: Herkunft „ai“, Prüfzeitpunkt und Begründung

Revision ID: 7c1e2a9d4b10
Revises: 28ff4a7746dc
Create Date: 2026-11-03 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c1e2a9d4b10"
down_revision: str | Sequence[str] | None = "28ff4a7746dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CK = "ck_transaction_category_source"


def upgrade() -> None:
    op.add_column("transaction", sa.Column("ai_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transaction", sa.Column("ai_note", sa.String(length=300), nullable=True))
    op.drop_constraint(op.f(CK), "transaction", type_="check")
    op.create_check_constraint(op.f(CK), "transaction", "category_source IN ('manual', 'rule', 'loan', 'ai', 'none')")
    # Offene Buchungen ohne Kategorie, die die KI noch nicht gesehen hat (Warteschlange des Workers)
    op.create_index(
        "ix_transaction_ai_pending",
        "transaction",
        ["id"],
        postgresql_where=sa.text("ai_checked_at IS NULL AND review_status = 'needs_review' AND category_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_transaction_ai_pending", table_name="transaction")
    op.execute(
        "UPDATE transaction SET category_source = 'none', category_id = NULL, review_status = 'needs_review' "
        "WHERE category_source = 'ai' AND review_status <> 'confirmed'"
    )
    op.execute("UPDATE transaction SET category_source = 'manual' WHERE category_source = 'ai'")
    op.drop_constraint(op.f(CK), "transaction", type_="check")
    op.create_check_constraint(op.f(CK), "transaction", "category_source IN ('manual', 'rule', 'loan', 'none')")
    op.drop_column("transaction", "ai_note")
    op.drop_column("transaction", "ai_checked_at")
