from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Geldbeträge: exakt 2 Nachkommastellen, kein NaN/Inf; JSON-Ausgabe als String ("1234.56")
Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2, allow_inf_nan=False)]

Name = Annotated[str, Field(min_length=1, max_length=100)]


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PatchModel(BaseModel):
    """Basis für PATCH-Schemas: Nur gesetzte Felder werden übernommen (exclude_unset)."""

    model_config = ConfigDict(extra="forbid")

    # Felder, die nicht bewusst auf null gesetzt werden dürfen
    _not_nullable: frozenset[str] = frozenset()

    def changes(self) -> dict:
        data = self.model_dump(exclude_unset=True)
        nulled = sorted(k for k, v in data.items() if v is None and k in self._not_nullable)
        if nulled:
            from app.errors import Invalid

            raise Invalid("Felder dürfen nicht null sein", details={"fields": nulled})
        return data
