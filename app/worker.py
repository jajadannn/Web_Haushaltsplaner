"""Import-Worker als eigener Prozess: `python -m app.worker`.

- beobachtet `imports/inbox/<watch-ordner>/` (watchdog) und legt für neue Dateien Aufträge an,
- verarbeitet wartende Aufträge (auch Uploads aus der API),
- setzt beim Start hängengebliebene Aufträge zurück und holt offene Archivierungen nach.

Übergabeprotokoll für Dateien: unter `*.part` schreiben und danach umbenennen.
Zusätzlich wird eine Datei erst übernommen, wenn sich Größe und Änderungszeit einige
Sekunden nicht mehr ändern.
"""

import logging
import os
import queue
import time
import uuid
from pathlib import Path

from sqlmodel import Session
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.config import get_settings
from app.db import engine
from app.models.imports import BatchSource, ImportProfile
from app.services.import_jobs import (
    archive_pending,
    create_batch,
    import_dir,
    process_queue,
    requeue_stale,
    safe_filename,
    watch_folder_for,
)

log = logging.getLogger("finanzplaner.worker")
SETTLE_SECONDS = 2.0
IGNORED_SUFFIXES = (".part", ".tmp", ".crdownload")


def is_candidate(path: Path, inbox: Path) -> bool:
    """Nur Dateien direkt in inbox/<ordner>/, keine temporären oder versteckten."""
    try:
        relative = path.relative_to(inbox)
    except ValueError:
        return False
    return (
        len(relative.parts) == 2
        and not path.name.startswith(".")
        and not path.name.endswith(IGNORED_SUFFIXES)
        and path.is_file()
    )


def ingest_inbox_file(session: Session, path: Path, inbox: Path) -> int | None:
    """Übernimmt eine Inbox-Datei als Auftrag; liefert die Auftrags-ID (None = nicht zuordenbar)."""
    subdir = path.relative_to(inbox).parts[0]
    folder = watch_folder_for(session, subdir)
    if folder is None:
        target = import_dir("failed") / f"unbekannter-ordner_{subdir}_{safe_filename(path.name)}"
        os.replace(path, target)
        log.warning("Kein Watch-Ordner '%s' angelegt – Datei nach %s verschoben", subdir, target)
        return None
    working = import_dir("processing") / f"{uuid.uuid4().hex}_{safe_filename(path.name)}"
    os.replace(path, working)  # atomar: ab jetzt unveränderliche Arbeitskopie
    profile = session.get(ImportProfile, folder.import_profile_id)
    batch, created = create_batch(
        session,
        user_id=folder.user_id,
        profile=profile,
        content=working.read_bytes(),
        original_filename=path.name,
        source=BatchSource.WATCHER,
        account_id=folder.account_id,
        stored_path=working,
    )
    session.commit()
    if not created:
        duplicate = import_dir("archive") / f"{batch.id}_bereits-importiert_{working.name}"
        os.replace(working, duplicate)
        log.info("%s wurde bereits mit Import %s verarbeitet", path.name, batch.id)
    else:
        log.info("Import %s für %s angelegt", batch.id, path.name)
    return batch.id


class InboxHandler(FileSystemEventHandler):
    def __init__(self, events: queue.Queue[Path]):
        self.events = events

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.events.put(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.events.put(Path(event.dest_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.events.put(Path(event.src_path))


class SettleTracker:
    """Merkt sich Dateien, bis Größe und Änderungszeit lange genug stabil sind."""

    def __init__(self, settle_seconds: float = SETTLE_SECONDS):
        self.settle_seconds = settle_seconds
        self.seen: dict[Path, tuple[tuple[int, float], float]] = {}

    def add(self, path: Path) -> None:
        self.seen.setdefault(path, ((-1, -1.0), time.monotonic()))

    def ready(self) -> list[Path]:
        now, done = time.monotonic(), []
        for path, (signature, since) in list(self.seen.items()):
            try:
                stat = path.stat()
            except FileNotFoundError:
                del self.seen[path]
                continue
            current = (stat.st_size, stat.st_mtime)
            if current != signature:
                self.seen[path] = (current, now)
            elif now - since >= self.settle_seconds:
                done.append(path)
                del self.seen[path]
        return done


def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    inbox = import_dir("inbox")
    events: queue.Queue[Path] = queue.Queue()
    observer = Observer()
    observer.schedule(InboxHandler(events), str(inbox), recursive=True)
    observer.start()
    log.info("Import-Worker beobachtet %s", inbox.resolve())

    tracker = SettleTracker()
    with Session(engine) as session:
        log.info("%s hängengebliebene Aufträge neu eingereiht", requeue_stale(session))
        archive_pending(session)
    for path in inbox.glob("*/*"):  # Dateien, die während einer Pause abgelegt wurden
        tracker.add(path)

    try:
        while True:
            try:
                tracker.add(events.get(timeout=settings.worker_poll_seconds))
                while True:
                    tracker.add(events.get_nowait())
            except queue.Empty:
                pass
            with Session(engine) as session:
                for path in tracker.ready():
                    if is_candidate(path, inbox):
                        try:
                            ingest_inbox_file(session, path, inbox)
                        except Exception:
                            session.rollback()
                            log.exception("Datei %s konnte nicht übernommen werden", path)
                process_queue(session)
                archive_pending(session)
    except KeyboardInterrupt:
        log.info("Import-Worker wird beendet")
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    run()
