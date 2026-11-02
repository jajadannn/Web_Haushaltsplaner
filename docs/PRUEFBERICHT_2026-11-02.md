# Prüfung des Finanzplaner-Backends

Stand: 02.11.2026, geprüfter Commit `eb3a9f8`. Geprüft wurden API, Services, Datenmodell und Migrationen, Parser, Import-Worker, Exporte sowie Sicherungs- und Testskripte.

Die Anwendung enthält **15 bestätigte Befunde**, einschließlich dreier Sicherheitsprobleme bei PDF-Erstellung, Regex-Kompilierung und Uploads. Besonders relevant sind doppelte Importbuchungen, das Einlesen lokaler Bilddateien beim PDF-Export und widersprüchliche Finanzdaten über alternative Änderungswege. Die vorhandenen Tests decken diese Fälle nicht ab.

**Bewertung:** P1 = hohe Priorität, vor verlässlichem Einsatz mit echten Finanzdaten korrigieren. P2 = konkreter Fehler mit begrenzterem Auslöser, anschließend beheben. Die Einstufung berücksichtigt den dokumentierten lokalen Einzelplatzbetrieb. `X-User-Id` ist ausdrücklich eine Profilwahl und keine Authentifizierung.

**Durchgeführte Prüfungen:**

- Vollständige vorhandene Testsuite: **693 bestanden**, Laufzeit 63,87 Sekunden.
- `ruff check app tests`: **bestanden**.
- `bash -n` für die vier Shellskripte: **bestanden**; dies prüft Syntax, nicht deren gesamte Laufzeitlogik.
- Die 54 Registry-Pakete aus `uv.lock` wurden mit Name und Version gegen die [OSV-API](https://google.github.io/osv.dev/post-v1-querybatch/) geprüft: **keine gemeldeten Treffer** zum Prüfzeitpunkt. Das ist keine Garantie für Schwachstellenfreiheit oder die Herkunft aller installierten Komponenten.
- Zusätzliche gezielte Reproduktionen mit PostgreSQL und TestClient, einer selbst erzeugten Bilddatei, begrenztem Regex-Unterprozess und temporären Importdateien. Die Datenbank-Reproduktionen liefen mit Rollback in der separaten Testdatenbank oder in anschließend entfernten temporären Schemas. Keine Änderungen an Anwendungsdaten.

## Bestätigte Befunde

### 1. [P1] Gleichzeitige Importfreigaben erzeugen Doppelbuchungen

**Stellen:** [Importfreigabe](/home/fabian/Dokumente/Web_Haushaltsplaner/app/routers/imports.py:186), [Übernahme der Zeilen](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/import_commit.py:115).

Der Router prüft `awaiting_review`, sperrt den Auftrag aber nicht. `commit_batch()` erzeugt anschließend neue Buchungen, ohne den Status erneut unter einer Sperre zu prüfen oder eine bereits gesetzte `created_transaction_id` abzusichern. Zwei überlappende Requests können deshalb dieselben Zeilen übernehmen.

**Nachweis:** Zwei PostgreSQL-Sessions lesen denselben freigegebenen CSV-Auftrag. Session A übernimmt und committet; Session B übernimmt mit ihrer zuvor geprüften Instanz ebenfalls. Ergebnis: zwei Buchungen zu je 10 Euro statt einer, Gesamtsumme 20 Euro.

**Korrektur:** Batchzeile vor der Statusprüfung innerhalb derselben Transaktion sperren. Zusätzlich die Übernahme einer Importzeile eindeutig und idempotent absichern. Regressionstest mit zwei getrennten Verbindungen ergänzen.

### 2. [P1] PDF-Titel erlauben das Einlesen lokaler Bilddateien

**Stellen:** [Berichtstitel](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/export.py:173), [Kreditname und Kreditgeber](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/export.py:227).

Die genannten Namen werden ungeescaped an ReportLabs `Paragraph` übergeben. Dieser interpretiert Markup einschließlich Bild-Tags. Damit können für den API-Prozess lesbare lokale Bilddateien in den herunterladbaren Bericht eingebettet werden. Fehlerhaftes Markup kann den Export außerdem mit einem Serverfehler abbrechen lassen.

**Nachweis:** Einen Profilnamen mit einem `<img>`-Tag setzen, dessen `src` auf eine eigens erzeugte PNG-Testdatei in `/tmp` zeigt. Der anschließende Aufruf von `/export/report.pdf` liefert HTTP 200 und ein PDF mit dem lokalen Bild. Der verwendete Name war kürzer als das erlaubte Namenslimit.

**Grenze:** Nachgewiesen ist das Einlesen von Bilddateien, nicht beliebiger Textdateien. Netzwerkzugriffe wurden von der installierten ReportLab-Konfiguration blockiert; SSRF ist hier nicht bestätigt.

**Korrektur:** Alle Nutzereingaben vor der Übergabe an `Paragraph` als Text escapen. Für Tabellenzellen existiert bereits `_p()`; die Titel benötigen denselben Schutz.

### 3. [P1] Die Prüfliste kann eine Umbuchung einseitig zur Ausgabe machen

**Stelle:** [Bestätigung mit Kategorie](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/review.py:91).

Die normale Buchungsbearbeitung schützt gepaarte Umbuchungen vor einer Änderung ihrer Art. Der Review-Pfad setzt bei Angabe einer Kategorie dagegen ungeprüft `kind=regular`, behält `transfer_peer_id` und verändert die Gegenseite nicht. Einzel- und Sammelbestätigung sind betroffen.

**Nachweis:** 100 Euro von Konto A nach B umbuchen. Die normale Änderung der Ausgangsbuchung wird mit `422 transfer_pair_linked` abgewiesen. Dieselbe Änderung über `/review/{id}/confirm` liefert 200. Der Kategorienbericht zeigt anschließend 100 Euro Ausgabe statt null; die positive Gegenseite bleibt eine Umbuchung.

**Korrektur:** Den Schutz gepaarter Umbuchungen zentral durchsetzen und auch bei Review-Änderungen anwenden. Beide Endpunkte im Regressionstest vergleichen.

### 4. [P1] Das Bezahlen einer späteren Rate entfernt frühere offene Raten

**Stellen:** [Auswahl einer Rate](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:92), [Neuberechnung des Plans](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/core.py:207), [nächste Fälligkeit](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/core.py:178).

`_target_entry()` akzeptiert jede offene Ratennummer. Die Neuberechnung löscht alle noch offenen Einträge und beginnt hinter der höchsten erledigten Nummer. Frühere unbezahlte Raten verschwinden dadurch aus der Fälligkeitsübersicht. Die Restschuld wird dabei nicht einfach erlassen; fehlerhaft ist die Darstellung der noch offenen Verpflichtungen und ihrer Termine.

**Nachweis:** Bei einem neuen Kredit zuerst `schedule_seq=2` buchen. Der Request liefert HTTP 201; danach fehlt Rate 1 vollständig im Tilgungsplan. Automatisches Import-Matching verwendet denselben Buchungsweg.

**Korrektur:** Nur die nächste offene Rate zulassen oder frühere offene Verpflichtungen bei der Neuberechnung erhalten. Buchungen außerhalb der zeitlichen Reihenfolge ausdrücklich testen.

### 5. [P2] Kreditkonten lassen eine vom Tilgungsplan unabhängige Restschuld zu

**Stelle:** [Kontobearbeitung](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/accounts.py:69).

Bei Kreditkonten wird ein Typwechsel abgefangen, die Änderung des Anfangssaldos und des Anfangsdatums aber nicht mit der Kreditlogik abgestimmt. Dadurch passen Kontosaldo, Kreditstatus und gespeicherter Tilgungsplan nicht mehr zusammen.

**Nachweis:** Kredit über 1.000 Euro bei 12 Prozent anlegen. Das Kreditkonto mit `opening_balance=-2000` ändern: HTTP 200. Die Restschuld beträgt anschließend 2.000 Euro, der gespeicherte Plan tilgt weiterhin nur 1.000 Euro; die erste geplante Zinszahlung bleibt 10 statt 20 Euro.

**Korrektur:** Finanzielle Basisfelder von Kreditkonten über einen gemeinsamen Kreditservice ändern. Plan, Status und Restschuld zusammen aktualisieren oder diese Änderungen über die allgemeine Konto-API ablehnen.

### 6. [P2] Teilzahlungen lassen offene Zinsen und Gebühren verschwinden

**Stellen:** [Rate als bezahlt markieren](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:207), [Zahlungsaufteilung](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/schedule.py:225).

Die Aufteilung begrenzt den Zins- und Gebührenanteil auf den tatsächlichen Zahlbetrag. Anschließend gilt die ganze Rate als bezahlt. Nicht gedeckte Zinsen und Gebühren werden weder als offene Forderung gespeichert noch in den nächsten Plan übernommen.

**Nachweis:** Kredit über 1.000 Euro bei 12 Prozent, erste geplante Zinsen 10 Euro. Zahlung von 1 Euro liefert HTTP 201 und setzt die Rate auf `paid`. Die Restschuld bleibt 1.000 Euro, die nächste Monatszinszahlung 10 Euro; die noch offenen 9 Euro aus der vorherigen Rate werden nicht weitergeführt.

**Korrektur:** Teilzahlungen mit verbleibenden Forderungen modellieren. Bis dahin solche Zahlungen ausdrücklich ablehnen, statt die Rate vollständig zu erledigen.

### 7. [P2] Rückdatierte Privatkreditzahlungen erzeugen falsche Zinsanteile

**Stellen:** [letztes Zahlungsdatum](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:102), [Zinsvorschlag](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:114).

Freie Zahlungen verwenden immer das höchste bereits vorhandene Zahlungsdatum. Eine danach erfasste frühere Zahlung erzeugt negative Zinstage und damit null Zinsen. Nachfolgende Zahlungen werden nicht neu berechnet; auch die verwendete Restschuld berücksichtigt bereits spätere Tilgungen.

**Nachweis:** Privatkredit über 1.000 Euro zu 3,65 Prozent. Zahlung von 110 Euro am 11.04. ergibt 10 Euro Zinsen und 100 Euro Tilgung. Danach eine Zahlung von 100 Euro am 01.02. erfassen: HTTP 201, null Euro Zinsen und 100 Euro Tilgung. Die Aprilbuchung bleibt unverändert.

**Korrektur:** Rückdatierungen ablehnen oder sämtliche betroffenen Zahlungen und Zinsintervalle chronologisch neu berechnen.

### 8. [P2] Die Dateidublettenprüfung berücksichtigt das Zielkonto nicht

**Stellen:** [Suche nach vorhandener Datei](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/import_jobs.py:93), [Unique-Index](/home/fabian/Dokumente/Web_Haushaltsplaner/app/models/imports.py:147).

Die Dateiidentität besteht aus Benutzer, Importprofil und Hash. Das gewählte Zielkonto fehlt. Unterstützte CSV-Dateien ohne Kontokennung können für zwei Konten derselben Bank identische Inhalte enthalten. Der zweite Import wird dann als bereits vorhanden behandelt, obwohl auf dem zweiten Konto nichts gebucht wurde.

**Nachweis:** Identische CSV-Bytes mit demselben Bankprofil zuerst für Konto A und danach für Konto B einreichen. Der erste Auftrag wird angelegt, der zweite liefert denselben Auftrag für Konto A zurück (`created=False`).

**Korrektur:** Den Zuordnungskontext einschließlich explizitem Zielkonto in Dateiidentität und Datenbankconstraint aufnehmen. Mehrkontodateien ohne festes Zielkonto gesondert berücksichtigen.

### 9. [P2] Ein schneller Worker-Neustart lässt Importe dauerhaft hängen

**Stellen:** [einmalige Wiederaufnahme beim Start](/home/fabian/Dokumente/Web_Haushaltsplaner/app/worker.py:141), [Zeitgrenze](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/import_jobs.py:359).

`requeue_stale()` läuft nur beim Start und berücksichtigt nur über 15 Minuten alte Aufträge. Bei einem schnellen Neustart nach einem Absturz ist der Heartbeat noch zu jung. Die Hauptschleife prüft ihn später nicht erneut. Der Auftrag bleibt `processing`; `/retry` akzeptiert diesen Status ebenfalls nicht.

**Nachweis:** Frischer `processing`-Auftrag: Wiederaufnahme findet null Aufträge. Nach Überschreiten der Altersgrenze verarbeitet der normale Queue-Durchlauf weiterhin nichts, der Status bleibt unverändert.

**Korrektur:** Wiederaufnahme regelmäßig ausführen, verbunden mit einer zuverlässigen Prozess- oder Lease-Prüfung und laufender Heartbeat-Aktualisierung. Aktive lange Jobs dürfen dabei nicht doppelt gestartet werden.

### 10. [P2, Sicherheit] Regex-Kompilierung kann den Speicher erschöpfen

**Stelle:** [Kompilieren eines Musters](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/categorization.py:40).

Das vorhandene 50-ms-Limit schützt nur die Suche. Die vorherige Kompilierung läuft ohne Ressourcenbegrenzung. Eine gültige kurze Regel mit einer extrem großen Wiederholungszahl übersteht die Eingabevalidierung und benötigt bereits beim Kompilieren sehr viel Speicher. Die Ausnahmebehandlung deckt nur Syntaxfehler ab.

**Nachweis:** `RuleCreate` akzeptiert das 13 Zeichen lange Muster `x{1000000000}`. Der echte Aufruf von `compile_pattern()` löst in einem isolierten Unterprozess mit 256 MiB Adressraumlimit `MemoryError` aus. Ein zusätzlicher äußerer Timeout begrenzte die Reproduktion auf fünf Sekunden. Ohne solche Begrenzung besteht das Risiko einer erheblichen Speicherbelastung bis zur Prozessbeendigung.

**Korrektur:** Kompilierung wirksam begrenzen oder isolieren und zulässige Mustereigenschaften einschränken. Ein bloßes Abfangen von `MemoryError` verhindert den Ressourcenverbrauch nicht.

### 11. [P2, Sicherheit] Das Uploadlimit greift erst nach dem Speichern des gesamten Dateiinhalts

**Stelle:** [Größenprüfung im Uploadhandler](/home/fabian/Dokumente/Web_Haushaltsplaner/app/routers/imports.py:107).

Beim Eintritt in den Handler ist das Multipart-Upload bereits verarbeitet. Große Dateien liegen zu diesem Zeitpunkt im temporären Dateisystem. `file.file.read(limit + 1)` begrenzt nur das nachträgliche Einlesen. Eine vorgelagerte Begrenzung eingehender Bytes fehlt im geprüften Setup.

**Nachweis:** Bei einem 10-MiB-Limit wurden von einem 11-MiB-Upload alle 11.534.336 Bytes ins temporäre Dateiobjekt geschrieben; `rolled_to_disk=True`. Erst danach kam `file_too_large`. Dasselbe vollständige Schreiben passiert ohne `X-User-Id`, bevor `profile_required` zurückgegeben wird. Der Test verwendete keine Datenbankverbindung.

**Korrektur:** Die tatsächlichen eingehenden Bytes vor der Multipart-Verarbeitung begrenzen, etwa in einer ASGI-Komponente oder einem verbindlich vorgeschalteten Proxy. Ein reiner `Content-Length`-Check genügt nicht.

### 12. [P2] Eine Sicherung bei aktivem Worker kann nicht zusammenpassende Datei- und Datenbankstände enthalten

**Stellen:** [Dateisicherung nach dem Datenbankdump](/home/fabian/Dokumente/Web_Haushaltsplaner/scripts/backup.sh:111), [Verschieben und Umbenennen](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/import_jobs.py:374), [Lesen der gespeicherten Datei](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/import_jobs.py:230).

Der Datenbankdump kann einen laufenden Auftrag mit `stored_path` unter `processing/` enthalten. Beendet der Worker den Import vor der anschließenden Dateisicherung, liegt die Datei bereits unter einem anderen Namen in `archive/`. Die Reihenfolge der gesicherten Ordner stellt den im Dump referenzierten Pfad nicht wieder her.

**Nachweis:** Den Datenbankzustand eines laufenden Auftrags als Objekt-Snapshot festhalten, die echte Archivfunktion ausführen und danach die Importordner als Tar sichern. Der Snapshot erwartet `processing/test.csv`, das Archiv enthält ausschließlich `archive/1_test.csv`. Die Verarbeitung mit dem Snapshot schlägt mit `file_missing` fehl. Dies ist eine kontrollierte Reproduktion des Zeitfensters, kein vollständiger produktiver Restore-Test.

**Korrektur:** Für eine konsistente Sicherung schreibende API- und Worker-Aktionen koordinieren bzw. pausieren oder unveränderliche Dateischlüssel mit einem konsistenten Manifest verwenden. Einen Restore mit zum Sicherungszeitpunkt laufendem Import testen.

### 13. [P2, geringere Auswirkung] Regeln für „beliebiges Feld“ verlieren bei langen Beschreibungen die Gegenpartei

**Stelle:** [Zusammenstellen des Suchtexts](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/categorization.py:46).

Beschreibung und Gegenpartei werden zuerst verkettet und anschließend gemeinsam auf 1.000 Zeichen gekürzt. Eine zulässige Beschreibung mit 1.000 Zeichen verdrängt deshalb die gesamte Gegenpartei. `match_field=any` verhält sich dann enger als `match_field=counterparty`.

**Nachweis:** Beschreibung mit 1.000 `x`-Zeichen, Gegenpartei `ARAL Tankstelle`, Suchmuster `ARAL`: `any` liefert keinen Treffer, `counterparty` liefert einen Treffer.

**Korrektur:** Beide Felder separat begrenzen und durchsuchen; die fachliche Bedeutung von `any` dabei erhalten.

### 14. [P1] Bereits mit Bankdaten abgeglichene manuelle Buchungen bleiben verschiebbar

**Stellen:** [Schutz unveränderlicher Bankfelder](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/transactions.py:276), [Erkennen einer Bank-ID-Dublette](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/dedup.py:79).

Eine manuelle Buchung, die als Dublette einer Importzeile bestätigt wurde, erhält eine `TransactionImportLink`-Identität und bleibt zugleich `source=manual`. Die Bearbeitung schützt Bankfelder jedoch nur bei `source=import`. Konto, Datum und Betrag können deshalb geändert werden, während der alte Bank-ID-Link bestehen bleibt. Weitere Importe vertrauen dieser überholten Zuordnung.

**Nachweis:** Manuelle Buchung per OFX-Import abgleichen. Änderungen an Betrag, Datum und Konto werden jeweils mit HTTP 200 angenommen. Nach Verschiebung von Konto A nach B bleibt der Importlink auf Konto A. Ein weiterer OFX-Export mit derselben FITID und geändertem Memo wird als Dublette behandelt: null neue Buchungen, eine Dublette, Konto A bleibt leer. Der Prüffall für den Kontowechsel verwendete passende Datums- und Betragswerte, damit die bereits vorhandenen Vergleichsprüfungen erfüllt waren.

**Korrektur:** Für unveränderliche Bankfelder die vorhandene Funktion `has_import_identity()` statt allein `source` verwenden. Beim Abgleich zusätzlich die Konsistenz von Bank-ID-Link und aktueller Buchung prüfen. Eine fachlich notwendige Korrektur muss die Zuordnung ausdrücklich auflösen oder atomar mitändern.

### 15. [P2] Löschen und Ausschließen behandeln importbestätigte Transferpaare inkonsistent

**Stellen:** [Löschen der Gegenseite](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/transactions.py:358), [Ausschluss einer Buchung](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/transactions.py:373).

Der Löschschutz prüft nur die angefragte Buchung auf Importidentität. Ein manueller Transferpartner wird anschließend ohne dieselbe Prüfung mitgelöscht. Umgekehrt verändert der Ausschlusspfad ausschließlich die angefragte Buchung und lässt den Transferpartner aktiv. Beide Wege verletzen die gemeinsame Behandlung eines Transferpaars.

**Nachweis, Löschen:** 25 Euro von A nach B umbuchen und die Gutschrift B als OFX-Dublette bestätigen. Direktes Löschen von B wird mit `409 imported_use_exclude` abgelehnt. Löschen von A liefert dagegen 204 und entfernt beide Seiten samt FITID-Link. Der nächste überlappende OFX-Export importiert B erneut als reguläre Einnahme.

**Nachweis, Ausschließen:** Bei einem solchen Transfer die bestätigte Seite B ausschließen. A bleibt aktiv, B wird nicht mehr berücksichtigt. Die Summe der berücksichtigten Buchungen beträgt minus 25 Euro statt null; dadurch verändert sich das berechnete Nettovermögen allein durch den einseitigen Ausschluss.

**Korrektur:** Vor Löschung beide Seiten auf Importidentität prüfen. Ausschließen und Wiedereinbeziehen eines gepaarten Transfers müssen eine explizite gemeinsame Regel haben, etwa atomare Behandlung beider Seiten oder Ablehnung des einseitigen Eingriffs. Den Zusammenhang nicht stillschweigend zerstören.

## Beobachtete Betriebs- und Entwicklungspraktiken

Diese Punkte sind von den reproduzierten Anwendungsfehlern zu unterscheiden:

- **Datenbankzugriff als Superuser:** Die Standard-URL in [config.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/config.py:10) verwendet `postgres`; die aktive lokale Rolle wurde als Superuser bestätigt. Die lokale, nicht versionierte [pg_hba.conf](/home/fabian/Dokumente/Web_Haushaltsplaner/.pg/data/pg_hba.conf:117) verwendet `trust`, auch für TCP über Loopback. Andere lokale Prozesse können dadurch ohne Passwort eine beliebige Datenbankrolle wählen. Für einen ausschließlich vertrauenswürdigen Einzelplatz ist dies eine bewusste Betriebsentscheidung; bei mehreren lokalen Benutzern fehlt damit eine wirksame Abgrenzung. Die [PostgreSQL-Dokumentation zu trust](https://www.postgresql.org/docs/16/auth-trust.html) erläutert diese Grenze. Eine eigene, eingeschränkte Anwendungsrolle und geeignete Authentifizierung begrenzen die Auswirkungen von Anwendungsfehlern.
- **Tests löschen ohne Schutzprüfung ein Schema:** [tests/conftest.py](/home/fabian/Dokumente/Web_Haushaltsplaner/tests/conftest.py:34) führt auf der konfigurierten Test-URL unmittelbar `DROP SCHEMA public CASCADE` aus. Aktuell sind Anwendungs- und Testdatenbank verschieden; das wurde vor dem Testlauf geprüft. Bei einer Fehlkonfiguration auf dieselbe Datenbank fehlt jedoch eine technische Sperre. Datenbankidentitäten vor dem Löschen vergleichen und eine ausdrückliche Testdatenbank-Konvention erzwingen; idealerweise eine eigene Rolle ohne Rechte auf die Anwendungsdatenbank verwenden.
- **Profilwahl ist kein Zugriffsschutz:** [deps.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/deps.py:13) vertraut der vom Aufrufer gewählten Benutzer-ID. Das ist dokumentiertes Design, kein versehentlich übersehener Passwortcheck. Die geprüfte Startanleitung bindet an Loopback. Eine Netzwerkfreigabe oder der Einsatz für gegenseitig nicht vertrauenswürdige Benutzer erfordert eine authentifizierte Identität und daran gebundene Berechtigungen.

Positiv sind die Verwendung von `Decimal` und `Numeric` für Geld, das Verbot von NaN/Unendlich in Geldschemas, mehrere Datenbankconstraints zur Profilzuordnung, der Schutz vor Formelausführung in CSV-Textzellen sowie die breite vorhandene Testsuite. Die zusätzlichen Befunde zeigen vor allem Lücken bei konkurrierenden Requests, alternativen Änderungswegen und Zustandsübergängen über mehrere Komponenten.

## Empfohlene Reihenfolge

1. Importfreigaben serialisieren und idempotent machen; PDF-Markup escapen.
2. Gemeinsame Invarianten für Umbuchungen, bereits abgeglichene Bankbuchungen, Kreditkonten und Kreditraten durchsetzen.
3. Teilzahlungen und rückdatierte Zahlungen konsistent behandeln.
4. Upload- und Regex-Ressourcenlimits vor der teuren Verarbeitung anwenden.
5. Importidentität, Worker-Wiederaufnahme und konsistente Sicherungen korrigieren.
6. Gezielte Regressionstests für die beschriebenen Fälle ergänzen. Die Zahl grüner Tests allein belegt diese Eigenschaften nicht.

Die Prüfung ist eine Codeanalyse mit gezielten Laufzeitnachweisen. Sie ersetzt keinen vollständigen Lasttest oder Penetrationstest einer späteren Bereitstellung. Die beschriebenen Korrekturen wurden im Rahmen dieser Prüfung noch nicht implementiert.
