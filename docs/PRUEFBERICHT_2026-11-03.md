# Prüfbericht Backend und Frontend – 3./4. November 2026

Geprüfter Stand: `f3834cd` (`feat: Frontend mit Wanddisplay, persönlicher Ansicht und Heimnetz-Betrieb`). Die Prüfung begann am 3. November. Am 4. November wurde sie auf den inzwischen hinzugekommenen Stand `1bc52a2` erweitert: lokale KI, Sammelbestätigung, MT940-Kontozuordnung, Fixkostenübernahme und Docker-Dateien. Die ursprünglichen Laufzeitproben betreffen `f3834cd`; die relevanten Fundstellen bestehen im erweiterten Stand fort. F16 wurde auf dem erweiterten Stand reproduziert.

**16 bestätigte Befunde: 3 × P1, 12 × P2, 1 × P3.** P1 bedeutet hohe Priorität wegen Verfügbarkeit oder falscher Finanzdaten; P2 bezeichnet relevante Funktionsfehler, P3 einen begrenzten Bedienfehler. Die Nummern gehören zu diesem Bericht und ersetzen nicht die Nummerierung des Berichts vom 2. November.

Projektlokal installiert und angewandt: `find-bugs`, `vercel-react-best-practices`, `web-design-guidelines`; gefunden mithilfe des bereits vorhandenen `find-skills`. Anwendungscode wurde nicht geändert. Prüfungen erfolgten mit synthetischen Daten in separaten PostgreSQL-Datenbanken und einer eigenen Anwendung auf Port 8017.

## Bestätigte Befunde

| Nr. | Priorität | Befund |
|---|---|---|
| F1 | P1 | Regex-Schutz lässt speicherintensive Kompilierung zu |
| F2 | P1 | Parallele Kreditzahlungen überzahlen die Restschuld |
| F3 | P1 | Zahlungen ohne Kreditplan fehlen im verfügbaren Monatsbudget |
| F4 | P2 | Zahlungen über dem Planwert werden aus dem Budget herausgerechnet |
| F5 | P2 | Eine Kreditzahlung wird zusätzlich als gewöhnliche Fixkostenzahlung erkannt |
| F6 | P2 | Buchungsliste bricht beim Nachladen über 200 Einträge ab |
| F7 | P2 | Importbestätigte manuelle Buchungen haben keine gültige Ausschlussaktion |
| F8 | P2 | Kategoriefilter summiert bei Empfängern den gesamten Splitbetrag |
| F9 | P2 | Zusammenführen von Kategorien erzeugt unsichtbare Unterkategorien |
| F10 | P2 | Offene Importe verschwinden nach 30 neueren Importen |
| F11 | P2 | Wechsel der Fensterbreite verwirft ungespeicherte Formulardaten |
| F12 | P2 | Restore in anderen Importordner hinterlässt ungültige Dateiverweise |
| F13 | P3 | Erfolgreiches Löschen verliert Bestätigung und URL-Bereinigung |
| F14 | P2 | Privatkreditzahlungen ohne Plan lassen sich im UI nicht stornieren |
| F15 | P2 | Reine Kreditumbenennung entfernt die vereinbarte Laufzeit |
| F16 | P2 | KI übernimmt inzwischen ungültige Kategorien |

### F1 – P1: Regex-Schutz lässt speicherintensive Kompilierung zu

Fundstelle: [app/services/categorization.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/categorization.py:49).

Der Schutz addiert Wiederholungsgrenzen, berücksichtigt aber ihre Verschachtelung nicht. `((x{100}){100}){100}` und `(((x{75}){75}){75}){75}` passieren die Prüfung. In isolierten Prozessen mit 256 MiB Adressraumlimit löste die anschließende Kompilierung jeweils `MemoryError` aus. Der Such-Timeout schützt die Kompilierung nicht. Ein erreichbarer Regel-Endpunkt erlaubt damit speicherintensive Arbeit im API-Prozess; ein unbeschränkter Serverabsturz wurde bewusst nicht provoziert.

**Korrekturrichtung:** Verschachtelte Wiederholungen und die tatsächliche Regex-Komplexität begrenzen oder Kompilierung und Ausführung in einen begrenzten separaten Prozess verlagern. Den Schutz auch beim Laden bestehender Regeln anwenden.

### F2 – P1: Parallele Kreditzahlungen überzahlen die Restschuld

Fundstelle: [app/services/loans/payments.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:207).

Zwei PostgreSQL-Sessions lesen dieselbe Restschuld, bevor eine Zahlung festgeschrieben ist. Bei 1.000 € Restschuld wurden zwei Zahlungen zu je 750 € erfolgreich committet; die Restschuld beträgt anschließend −500 €. Die Reproduktion synchronisiert ausschließlich den Zeitpunkt nach dem vorhandenen Lesen der Restschuld und ersetzt keine berechneten Werte. Es fehlt eine gemeinsame Sperre vor Prüfung und Buchung.

**Korrekturrichtung:** Den Kredit vor dem Lesen von Status, Reihenfolge und Restschuld innerhalb der Transaktion sperren. Alle konkurrierenden Zahlungs-, Storno-, Belastungs- und Konditionsänderungen müssen dieselbe Sperrkonvention verwenden. Regression mit zwei echten Datenbankverbindungen ergänzen.

### F3 – P1: Zahlungen ohne Kreditplan fehlen im verfügbaren Monatsbudget

Fundstelle: [app/services/budget.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/budget.py:180).

Bei 1.000 € Monatseinnahmen und einem Privatkredit ohne feste Rate bleibt „verfügbar“ nach einer tatsächlichen Zahlung von 250 € unverändert bei 1.000 € statt 750 €. Der Budgetdienst berücksichtigt Kredite über Planraten; die Tilgung ist zugleich als Transfer aus den normalen Ausgaben entfernt. Dadurch verschwindet der reale Geldabfluss aus der Budgetberechnung.

**Korrekturrichtung:** Tatsächliche Kreditabflüsse auch ohne Plan erfassen und nach Buchungsmonat zuordnen. Planreservierung und tatsächliche Zahlung einmalig verrechnen; zusätzlich Zahlungen in einem anderen Monat als dem Fälligkeitsmonat testen.

### F4 – P2: Zahlungen über dem Planwert werden aus dem Budget herausgerechnet

Fundstelle: [app/services/budget.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/budget.py:251).

Mit 1.000 € Einnahmen, 100 € Fixkostenplan und 150 € tatsächlicher Zahlung zeigt das Budget 900 € verfügbar statt 850 €. Bei einer geplanten Kreditrate von 100 € und tatsächlichen 250 € bleiben ebenfalls 900 € statt 750 €. Die tatsächlich zugeordneten Ausgaben werden vollständig aus den variablen Ausgaben entfernt, während nur der Planbetrag abgezogen wird.

**Korrekturrichtung:** Tatsächliche Ausgaben plus noch offene Reservierung berechnen. Mehrzahlungen dürfen nicht verschwinden; die gewünschte Behandlung von Teilzahlungen ausdrücklich definieren.

### F5 – P2: Eine Kreditzahlung wird zusätzlich als gewöhnliche Fixkostenzahlung erkannt

Fundstelle: [app/services/budget.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/budget.py:125).

Eine Kreditrate von 100 € mit 10 € Zinsen und ein weiterer Fixkostenposten von 50 € mit passender Zinskategorie führen zu `fixed_paid=110` und `variable_spent=-10`. Dieselben 10 € werden bei Kredit und Fixkosten abgezogen; verfügbar werden 860 € statt 850 €. Der Fixkostenmatcher schließt mit LoanPayment verbundene Buchungsanteile nicht aus.

**Korrekturrichtung:** Kreditbuchungen aus dem gewöhnlichen Fixkostenmatching ausschließen oder verbrauchte Buchungsanteile global nur einmal zuordnen. Kategorie- und Textmatching berücksichtigen.

### F6 – P2: Buchungsliste bricht beim Nachladen über 200 Einträge ab

Fundstelle: [frontend/src/pages/buchungen/TransactionsPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/buchungen/TransactionsPage.tsx:62).

Mit 205 Buchungen werden zunächst 100, dann 200 geladen. Der nächste Klick fordert `limit=300` an, obwohl die API höchstens 200 zulässt. Die Antwort ist HTTP 422; die angezeigte Liste fällt auf null Zeilen zurück.

**Korrekturrichtung:** Mit begrenzter Seitengröße und Offset beziehungsweise Cursor paginieren und geladene Seiten bei einem Folgefehler erhalten.

### F7 – P2: Importbestätigte manuelle Buchungen haben keine gültige Ausschlussaktion

Fundstelle: [frontend/src/pages/buchungen/TransactionEditor.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/buchungen/TransactionEditor.tsx:213).

Eine manuelle Buchung, die beim Import als identische Bankbuchung bestätigt wurde, behält `source=manual`, besitzt aber Importidentität. Die Oberfläche bietet nur Löschen und keinen Ausschluss an. Löschen scheitert korrekt mit HTTP 409 `imported_use_exclude`. Die neue Backend-Schutzregel ist nicht im UI-Modell abgebildet.

**Korrekturrichtung:** Die tatsächlichen Fähigkeiten beziehungsweise Import- und Kreditverknüpfungen in der API ausgeben und passende Aktionen im Editor anbieten. Die Backend-Schutzregel beibehalten.

### F8 – P2: Kategoriefilter summiert bei Empfängern den gesamten Splitbetrag

Fundstelle: [frontend/src/pages/berichte/ReportsPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/berichte/ReportsPage.tsx:220).

Eine Buchung über 12,50 € ist auf Kategorie A mit 8 € und B mit 4,50 € verteilt. In der Detailansicht für A steht korrekt 8 € netto, unter „Größte Empfänger“ aber 12,50 €. Auch die gefilterte Buchungsliste zeigt 12,50 € Ausgaben. Der Filter wählt passende Buchungen, die anschließende Summe verwendet jedoch deren vollständigen Betrag.

**Korrekturrichtung:** Nur passende reguläre Splitanteile summieren, einschließlich der definierten Unterkategorien. Transferanteile nicht als Kategorieausgabe addieren.

### F9 – P2: Zusammenführen von Kategorien erzeugt unsichtbare Unterkategorien

Fundstelle: [frontend/src/pages/einstellungen/CategoriesSection.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/einstellungen/CategoriesSection.tsx:19).

Eine Wurzelkategorie A mit Kind B wird in eine vorhandene Unterkategorie T zusammengeführt. Die API akzeptiert dies; B ist danach Kind von T und damit auf Ebene drei. In den Einstellungen verschwindet B, obwohl die API es weiter liefert. Die Darstellung verarbeitet nur Wurzeln und direkte Kinder.

**Korrekturrichtung:** Kategoriebäume rekursiv darstellen und Filter/Selektoren mitziehen, oder die erlaubte Tiefe durchgängig in Backend und UI begrenzen. Bestehende tiefere Kategorien berücksichtigen.

### F10 – P2: Offene Importe verschwinden nach 30 neueren Importen

Fundstelle: [frontend/src/pages/import/ImportPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/import/ImportPage.tsx:59).

Nach einem Import im Status `awaiting_review` und 30 neueren Importen ist der alte Eintrag weder in der Liste noch über `/import?id=<id>` erreichbar. Das direkte API-GET liefert ihn weiterhin mit HTTP 200. Die ausgewählte ID wird ausschließlich in den neuesten 30 Listeneinträgen gesucht.

**Korrekturrichtung:** Ausgewählte Import-ID separat laden und eine vollständige Navigation/Paginierung anbieten. Offene Prüfaufgaben dürfen nicht von der Historienbegrenzung abhängen.

### F11 – P2: Wechsel der Fensterbreite verwirft ungespeicherte Formulardaten

Fundstelle: [frontend/src/pages/einstellungen/MasterDetail.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/einstellungen/MasterDetail.tsx:102).

Ein Fixkostenentwurf mit Name und 123,45 € wurde bei 1440 px ausgefüllt. Nach Verkleinerung auf 1000 px sind beide Felder leer. Der Wechsel zwischen Seitenbereich und Dialog hängt den zustandsführenden Formularbaum aus und neu ein; es gibt keine Warnung.

**Korrekturrichtung:** Formularzustand oberhalb des responsiven Darstellungswechsels halten oder denselben Formularbaum erhalten. Größenänderung und Tabletrotation mit ungespeichertem Entwurf testen.

### F12 – P2: Restore in anderen Importordner hinterlässt ungültige Dateiverweise

Fundstelle: [scripts/restore.sh](/home/fabian/Dokumente/Web_Haushaltsplaner/scripts/restore.sh:217).

Backup und Restore in eine separate Datenbank mit anderem IMPORT_DIR endeten beide mit Exit 0. Die Datei liegt im neuen Ordner, `stored_path` in der Datenbank zeigt weiterhin auf den alten. Nach vorübergehendem Ausblenden nur des alten Audit-Ordners scheitert die Verarbeitung des wiederhergestellten Imports mit `file_missing`. Das betrifft auch die dokumentierte Restore-Probe mit abweichendem Importordner.

**Korrekturrichtung:** Dateipfade relativ zum konfigurierten Importwurzelordner speichern und bestehende Datensätze migrieren oder Pfade beim Restore zuverlässig umschreiben. Nach Restore tatsächlich eine ausstehende Importdatei lesen.

### F13 – P3: Erfolgreiches Löschen verliert Bestätigung und URL-Bereinigung

Fundstelle: [frontend/src/api/hooks.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/api/hooks.ts:73).

Die API löscht die Buchung erfolgreich mit HTTP 204; das anschließende GET liefert 404. Dennoch fehlt die Erfolgsmeldung und die URL enthält weiter die gelöschte ID. Die abgewartete Cache-Invalidierung entfernt den Editor vor dessen per-mutate-Erfolgscallback. Der bestehende Browserlauf paket1 scheitert genau beim Warten auf diese Bestätigung.

**Korrekturrichtung:** Erfolgsmeldung und Navigation in einem beständigen Parent beziehungsweise Hook ausführen, bevor das Refetch den Editor entfernt. Den vorhandenen Browserlauf als Regression verwenden.

### F14 – P2: Privatkreditzahlungen ohne Plan lassen sich im UI nicht stornieren

Fundstelle: [frontend/src/pages/kredite/LoansPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/kredite/LoansPage.tsx:245).

Bei einem Privatkredit ohne vereinbarte Rate liefert die API eine erfasste Zahlung, aber die Oberfläche bietet null Stornoaktionen. Die Storno-Schaltfläche existiert nur in bezahlten Tilgungsplanzeilen; ohne Plan gibt es diese nicht. Der normale Buchungseditor darf verknüpfte Kreditbuchungen ebenfalls nicht löschen.

**Korrekturrichtung:** Eine Zahlungshistorie unabhängig vom Tilgungsplan anzeigen und die vom Backend erlaubte Stornoaktion für die letzte Zahlung anbieten.

### F15 – P2: Reine Kreditumbenennung entfernt die vereinbarte Laufzeit

Fundstelle: [frontend/src/pages/kredite/LoanDialogs.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/kredite/LoanDialogs.tsx:209).

Ein über 48 Monate angelegter Kredit speichert Laufzeit und berechnete Rate. Beim Bearbeiten wählt das Formular deshalb automatisch die Rate als Basis und sendet selbst bei bloßer Namensänderung `term_months=null`. Im Browser wurde der Verlust von 48 auf null bestätigt. Die unmittelbare Ratenzahl blieb in dieser Probe bei 48. In einer anschließenden API-Vergleichsprobe mit identischer Änderung des Zinssatzes auf 6 % behielt der Kontrollkredit seine 48 Raten zu 234,86 €; der umbenannte Kredit lief über 56 Raten zu 208,34 € bis Juni 2031 statt Oktober 2030.

**Korrekturrichtung:** Bei PATCH nur tatsächlich geänderte Felder senden. Eine berechnete Rate darf die explizite Laufzeitbasis nicht stillschweigend ersetzen. Name-only-Änderungen müssen Konditionen und Laufzeit erhalten.


### F16 – P2: KI übernimmt inzwischen ungültige Kategorien

Fundstelle: [app/services/ai_review.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/ai_review.py:358), ergänzend [app/services/review.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/review.py:130).

Der Worker sammelt angebotene Kategorien vor der potenziell langen KI-Anfrage. Vor dem Speichern prüft er die Buchung erneut, aber nicht die gewählte Kategorie. In zwei gezielten Proben wurde die zunächst unbenutzte Ausgabekategorie während der Anfrage per regulärem API-PATCH einmal deaktiviert und einmal in eine Einnahmekategorie geändert. Beide Änderungen wurden akzeptiert. Anschließend erhielt die Ausgabe die veraltete Kategorie und den Status `auto_categorized`; `confirm-all` bestätigte jeweils eine Buchung ohne Überspringen. Die KI-Antwort war für diese Probe vorgegeben; die Kategorieänderung und Speicherung liefen durch die echten API-/Datenbankpfade.

**Korrekturrichtung:** Vor Übernahme unter konsistenter Transaktion erneut prüfen, ob die Kategorie existiert, dem Profil gehört, aktiv ist und weiterhin zur angebotenen Auswahl beziehungsweise Buchung passt. Nach Änderungen einen neuen Vorschlag anfordern. Auch die Sammelbestätigung muss ungültig gewordene Kategorien behandeln.

## Verifikation

| Prüfung | Ergebnis |
|---|---|
| Backend pytest | Ursprünglich 745 bestanden; auf `1bc52a2` 780 bestanden, 196,61 Sekunden |
| Frontend Vitest | Ursprünglich 90 Tests in 8 Dateien; auf `1bc52a2` 97 Tests in 9 Dateien bestanden |
| Ruff, Frontend-Lint, TypeScript, Vite-Produktionsbuild | Bestanden |
| Shell-Syntax der Backup-/Restore-/Datenbankskripte | Bestanden |
| Browserpaket 1 | Anlage, Aufteilung und Filter funktionierten; Abbruch an fehlender Löschbestätigung (F13) |
| Browserpaket 2 und 3 | Bestanden |
| Wanddisplay, Chrome-Smoke-Test | November 2026 geladen, keine pageerror-Ereignisse |
| Zusätzliche Browserproben | F6–F11, F13–F15 reproduziert |
| Budget-/Parallelitätsproben | F2–F5 reproduziert; PostgreSQL statt SQLite |
| Backup und Restore | Skripte erfolgreich; Dateiverarbeitung nach Pfadwechsel scheitert (F12) |
| npm audit | Keine gemeldeten Schwachstellen zum Prüfzeitpunkt |
| OSV-Abfrage zu 54 Python-Paketen aus uv.lock | Keine Treffer zum Prüfzeitpunkt |

Grüne vorhandene Tests decken diese Randfälle nicht ab. Die Regex-Probe lief in speicherbegrenzten Unterprozessen; es wurde kein unbeschränkter Denial-of-Service gegen die laufende Anwendung ausgelöst.

## Abgleich mit der vorherigen Prüfung

Die bereits eingebauten Korrekturen und ihre Regressionstests wurden berücksichtigt. Beim Import sind Sperre und Wiederholungsprüfung vorhanden; Transferpaare und Bankidentitäten werden geschützt. PDF-Text wird maskiert, die Uploadgröße wird vor der Multipart-Verarbeitung begrenzt. Kreditreihenfolge, Rückdatierung und Änderungen des Eröffnungssaldos sind abgesichert. Die Worker-Wiederaufnahme besitzt Lease-/Versuchsgrenzen; Backup und Dateiverschiebung verwenden koordinierte Sperren.

Der frühere Regex-Befund ist nur teilweise behoben (F1). Neue Restprobleme liegen insbesondere im Zusammenspiel der Schutzregeln mit dem Frontend (F7) und bei parallelen Kreditzahlungen (F2). Der Restore-Pfadfehler F12 ist unabhängig von der inzwischen verbesserten Backup-Sperre.

## Sicherheits- und Praxischeck

| Bereich | Ergebnis / Grenze |
|---|---|
| SQL-/Shell-Injection, Dateipfade | Relevante Datenzugriffe und Skripte geprüft; kein zusätzlicher bestätigter Injection-Befund. Restore-Pfade: F12. |
| XSS, HTML/PDF, CSV | React-Ausgabe, Exportpfade und Escape-Verwendung geprüft; kein weiterer bestätigter Befund. |
| Authentifizierung und Profilzugriff | Bewusstes Heimnetzmodell: X-User-Id ist Profilauswahl, kein Identitätsnachweis. Ein zugelassenes Gerät kann Profile auswählen. Das ist die dokumentierte Vertrauensgrenze und keine hier neu entdeckte Authentifizierung. |
| Autorisierung von Objekt-IDs | Ownership-Prüfungen und Regressionen berücksichtigt; keine vollständige Kombination aller Endpunkte/Rollen durchgeprüft. |
| CSRF und Browserzugriff | JSON-/Header-Verwendung und Netzwerkgrenzen berücksichtigt; kein separater umfassender DNS-Rebinding-/Fremdursprungs-Penetrationstest. |
| Eingabevalidierung, Ressourcenverbrauch | Uploadbegrenzung positiv; Regex-Kompilierung weiter problematisch (F1). |
| Parallelität und Transaktionsintegrität | Importabsicherung vorhanden; Kreditrennen bestätigt (F2). |
| Finanzlogik | Reale Abflüsse und doppelte Zuordnung fehlerhaft (F3–F5); Kategorienauswertung und Kreditkonditionen F8/F15. |
| Fehlerbehandlung und Zustandsverwaltung | API-/UI-Verträge, Pagination, Entwürfe und Mutationscallbacks: F6–F14. |
| Sessions, Passwörter, Kryptografie | Kein entsprechendes Login-/Passwortmodell implementiert; daher überwiegend nicht anwendbar. |
| Abhängigkeiten | Keine Treffer der genannten Abfragen; dies ist keine Garantie für unbekannte Schwachstellen. |
| React-/UI-Praxis | Lazy-Routen, Query-Cache, Profiltrennung der Query-Keys und BigInt-Geldverarbeitung sind vorhanden. Keine pauschale Bibliotheksmigration empfohlen. |
| Barrierefreiheit | Labels, Dialoge, aria-invalid und reduzierte Bewegung stichprobenartig geprüft. Keine vollständige WCAG-, Kontrast- oder Screenreader-Zertifizierung. |

## Nachweise und Grenzen

Die synthetischen Messergebnisse stehen in [docs/pruefung-2026-11-03/nachweise.json](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/pruefung-2026-11-03/nachweise.json); die Liste vollständig gelesener Dateien in [docs/PRUEFUMFANG_2026-11-03.md](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/PRUEFUMFANG_2026-11-03.md). Im Nachweisordner liegen zusätzlich Audit-Ausgaben, ausgewählte Screenshots und Reproduktionsskripte. Die Skripte sind Prüfartefakte mit festem lokalen Audit-Endpunkt und temporären Pfaden, keine produktiven Migrationen; sie dürfen nicht unbesehen gegen Nutzerdaten ausgeführt werden.

Die Prüfung kombiniert Quellcodeanalyse, vorhandene Tests und gezielte Laufzeitproben. Nicht jede Datei und nicht jede Zustandskombination wurde vollständig geprüft. Browserproben erfolgten mit Chrome unter Linux; Firefox, Safari, reale Mobilgeräte, Reverse-Proxy-/Firewall-Konfiguration und ein tatsächlicher Docker-Start und ein echter Serverumzug wurden nicht geprüft. Die Docker-Dateien wurden gelesen, aber kein Image gebaut. Ein realer Ollama-/LM-Studio-Modelllauf wurde nicht ausgeführt; die KI-Integrationsprobe verwendete eine kontrollierte Antwort. Die Restore-Probe nutzte eine zweite lokale Datenbank und einen anderen Importordner. Es wurden weder vorhandene Nutzerdaten verändert noch Fehler im Anwendungscode repariert.

Ergänzende fachliche Prüfung vom 4. November: [docs/SINNFEHLER_2026-11-04.md](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/SINNFEHLER_2026-11-04.md) (neun zusätzliche Befunde und zwei Vertiefungen).
