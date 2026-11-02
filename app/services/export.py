"""Export als CSV (für Tabellenkalkulation) und PDF.

CSV: Semikolon, UTF-8 mit BOM, Dezimalkomma, Datum TT.MM.JJJJ – öffnet sich in einer
deutschen Tabellenkalkulation direkt richtig. Textzellen, die mit = + - @ Tab oder CR
beginnen, werden mit einem Apostroph entschärft (CSV-/Formel-Injection); normales
Quoting allein reicht dafür nicht. Split-Buchungen erscheinen als eigene Zeilen.
"""

import csv
import io
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlmodel import Session, select

from app.models import Account, Category, Loan, LoanScheduleEntry, Transaction, User
from app.schemas.filters import TransactionFilter
from app.services import reports
from app.services.transactions import category_with_descendants, filtered_query

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
REVIEW_LABELS = {"needs_review": "offen", "auto_categorized": "automatisch", "confirmed": "bestätigt"}
SOURCE_LABELS = {"manual": "manuell", "import": "Import", "loan": "Kredit"}
BATCH_SIZE = 500


def safe_text(value: str | None) -> str:
    text = value or ""
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def plain_money(value: Decimal) -> str:
    """Zahl ohne Tausenderpunkt – bleibt in Tabellenkalkulationen eine Zahl."""
    return f"{value:.2f}".replace(".", ",")


def _csv_line(values: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";", lineterminator="\r\n").writerow(values)
    return buffer.getvalue()


TRANSACTION_HEADER = [
    "Buchungsdatum", "Wertstellung", "Konto", "Betrag", "Art", "Kategorie", "Gegenpartei",
    "IBAN Gegenpartei", "Verwendungszweck", "Prüfstatus", "Quelle", "Ausgeschlossen", "Buchungs-ID", "Teilzeile",
]


def transactions_csv(session: Session, user: User, filters: TransactionFilter) -> Iterator[str]:
    """Alle gefilterten Buchungen (unabhängig von einer Seitengröße), gestreamt."""
    accounts = {a.id: a.name for a in session.exec(select(Account).where(Account.user_id == user.id))}
    categories = {c.id: c.name for c in session.exec(select(Category).where(Category.user_id == user.id))}
    yield "﻿" + _csv_line(TRANSACTION_HEADER)
    # Mit Kategoriefilter nur die passenden Split-Zeilen – sonst überzeichnete die Summe die Kategorie
    wanted = None
    if filters.category_id is not None:
        wanted = set(
            category_with_descendants(session, user.id, filters.category_id)
            if filters.include_subcategories
            else [filters.category_id]
        )
    query = filtered_query(session, user, filters).order_by(
        Transaction.booking_date.desc(), Transaction.id.desc()
    )
    offset = 0
    while True:
        page = list(session.exec(query.limit(BATCH_SIZE).offset(offset)))
        for tx in page:
            lines = [s for s in tx.splits if wanted is None or s.category_id in wanted] or [None]
            if tx.splits and lines == [None]:
                continue
            for split in lines:
                amount = split.amount if split else tx.amount
                kind = split.kind if split else tx.kind
                category_id = split.category_id if split else tx.category_id
                yield _csv_line(
                    [
                        tx.booking_date.strftime("%d.%m.%Y"),
                        tx.value_date.strftime("%d.%m.%Y") if tx.value_date else "",
                        safe_text(accounts.get(tx.account_id)),
                        plain_money(amount),
                        "Umbuchung" if kind == "transfer" else "",
                        safe_text(categories.get(category_id, "")),
                        safe_text(tx.counterparty),
                        safe_text(tx.counterparty_iban),
                        safe_text(tx.description),
                        REVIEW_LABELS.get(tx.review_status, tx.review_status),
                        SOURCE_LABELS.get(tx.source, tx.source),
                        "ja" if tx.excluded_at else "",
                        str(tx.id),
                        str(split.line_no) if split else "",
                    ]
                )
        if len(page) < BATCH_SIZE:
            break
        offset += BATCH_SIZE


def schedule_csv(session: Session, loan: Loan) -> Iterator[str]:
    yield "﻿" + _csv_line(["Nr", "Fällig", "Rate", "Zinsen", "Tilgung", "Gebühren", "Restschuld danach", "Status"])
    entries = session.exec(
        select(LoanScheduleEntry).where(LoanScheduleEntry.loan_id == loan.id).order_by(LoanScheduleEntry.seq)
    )
    for e in entries:
        yield _csv_line(
            [str(e.seq), e.due_date.strftime("%d.%m.%Y"), plain_money(e.planned_installment),
             plain_money(e.planned_interest), plain_money(e.planned_principal), plain_money(e.planned_extra),
             plain_money(e.planned_remaining_after), e.status]
        )


# --- PDF ----------------------------------------------------------------------

_STYLES = getSampleStyleSheet()
_CELL = _STYLES["BodyText"].clone("cell", fontSize=8, leading=10)
_TABLE_STYLE = TableStyle(
    [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECF2")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#8A94A6")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F8FA")]),
    ]
)


def _esc(text: str | None) -> str:
    """Nutzertexte für ReportLab-Paragraphen escapen – Paragraph wertet Markup aus
    (z. B. <img src=…>, das lokale Dateien einbetten würde)."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(text: str) -> Paragraph:
    """Zellen umbrechen lange Namen statt sie abzuschneiden."""
    return Paragraph(_esc(text), _CELL)


def _table(rows: list[list], widths: list[float], long: bool = False) -> Table:
    table = (LongTable if long else Table)(rows, colWidths=widths, repeatRows=1)
    table.setStyle(_TABLE_STYLE)
    return table


def _document(title: str, story: list) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title=title, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Seite {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def report_pdf(session: Session, user: User, date_from: date, date_to: date) -> bytes:
    """Zusammenfassung und Kategorien aus denselben Berichtsfunktionen wie die API."""
    s = reports.summary(session, user, date_from, date_to)
    expense = reports.categories(session, user, date_from, date_to, "expense")
    income = reports.categories(session, user, date_from, date_to, "income")
    period = f"{date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}"
    story = [
        Paragraph(f"Finanzbericht {_esc(user.name)}", _STYLES["Title"]),
        Paragraph(f"Zeitraum {period}", _STYLES["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Kontostände am {date_to:%d.%m.%Y}", _STYLES["Heading2"]),
    ]
    rows = [["Konto", "Saldo"]] + [
        [_p(a["name"] + (" (archiviert)" if a["archived"] else "") + (" *" if a["history_incomplete"] else "")),
         money(a["balance"]) if a["balance"] is not None else "–"]
        for a in s["accounts"]
    ]
    rows += [["Vermögen", money(s["assets"])], ["Verbindlichkeiten", money(s["liabilities"])],
             ["Nettovermögen", money(s["net_worth"])]]
    story += [_table(rows, [120 * mm, 40 * mm]),
              Paragraph("* Anfangssaldo liegt im Zeitraum – Historie davor unvollständig", _CELL),
              Spacer(1, 6 * mm)]

    m = s["movements"]
    story += [
        Paragraph("Einnahmen und Ausgaben", _STYLES["Heading2"]),
        _table(
            [["", "Betrag"], ["Einnahmen (netto)", money(m["income"])], ["Ausgaben (netto)", money(m["expenses"])],
             ["Unkategorisiert: Zuflüsse", money(m["uncategorized_in"])],
             ["Unkategorisiert: Abflüsse", money(m["uncategorized_out"])], ["Saldo", money(m["net"])]],
            [120 * mm, 40 * mm],
        ),
        Spacer(1, 6 * mm),
    ]
    for title, data in (("Ausgaben nach Kategorie", expense), ("Einnahmen nach Kategorie", income)):
        rows = [["Kategorie", "Brutto", "Erstattet", "Netto", "Anteil"]]
        for item in data["items"]:
            indent = "    " if item["parent_id"] else ""
            share = f"{item['share'] * 100:.1f} %".replace(".", ",") if item["share"] is not None else "–"
            rows.append([_p(indent + item["name"]), money(item["gross"]), money(item["refunds"]),
                         money(item["net"]), share])
        rows.append([_p("Unkategorisiert"), money(data["uncategorized"]), "", "", ""])
        story += [Paragraph(title, _STYLES["Heading2"]),
                  _table(rows, [80 * mm, 25 * mm, 25 * mm, 25 * mm, 20 * mm], long=True), Spacer(1, 6 * mm)]
    return _document("Finanzbericht", story)


def schedule_pdf(session: Session, loan: Loan) -> bytes:
    account = session.get(Account, loan.account_id)
    entries = session.exec(
        select(LoanScheduleEntry).where(LoanScheduleEntry.loan_id == loan.id).order_by(LoanScheduleEntry.seq)
    )
    status = {"planned": "offen", "paid": "bezahlt", "skipped": "ausgesetzt"}
    rows = [["Nr", "Fällig", "Rate", "Zinsen", "Tilgung", "Gebühren", "Restschuld", "Status"]]
    rows += [
        [str(e.seq), f"{e.due_date:%d.%m.%Y}", money(e.planned_installment), money(e.planned_interest),
         money(e.planned_principal), money(e.planned_extra), money(e.planned_remaining_after), status[e.status]]
        for e in entries
    ]
    rate = f"{loan.annual_interest_rate:.2f}".replace(".", ",")
    story = [
        Paragraph(f"Tilgungsplan {_esc(account.name)}", _STYLES["Title"]),
        Paragraph(f"{_esc(loan.lender_name)} · {rate} % p. a.", _STYLES["Normal"]),
        Spacer(1, 5 * mm),
        _table(rows, [10 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 20 * mm, 26 * mm, 18 * mm], long=True),
    ]
    return _document("Tilgungsplan", story)
