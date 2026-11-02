from datetime import date

from pydantic import BaseModel, Field

from app.models.transaction import ReviewStatus, TransactionKind, TransactionSource
from app.schemas.common import Money


class TransactionFilter(BaseModel):
    """Gemeinsame Filter für Buchungsliste und Export (alle Datumsgrenzen inklusive).

    Bewusst ohne extra="forbid": Als Query-Modell teilt es sich die Parameter mit
    limit/offset des jeweiligen Endpunkts."""

    date_from: date | None = None
    date_to: date | None = None
    account_ids: list[int] = Field(default_factory=list)
    institution_id: int | None = None
    category_id: int | None = None
    include_subcategories: bool = True
    uncategorized: bool | None = Field(
        default=None, description="true: nur Buchungen ohne Kategorie (Transfers ausgenommen)"
    )
    kind: TransactionKind | None = None
    review_status: ReviewStatus | None = None
    source: TransactionSource | None = None
    search: str | None = Field(default=None, max_length=200)
    amount_min: Money | None = None
    amount_max: Money | None = None
    include_excluded: bool = False
