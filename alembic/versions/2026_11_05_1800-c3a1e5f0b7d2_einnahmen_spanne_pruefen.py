"""Erwartete Einnahmen: Betragsspanne in der Datenbank prüfen (Prüfbericht KI N28).

Revision ID: c3a1e5f0b7d2
Revises: 8e02e866d112
Create Date: 2026-11-05 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a1e5f0b7d2"
down_revision: str | Sequence[str] | None = "8e02e866d112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # bereits gespeicherte umgekehrte Spannen richtigherum drehen, statt die Migration scheitern zu lassen
    op.execute(
        "UPDATE expected_income SET amount_min = amount_max, amount_max = amount_min "
        "WHERE amount_min IS NOT NULL AND amount_max IS NOT NULL AND amount_min > amount_max"
    )
    op.create_check_constraint(
        op.f("ck_expected_income_amount_range"), "expected_income",
        "amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_expected_income_amount_range"), "expected_income", type_="check")
