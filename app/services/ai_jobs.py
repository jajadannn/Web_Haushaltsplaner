"""Warteschlange für KI-Aufträge (Anreicherung von Vorschlägen, Belege lesen, Erklärungen …).

Ein Auftrag verweist auf ein Objekt (`ref_type`, `ref_id`) und hat eine Aufgabenart (`kind`) mit
- `prepare(session, job)` → (Aufgabe, Daten, Schema) oder None (nichts mehr zu tun),
- `finish(session, job, antwort)` → schreibt das Ergebnis über die Fach-Services.

Während die KI rechnet, ist keine Datenbanktransaktion offen; `finish` prüft den aktuellen Stand
erneut (der Nutzer kann inzwischen entschieden haben). Ungültige Antworten zählen als Fehlversuch,
nach `MAX_ATTEMPTS` ist der Auftrag `failed`; ist die KI nicht erreichbar, bleibt er in der Schlange.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.models import AiJob, AiJobStatus
from app.services import ai_gateway, settings

log = logging.getLogger("finanzplaner.ki.auftraege")

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=10)
IDLE_SECONDS = 15.0
BACKOFF_SECONDS = 60.0


@dataclass
class Image:
    """Bild für das Bildmodell (z. B. Foto eines Belegs) statt Textdaten."""

    content: bytes
    mime: str
    data: Any = None


@dataclass
class Task:
    prepare: Callable[[Session, AiJob], tuple[str, Any, dict] | None]  # Daten oder Image
    finish: Callable[[Session, AiJob, dict], dict | None]


TASKS: dict[str, Task] = {}


def register(kind: str, task: Task) -> None:
    TASKS[kind] = task


def enqueue(session: Session, user_id: int, kind: str, ref_type: str, ref_id: int) -> AiJob | None:
    """Neuen Auftrag anlegen – nicht, wenn die KI im Profil abgeschaltet ist oder er schon besteht."""
    if not settings.get(session, user_id, "ai.enabled"):
        return None
    existing = session.exec(
        select(AiJob).where(AiJob.kind == kind, AiJob.ref_type == ref_type, AiJob.ref_id == ref_id)
    ).first()
    if existing is not None:
        if existing.status in (AiJobStatus.DONE, AiJobStatus.FAILED):
            existing.status, existing.attempts, existing.error = AiJobStatus.QUEUED, 0, None
        return existing
    job = AiJob(user_id=user_id, kind=kind, ref_type=ref_type, ref_id=ref_id)
    session.add(job)
    session.flush()
    return job


def _claim(session: Session) -> AiJob | None:
    now = datetime.now(UTC)
    job = session.exec(
        select(AiJob)
        .where(or_(AiJob.status == AiJobStatus.QUEUED,
                   (AiJob.status == AiJobStatus.RUNNING) & (AiJob.lease_until < now)))
        .order_by(AiJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if job is None:
        return None
    job.status, job.lease_until, job.attempts = AiJobStatus.RUNNING, now + LEASE, job.attempts + 1
    session.commit()
    return job


def _fail(session: Session, job: AiJob, error: str) -> None:
    job.error = error[:500]
    job.status = AiJobStatus.FAILED if job.attempts >= MAX_ATTEMPTS else AiJobStatus.QUEUED
    session.commit()


def run_one(session: Session) -> bool | None:
    """Einen Auftrag bearbeiten. True/False = bearbeitet (erfolgreich/nicht), None = nichts zu tun."""
    job = _claim(session)
    if job is None:
        return None
    task = TASKS.get(job.kind)
    if task is None:
        _fail(session, job, f"Unbekannte Aufgabe {job.kind}")
        return False
    try:
        prepared = task.prepare(session, job)
        if prepared is None:
            job.status = AiJobStatus.DONE
            session.commit()
            return True
        what, data, schema = prepared
        session.commit()  # keine offene Transaktion, während die KI rechnet
        if isinstance(data, Image):
            answer = ai_gateway.ask_vision(what, data.content, data.mime, schema, data=data.data)
        else:
            answer = ai_gateway.ask(what, data, schema, session=session)
        job = session.get(AiJob, job.id, populate_existing=True)
        job.result = task.finish(session, job, answer) or answer
        job.status, job.error = AiJobStatus.DONE, None
        session.commit()
        return True
    except ai_gateway.AiInvalidAnswer as exc:
        session.rollback()
        _fail(session, session.get(AiJob, job.id), f"Ungültige Antwort: {exc}")
        return False
    except ai_gateway.AiUnavailable:
        session.rollback()
        job = session.get(AiJob, job.id)
        job.status, job.attempts = AiJobStatus.QUEUED, max(job.attempts - 1, 0)
        session.commit()
        raise
    except Exception as exc:  # Fehler eines Auftrags darf die Schlange nicht blockieren
        session.rollback()
        log.exception("KI-Auftrag %s fehlgeschlagen", job.id)
        _fail(session, session.get(AiJob, job.id), str(exc))
        return False


def run_pending(session: Session, limit: int = 50) -> int:
    """Alle offenen Aufträge nacheinander (für Tests und manuelle Läufe); Anzahl bearbeiteter."""
    if not ai_gateway.enabled():
        return 0
    done = 0
    for _ in range(limit):
        try:
            result = run_one(session)
        except ai_gateway.AiUnavailable:
            break
        if result is None:
            break
        done += 1
    return done


def run_forever(engine: Engine, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with Session(engine) as session:
                result = run_one(session)
        except ai_gateway.AiUnavailable as exc:
            log.warning("KI nicht erreichbar (%s) – neuer Versuch in %ss", exc, BACKOFF_SECONDS)
            stop.wait(BACKOFF_SECONDS)
            continue
        except Exception:
            log.exception("KI-Auftragsschleife")
            result = None
        if result is None:
            stop.wait(IDLE_SECONDS)


def start_in_background(engine: Engine) -> threading.Event | None:
    if not ai_gateway.enabled():
        return None
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(engine, stop), name="ki-auftraege", daemon=True).start()
    return stop
