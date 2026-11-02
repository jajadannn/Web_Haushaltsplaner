import codecs
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.imports import (
    ArchiveState,
    BatchSource,
    BatchStatus,
    ImportFormat,
    MatchKind,
    RowDecision,
    RowResolution,
    SignMode,
)
from app.schemas.common import Money, Name, PatchModel, ReadModel

COLUMN_KEYS = {
    "booking_date", "value_date", "amount", "debit", "credit", "indicator", "description",
    "counterparty", "counterparty_iban", "external_id", "own_account", "currency", "status",
}
Separator = Annotated[str, Field(max_length=1)]


def _check_column_map(column_map: dict) -> dict:
    unknown = set(column_map) - COLUMN_KEYS
    if unknown:
        raise ValueError(f"Unbekannte Felder in column_map: {sorted(unknown)}")
    for key, spec in column_map.items():
        ok = (
            (isinstance(spec, str) and spec)
            or (isinstance(spec, list) and spec and all(isinstance(s, str) and s for s in spec))
            or (
                isinstance(spec, dict)
                and set(spec) <= {"debit", "credit"}
                and spec
                and all(isinstance(s, str) and s for s in spec.values())
            )
        )
        if not ok:
            raise ValueError(f"column_map.{key}: Spaltenname, Liste oder {{debit, credit}} erwartet")
    return column_map


def _valid_encoding(value: str | None) -> str | None:
    if value is not None:
        try:
            codecs.lookup(value)
        except LookupError as exc:
            raise ValueError(f"Unbekannte Zeichenkodierung {value}") from exc
    return value


def _valid_date_format(value: str | None) -> str | None:
    if value is not None and ("%" not in value or date(2026, 1, 31).strftime(value) == value):
        raise ValueError("Datumsformat im strftime-Stil angeben, z. B. %d.%m.%Y")
    return value


class CsvSettings(BaseModel):
    delimiter: Separator = ";"
    encoding: Annotated[str, Field(max_length=20)] = "utf-8"
    skip_rows: Annotated[int, Field(ge=0, le=50)] = 0
    column_map: dict = Field(default_factory=dict)
    date_format: Annotated[str, Field(max_length=20)] = "%d.%m.%Y"
    decimal_sep: Separator = ","
    thousands_sep: Separator = "."
    sign_mode: SignMode = SignMode.SIGNED
    debit_indicators: list[Annotated[str, Field(max_length=20)]] = Field(default_factory=list)
    pending_values: list[Annotated[str, Field(max_length=50)]] = Field(default_factory=list)

    @field_validator("encoding")
    @classmethod
    def _encoding(cls, value: str) -> str:
        return _valid_encoding(value)

    @field_validator("date_format")
    @classmethod
    def _date_format(cls, value: str) -> str:
        return _valid_date_format(value)

    @field_validator("column_map")
    @classmethod
    def _column_map(cls, value: dict) -> dict:
        return _check_column_map(value)


def check_csv_settings(fmt: str, data: CsvSettings | dict) -> None:
    if fmt != ImportFormat.CSV:
        return
    get = data.get if isinstance(data, dict) else lambda k: getattr(data, k)
    cmap, mode = get("column_map") or {}, get("sign_mode")
    needed = {"booking_date"} | {
        SignMode.SIGNED: {"amount"},
        SignMode.DEBIT_CREDIT_COLUMNS: {"debit", "credit"},
        SignMode.INDICATOR_COLUMN: {"amount", "indicator"},
    }[mode]
    missing = sorted(needed - set(cmap))
    if missing:
        raise ValueError(f"column_map braucht für sign_mode={mode}: {missing}")
    if mode == SignMode.INDICATOR_COLUMN and not get("debit_indicators"):
        raise ValueError("debit_indicators angeben (z. B. ['S'])")
    if get("decimal_sep") == get("thousands_sep"):
        raise ValueError("Dezimal- und Tausendertrennzeichen müssen sich unterscheiden")


class ImportProfileCreate(CsvSettings):
    model_config = ConfigDict(extra="forbid")
    name: Name
    institution_id: int
    format: ImportFormat

    @model_validator(mode="after")
    def _consistent(self):
        check_csv_settings(self.format, self)
        return self


class ImportProfileUpdate(PatchModel):
    """Format und Bank sind fest; Änderungen an Leseregeln erhöhen die Profilversion."""

    _not_nullable = frozenset(
        {"name", "delimiter", "encoding", "skip_rows", "column_map", "date_format", "decimal_sep",
         "thousands_sep", "sign_mode", "debit_indicators", "pending_values"}
    )
    name: Name | None = None
    delimiter: Separator | None = None
    encoding: Annotated[str, Field(max_length=20)] | None = None
    skip_rows: Annotated[int, Field(ge=0, le=50)] | None = None
    column_map: dict | None = None
    date_format: Annotated[str, Field(max_length=20)] | None = None
    decimal_sep: Separator | None = None
    thousands_sep: Separator | None = None
    sign_mode: SignMode | None = None
    debit_indicators: list[Annotated[str, Field(max_length=20)]] | None = None
    pending_values: list[Annotated[str, Field(max_length=50)]] | None = None

    @field_validator("encoding")
    @classmethod
    def _encoding(cls, value: str | None) -> str | None:
        return _valid_encoding(value)

    @field_validator("date_format")
    @classmethod
    def _date_format(cls, value: str | None) -> str | None:
        return _valid_date_format(value)

    @field_validator("column_map")
    @classmethod
    def _column_map(cls, value: dict | None) -> dict | None:
        return None if value is None else _check_column_map(value)


class ImportProfileRead(ReadModel):
    id: int
    name: str
    institution_id: int
    format: ImportFormat
    version: int
    delimiter: str
    encoding: str
    skip_rows: int
    column_map: dict
    date_format: str
    decimal_sep: str
    thousands_sep: str
    sign_mode: SignMode
    debit_indicators: list[str]
    pending_values: list[str]
    created_at: datetime
    updated_at: datetime


class WatchFolderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subdir: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)]
    import_profile_id: int
    account_id: int | None = None


class WatchFolderRead(ReadModel):
    id: int
    subdir: str
    import_profile_id: int
    account_id: int | None
    path: str | None = None
    created_at: datetime


class ImportBatchRead(ReadModel):
    id: int
    import_profile_id: int
    account_id: int | None
    original_filename: str
    source: BatchSource
    status: BatchStatus
    attempt: int
    errors: list
    archive_state: ArchiveState
    rows_total: int
    rows_new: int
    rows_duplicate: int
    rows_review: int
    rows_skipped: int
    rows_pending: int
    profile_version: int
    parser_version: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    already_imported: bool = False


class ImportRowRead(ReadModel):
    id: int
    row_no: int
    account_id: int
    booking_date: date
    value_date: date | None
    amount: Money
    description: str
    counterparty: str | None
    counterparty_iban: str | None
    external_id: str | None
    decision: RowDecision
    match_kind: MatchKind | None
    resolution: RowResolution | None
    note: str | None
    matched_transaction_id: int | None
    created_transaction_id: int | None
    suggested_loan_entry_id: int | None
    raw: dict


class RowResolve(BaseModel):
    """Entscheidung für Zeilen: per `row_ids` oder für alle offenen Zeilen einer Art,
    z. B. `{"decision": "ambiguous", "match_kind": "fingerprint", "action": "duplicate"}`."""

    model_config = ConfigDict(extra="forbid")
    action: RowResolution
    row_ids: list[int] | None = None
    decision: Literal["ambiguous", "before_opening"] | None = None
    match_kind: MatchKind | None = None
    matched_transaction_id: int | None = None


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int | None = None
