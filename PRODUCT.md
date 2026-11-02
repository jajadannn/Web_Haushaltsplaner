# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Frontend: React + Vite + TypeScript als Single-Page-App gegen die bestehende FastAPI (Dev-Server auf Port 5173, CORS ist dafür eingestellt). Backend: FastAPI, SQLModel, PostgreSQL 16, Alembic (siehe README.md).

## Users

Ein Privathaushalt im eigenen Heimnetz, typischerweise Partner bzw. Familie. Jede Person hat ein eigenes Profil mit eigenen Konten, Kategorien und Regeln; das Profil wird ohne Passwort gewählt (Header `X-User-Id`). Genutzt wird überwiegend am Desktop – Kontoauszüge importieren, Buchungen klären, Kredite und Berichte ansehen – und gelegentlich am Handy, um unterwegs Salden zu prüfen oder eine Ausgabe schnell zu erfassen.

## Product Purpose

Die Finanzen eines Haushalts vollständig und richtig abbilden: mehrere Konten bei mehreren Banken, Einnahmen und Ausgaben, Kredite mit Tilgungsplan, und daraus verlässliche Auswertungen. Erfolg heißt: Kontostände stimmen mit der Bank überein, nichts wird doppelt oder gar nicht gebucht, und die wiederkehrende Pflege (Auszüge einlesen, Unklares klären) kostet wenig Zeit.

## Positioning

Ein selbst betriebener, lokaler Finanzplaner, der Richtigkeit vor Bequemlichkeit stellt: Er bucht nie still doppelt und verwirft nichts still, sondern fragt bei möglichen Dubletten nach; Salden werden immer berechnet statt gespeichert; Kreditraten werden in Zins (Ausgabe) und Tilgung (Umbuchung) getrennt; alle Daten bleiben im eigenen Netz.

## Operating Context

- Kontoauszüge kommen als CSV, OFX oder MT940 per Upload oder über Watch-Ordner (`imports/inbox/<ordner>/`); ein separater Import-Worker verarbeitet sie.
- Wiederkehrender Ablauf: Auszug einlesen → mögliche Dubletten und Zeilen vor dem Stichtag klären → übernehmen → Prüfliste (unkategorisierte/automatisch kategorisierte Buchungen) abarbeiten → Regeln ergänzen.
- Kredite: fällige und überfällige Raten, Tilgungsplan, Zinsen pro Jahr (z. B. für die Steuer).
- Berichte über Zeiträume: Nettovermögen, Einnahmen/Ausgaben, Kategorien, Monatstrends; Export als CSV/PDF.
- Betrieb lokal (Loopback bzw. internes Netz), Backup über `scripts/backup.sh`.

## Capabilities and Constraints

- Vorhandene API (siehe `/docs` der FastAPI): Profile, Banken, Konten (inkl. Archivieren, Stichtag mit Anfangssaldo), Kategorien (Hierarchie, Deaktivieren, Zusammenführen), Buchungen mit Splits und Umbuchungen, Ausschließen importierter Buchungen, Kredite (Annuität, Tilgungsdarlehen, Privatkredit; Raten, Ratenpause, Belastungen), Importprofile, Watch-Ordner, Importe mit Zeilenklärung, Regeln mit Vorschau, Prüfliste, Berichte, CSV-/PDF-Export.
- Nur EUR und nur gebuchte Umsätze; Geldbeträge kommen als Dezimalstrings (`"1234.56"`) und dürfen nie über float gerechnet werden.
- Fehlerformat: `{"error": {"code", "message", "details"}}` – Codes sind für die Oberfläche auswertbar (z. B. `before_opening`, `transfer_pair_linked`, `import_rows_open`).
- Fachliche Regeln, die die Oberfläche nicht verwischen darf: Umbuchungen sind weder Einnahme noch Ausgabe; Erstattungen werden in der Kategorie verrechnet; Bestätigen in der Prüfliste heißt nicht „mit Kontoauszug abgestimmt“; Kredit-Laufzeit endet mit einer Schlussrate.
- Profilwahl ist kein Zugriffsschutz.
- Offen: Abgleich mit Kontoauszug, Budgets/Vorschau, Teilzahlungen bei Krediten, Mehrwährung (alles Backlog).

## Brand Commitments

Arbeitsname „Finanzplaner“ (Repository „Web_Haushaltsplaner“). Oberfläche und Texte auf Deutsch. Keine weiteren verbindlichen Markenvorgaben.

## Evidence on Hand

Keine echten Kundendaten, Logos oder Testimonials. Anonymisierte Beispiel-Kontoauszüge unter `tests/fixtures/imports/` (Bankformate nachgebildet, nicht mit echten Exporten verifiziert). Echte Bankexporte des Haushalts liegen noch nicht vor.

## Product Principles

1. Richtigkeit vor Bequemlichkeit: Im Zweifel nachfragen, nie still doppelt buchen oder verwerfen.
2. Klären muss schnell gehen: Die wiederkehrende Pflege (Import, Dubletten, Prüfliste) ist der Kernablauf und verdient den geringsten Reibungsverlust.
3. Zahlen sind nachvollziehbar: Woher ein Saldo, eine Kategorie oder ein Zinsanteil kommt, ist jederzeit erkennbar.
4. Fachbegriffe ehrlich: Umbuchung, Erstattung, Tilgung und Zinsen werden so dargestellt, wie sie fachlich gemeint sind.
