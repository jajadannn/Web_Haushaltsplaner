# Laufender Prüfbericht: KI-Ausbau — 5. November 2026

Geprüfter Stand: `7b48533` (main, Merge PR #2). **39 Befunde: 3 × P1, 35 × P2, 1 × P3; davon 38 reproduziert und 1 durch Konfigurationsprüfung belegt.** Die Gesamtsuche ist noch nicht abgeschlossen. Keine Änderungen am Anwendungscode.

P1 = hohe Priorität wegen verletzter finanzieller Invariante; P2 = relevanter Funktions-/Logikfehler; P3 = nachrangiger Darstellungs-/Messfehler. Zusammenhängende Symptome sind zusammengefasst, um die Anzahl nicht künstlich zu erhöhen. Frühere F-/S-Befunde werden hier nicht erneut gezählt.

## Nachweise und Methode

Sechs isolierte Reproduktionsläufe erstellen jeweils eine eigene PostgreSQL-Datenbank mit zufälligem Namen, migrieren sie auf head und entfernen sie im finally-Block. Reguläre API-Aufrufe arbeiten ausschließlich mit synthetischen Profilen. Der Assistenten-Splitfall ruft die echte Werkzeugausführung direkt auf; Dokument- und KI-Fälle verwenden kontrollierte Antworten beziehungsweise Exceptions ohne externe Modellanfrage. Alle sechs Skripte liefen mit ihren Assertions erfolgreich durch. Beim ersten zweiten Lauf wurde die Aufräumvariable versehentlich überschrieben; die Probe-Datenbank wurde anschließend anhand ihrer synthetischen Profile identifiziert und entfernt, das Skript korrigiert und vollständig erfolgreich erneut ausgeführt.

Ausführung aus dem Projektverzeichnis:

```bash
PYTHONPATH=. .venv/bin/python docs/pruefung-ki-2026-11-05/probe.py
PYTHONPATH=. .venv/bin/python docs/pruefung-ki-2026-11-05/probe2.py
PYTHONPATH=. .venv/bin/python docs/pruefung-ki-2026-11-05/probe3.py
PYTHONPATH=. .venv/bin/python docs/pruefung-ki-2026-11-05/probe4.py
PYTHONPATH=. .venv/bin/python docs/pruefung-ki-2026-11-05/probe5.py
PYTHONPATH=. .venv/bin/python docs/pruefung-ki-2026-11-05/probe6.py
```

Die Skripte benötigen dieselbe lokale PostgreSQL-Erreichbarkeit wie das Projekt und die Berechtigung zum Anlegen eigener Probe-Datenbanken. Sie ändern keine produktiven Daten. Ergebnisse: [Lauf 1](pruefung-ki-2026-11-05/results.json), [Lauf 2](pruefung-ki-2026-11-05/results2.json), [Lauf 3](pruefung-ki-2026-11-05/results3.json), [Lauf 4](pruefung-ki-2026-11-05/results4.json), [Lauf 5](pruefung-ki-2026-11-05/results5.json), [Lauf 6](pruefung-ki-2026-11-05/results6.json). Lauf 6 führt die echten Backup-/Restore-Skripte mit ausschließlich temporären Ordnern und einer weiteren zufällig benannten neuen Ziel-Datenbank aus; auch diese wird entfernt.

## Befunde

| ID | Priorität | Problem |
|---|---|---|
| N01 | P1 | Veralteter Umbuchungsvorschlag erzeugt ein unausgeglichenes Paar |
| N02 | P2 | Rücknahme meldet Erfolg, lässt die Umbuchung aber bestehen |
| N03 | P2 | Fixkosten-Preisanpassung lässt sich unmittelbar nach Übernahme nicht zurücknehmen |
| N04 | P2 | Probelauf-Vorschläge bleiben nach Aktivierung der Automatik liegen |
| N05 | P2 | Ausgeschaltete Erkennung erzeugt weiterhin Vorschläge |
| N06 | P2 | Übernahme verwendet veraltete Beträge der Belegbuchungen |
| N07 | P2 | Zwischenzeitlich manuell angelegte Fixkost verhindert keine doppelte Übernahme |
| N08 | P2 | Zuordnung einer Fixkost ignoriert ihr hinterlegtes Konto |
| N09 | P2 | Nachträglich positiver Zahlungseingang bleibt als Fixkostenzahlung bestehen |
| N10 | P2 | Eine Gehaltszahlung erledigt mehrere unabhängige Einnahmenserien |
| N11 | P2 | Bereits erfasste zukünftige Buchungen verschwinden aus der Kontovorschau |
| N12 | P2 | Assistent summiert Splitbuchungen mit dem Gesamtbetrag |
| N13 | P2 | Vorgestern wird beim lokalen Erfassungs-Fallback zu gestern |
| N14 | P2 | Tausenderbetrag wird beim Erfassungs-Fallback um Faktor tausend verkleinert |
| N15 | P2 | KI-Abschaltung des Profils wird nicht in allen Ausführungspfaden beachtet |
| N16 | P2 | USD-Beleg wird einer gleich hohen EUR-Buchung vorgeschlagen |
| N17 | P2 | Manuelle Betragsänderung wirkt nach Einführung einer Historie nicht mehr im Budget |
| N18 | P2 | Mehrere Erstattungen können denselben Einkauf übersteigen |
| N19 | P2 | Automatik ignoriert explizite KI-Einschätzung „keine Verpflichtung“ |
| N20 | P2 | IBAN-Erkennung verdeckt weitere Referenz-Aliasse desselben Vertrags |
| N21 | P2 | Referenz als Teilstring ordnet Buchungen dem falschen Vertrag zu |
| N22 | P2 | Abgelehnte Rückfragen verhindern weitere Rückfragen dauerhaft |
| N23 | P2 | Endgültig fehlgeschlagener Dokumentauftrag bleibt in der Oberfläche wartend |
| N24 | P2 | Nicht aufeinanderfolgende Preisabweichungen ändern den Plan automatisch rückwirkend |
| N25 | P3 | Rücknahmequote verwendet den falschen Nenner |
| N26 | P2 | Split-Vorlage scheitert bei bereits automatisch kategorisierter Buchung |
| N27 | P2 | Zwei Fixkosten aus verschiedenen Splits derselben Buchung blockieren sich |
| N28 | P2 | Einnahmenänderung akzeptiert eine umgekehrte Betragsspanne |
| N29 | P2 | Ungültige Vorschlagswerte führen zu HTTP 500 statt Validierungsfehler |
| N30 | P2 | Alter Erstattungsvorschlag überschreibt zwischenzeitliche manuelle Bestätigung |
| N31 | P2 | Abgelehnter Fixkostenvorschlag erscheint bei einem weiteren Vertrag erneut |
| N32 | P2 | Namenskonflikt in der Automatik zerstört die Savepoint-Behandlung |
| N33 | P2 | Rücknahme einer Regel löscht eine zwischenzeitliche manuelle Änderung |
| N34 | P2 | Automatische und manuelle Übernahme derselben Regel erzeugen Duplikate |
| N35 | P2 | Importassistent beantwortet gewöhnliche Formatfehler mit Serverfehlern |
| N36 | P2 | KI zur Spaltenerkennung erhält bei unbekanntem Format keine Beispielwerte |
| N37 | P1 | Backup lässt alle Belege aus, solange keine Import-Unterordner existieren |
| N38 | P1 | Restore überschreibt vorhandene Belege ohne --yes oder Rückfrage |
| N39 | P2 | Docker-Betrieb richtet keinen beschreibbaren gemeinsamen Dokumentordner ein |

### N01 — P1: Veralteter Umbuchungsvorschlag erzeugt ein unausgeglichenes Paar

Fundstelle: `app/services/matching.py:99`.

Zwei passende Buchungen −100/+100 erkennen lassen, den Eingang auf +200 ändern und den alten Vorschlag übernehmen. Beide Buchungen werden trotzdem zu einem gekoppelten Transfer. Die Differenz von 100 € verschwindet aus Einnahmen/Ausgaben, obwohl sich das Gesamtvermögen um 100 € verändert. Der normale Änderungsweg sperrt das anschließend als gekoppeltes Paar.

**Korrekturrichtung:** Unter Sperre Betragssumme, Konten, Buchungsart, Ausschlussstatus, Gegenparteien und Datenversion erneut prüfen; bei Abweichungen neu erkennen lassen.

**Nachweis:** `results.json` → `unbalanced_transfer`.

### N02 — P2: Rücknahme meldet Erfolg, lässt die Umbuchung aber bestehen

Fundstelle: `app/services/suggestions.py:215`.

Umbuchungsvorschlag annehmen und sofort zurücknehmen. Die API antwortet 200 mit status=reverted; die Buchung bleibt kind=transfer und gekoppelt. Der Handler schreibt keinen ChangeLog, die Rücknahmeschleife bearbeitet deshalb null Einträge. Derselbe fehlende Änderungsverlauf betrifft im Code auch Erstattungen, Split-Vorlagen, Belegzuordnungen, Rückfragen und Importprofilkorrekturen; ausgeführt wurde hier der Transferfall.

**Korrekturrichtung:** Jede verändernde Übernahme vollständig protokollieren und fachlich konsistent zurücknehmen. Eine nicht implementierte Rücknahme ausdrücklich ablehnen, statt Erfolg zu melden.

**Nachweis:** `results.json` → `transfer_fake_revert`.

### N03 — P2: Fixkosten-Preisanpassung lässt sich unmittelbar nach Übernahme nicht zurücknehmen

Fundstelle: `app/services/changes.py:74`.

Zwei zugeordnete Zahlungen über 30 € bei 20 € Planbetrag erkennen und übernehmen. Die sofortige Rücknahme scheitert mit 409 changed_since, obwohl nichts manuell geändert wurde. upkeep._change_apply protokolliert nur amount; changes.revert vergleicht dagegen den vollständigen FIXED_FIELDS-Snapshot. Außerdem wird die angelegte Betragsgeschichte gar nicht protokolliert.

**Korrekturrichtung:** Änderungsspezifische Snapshots vergleichen und die FixedCostAmount-Zeilen einschließlich vorheriger Versionen atomar mit zurücknehmen.

**Nachweis:** `results.json` → `amount_revert`.

### N04 — P2: Probelauf-Vorschläge bleiben nach Aktivierung der Automatik liegen

Fundstelle: `app/services/suggestions.py:119`.

Drei identische Monatszahlungen im Probelauf erkennen, danach auf auto wechseln und erneut analysieren. Der Status bleibt dry_run, es entsteht keine Fixkost. Die Automatik liest ausschließlich open; sync setzt dry_run nicht zurück.

**Korrekturrichtung:** Beim Moduswechsel zulässige vorhandene Vorschläge erneut gegen aktuelle Evidenz prüfen und zur Verarbeitung freigeben.

**Nachweis:** `results.json` → `dry_run_to_auto`.

### N05 — P2: Ausgeschaltete Erkennung erzeugt weiterhin Vorschläge

Fundstelle: `app/services/suggestions.py:73`.

automation.fixed_cost=off setzen und die Erkennung ausführen: Ein neuer offener Fixkostenvorschlag wird angelegt. Die Oberfläche verspricht für Aus ausdrücklich „Es wird nichts erkannt.“ Erst nach dem Speichern berücksichtigt _automate den Modus. Die gemeinsame Infrastruktur betrifft auch andere Automatikarten.

**Korrekturrichtung:** Die jeweilige Funktion bereits vor Erkennung beziehungsweise Speicherung anhand ihrer Einstellung sperren und den Umgang mit bestehenden Vorschlägen definieren.

**Nachweis:** `results.json` → `off_still_suggests`.

### N06 — P2: Übernahme verwendet veraltete Beträge der Belegbuchungen

Fundstelle: `app/services/recurring.py:311`.

Fixkostenvorschlag aus drei Abbuchungen über 20 € erzeugen. Alle drei Buchungen auf 75 € ändern, dann den alten Vorschlag annehmen. Die Fixkost wird weiterhin mit 20 € angelegt. Die Evidenzprüfung kontrolliert nur Existenz und Ausschluss, nicht Betrag, Datum, Kategorie oder Vertragsbezug.

**Korrekturrichtung:** Evidenz mit relevanten Werten und Versionen speichern und unmittelbar vor Übernahme vollständig revalidieren.

**Nachweis:** `results.json` → `stale_evidence`.

### N07 — P2: Zwischenzeitlich manuell angelegte Fixkost verhindert keine doppelte Übernahme

Fundstelle: `app/services/recurring.py:319`.

Vorschlag erkennen, passende Fixkost unter anderem Namen manuell anlegen und danach den alten Vorschlag übernehmen. Es existieren zwei Fixkosten für denselben Anbieter. _validate prüft nur feste Zahlungsverknüpfungen; die manuelle Fixkost muss solche Links nicht besitzen.

**Korrekturrichtung:** Den Abgleich mit aktuellen Fixkosten auch bei der Übernahme durchführen und die fachliche Identität unter Parallelität absichern.

**Nachweis:** `results.json` → `manual_duplicate`.

### N08 — P2: Zuordnung einer Fixkost ignoriert ihr hinterlegtes Konto

Fundstelle: `app/services/budget.py:274`.

Fixkost auf Girokonto A hinterlegen. Eine passende Zahlung nur auf Konto B buchen. Der Monatsplan markiert die Fixkost auf A trotzdem als bezahlt. Die Suchabfrage nutzt account_id nicht; dadurch kann auch die Vorschau für Konto A eine noch anstehende Belastung ausblenden.

**Korrekturrichtung:** Bei hinterlegtem Konto die automatische Zahlungssuche darauf begrenzen; bewusste manuelle Abweichungen getrennt behandeln.

**Nachweis:** `results.json` → `wrong_account_payment`.

### N09 — P2: Nachträglich positiver Zahlungseingang bleibt als Fixkostenzahlung bestehen

Fundstelle: `app/services/budget.py:306`.

Eine manuelle Abbuchung über 20 € fest verknüpfen und danach auf +20 € ändern. Die Fixkost bleibt bezahlt und zeigt paid_amount=-20.00. Beim Lesen fester Links wird der Ausschlussstatus geprüft, aber nicht mehr Abfluss, Art oder Kreditbezug.

**Korrekturrichtung:** Relevante Buchungsänderungen gegen vorhandene Links validieren oder ungültige Links lösen. Die Leseabfrage zusätzlich defensiv prüfen.

**Nachweis:** `results.json` → `positive_fixed_payment`.

### N10 — P2: Eine Gehaltszahlung erledigt mehrere unabhängige Einnahmenserien

Fundstelle: `app/services/outlook.py:101`.

Zwei erwartete Einnahmen auf demselben Konto und derselben Kategorie anlegen, aber mit verschiedenen Arbeitgeber-Suchtexten. Nur Arbeitgeber A zahlt. Die Vorschau enthält auch die noch offene Einnahme B nicht mehr, weil category_id die Prüfung des match_text durch elif vollständig verdrängt und dieselbe Buchung mehrfach verwendet werden kann.

**Korrekturrichtung:** Kategorie und Suchtext gemeinsam prüfen und eine Zahlung nicht ohne ausdrückliche Aufteilung mehreren unabhängigen Erwartungen zuordnen.

**Nachweis:** `results2.json` → `one_income_suppresses_two`.

### N11 — P2: Bereits erfasste zukünftige Buchungen verschwinden aus der Kontovorschau

Fundstelle: `app/services/outlook.py:128`.

Bei heutigem Datum 20.11. eine passende Buchung über −20 € am 25.11. erfassen und bis 30.11. vorschauen. Anfangssaldo 5.000 €, keine Ereignisse, Endsaldo 5.000 € statt 4.980 €. Die Monatsrechnung erkennt die zukünftige Zahlung bereits als bezahlt; der Anfangssaldo enthält sie noch nicht und die Vorschau ergänzt keine tatsächlichen künftigen Buchungen.

**Korrekturrichtung:** Künftige vorhandene Buchungen im Vorschauzeitraum als tatsächliche Ereignisse einbeziehen und zugehörige Planereignisse nur ohne Doppelzählung ersetzen.

**Nachweis:** `results2.json` → `future_booked_missing`.

### N12 — P2: Assistent summiert Splitbuchungen mit dem Gesamtbetrag

Fundstelle: `app/services/assistant.py:198`.

Eine Buchung über −100 € auf Internet −30 € und Telefon −70 € aufteilen. transactions_search mit Internet-Kategorie liefert −100 € statt −30 €. sum_by zeigt denselben Gesamtbetrag unter „ohne Kategorie“. Die Filter finden die Buchung über passende Splits, summiert wird danach aber Transaction.amount beziehungsweise die leere Kopfkategorie.

**Korrekturrichtung:** Auswertung über transaction_line und dieselben Filter wie in den Berichten durchführen. Auch Transferanteile von Splits ausschließen.

**Nachweis:** `results2.json` → `assistant_split_sum, assistant_split_groups`.

### N13 — P2: Vorgestern wird beim lokalen Erfassungs-Fallback zu gestern

Fundstelle: `app/services/assistant.py:308`.

Ohne KI „Vorgestern 18,50 Euro Mittagessen“ auswerten: Bei heute=20.11. liefert die API den 19.11. statt 18.11. Die Teiltextsuche findet gestern innerhalb von vorgestern zuerst.

**Korrekturrichtung:** Relative Datumswörter mit Wortgrenzen beziehungsweise längsten Treffern erkennen.

**Nachweis:** `results2.json` → `parse_day`.

### N14 — P2: Tausenderbetrag wird beim Erfassungs-Fallback um Faktor tausend verkleinert

Fundstelle: `app/services/assistant.py:308`.

Ohne KI „Heute 1.234,56 Euro Miete“ auswerten: Betrag −1.23 statt −1234.56. Der vorgeschaltete _AMOUNT-Ausdruck schneidet den Text bereits auf 1.23 ab; die spätere Tausenderbehandlung in _money kann den verlorenen Rest nicht reparieren.

**Korrekturrichtung:** Den vollständigen Betrag inklusive Tausender- und Dezimaltrenner extrahieren und danach einmal eindeutig normalisieren.

**Nachweis:** `results2.json` → `parse_amount`.

### N15 — P2: KI-Abschaltung des Profils wird nicht in allen Ausführungspfaden beachtet

Fundstelle: `app/services/assistant.py:320`.

ai.enabled=false speichern und /entries/parse aufrufen: Die gemockte KI wird trotzdem einmal aufgerufen, ai_used=true. Separat zeigt results3.json/disabled_queued_job_runs, dass ein vorher eingereihter Dokumentauftrag nach der Abschaltung weiterhin das Bildmodell aufruft. enqueue prüft die Einstellung nur bei Einreihung; Assistent und Jobausführung prüfen sie nicht.

**Korrekturrichtung:** Profileinstellung vor jeder KI-Anfrage und beim Beanspruchen wartender Aufträge prüfen. Lokalen Fallback beziehungsweise nachvollziehbaren pausierten Zustand verwenden.

**Nachweis:** `results2.json` → `disabled_ai_called`.

### N16 — P2: USD-Beleg wird einer gleich hohen EUR-Buchung vorgeschlagen

Fundstelle: `app/services/documents.py:198`.

Strukturierte Dokumentantwort mit betrag=100 und waehrung=USD an den echten Ergebnis-Handler übergeben. Zu einer zeitnahen EUR-Buchung über 100 € entsteht ein Zuordnungsvorschlag. Die extrahierte Währung wird bei der Suche vollständig ignoriert. Dies ist ein reproduzierter Handlerfall mit vorgegebener Modellantwort, kein Nachweis eines echten Modellfehlers.

**Korrekturrichtung:** Währung vor Betragsvergleich validieren. Bei Fremdwährung nur mit belegtem Umrechnungsbetrag zuordnen oder den Fall zur manuellen Klärung belassen.

**Nachweis:** `results2.json` → `foreign_currency_match`.

### N17 — P2: Manuelle Betragsänderung wirkt nach Einführung einer Historie nicht mehr im Budget

Fundstelle: `app/services/budget.py:89`.

Fixkost zunächst 20 €, ab Oktober über /amounts auf 30 € setzen. Danach über normalen PATCH auf 40 € ändern. API und Stammdatensatz zeigen 40 €, der Dezemberplan weiter 30 €, weil amount_for die unveränderte Historie verwendet.

**Korrekturrichtung:** Betragsänderungen über einen einheitlichen Pfad mit Gültigkeitsdatum führen; inkonsistente direkte Änderungen ablehnen oder in die Historie übernehmen.

**Nachweis:** `results2.json` → `fixed_patch_ignored`.

### N18 — P2: Mehrere Erstattungen können denselben Einkauf übersteigen

Fundstelle: `app/services/matching.py:160`.

Einkauf −100 € und zwei spätere Gutschriften von jeweils +100 € desselben Händlers anlegen. Beide Vorschläge werden akzeptiert und demselben Einkauf zugeordnet. Es gibt nur eine Eindeutigkeit je Erstattung, aber keine Prüfung bereits zugeordneter Gesamterstattungen.

**Korrekturrichtung:** Originalbuchung sperren, bereits verknüpfte Erstattungen summieren und Restbetrag bei Erkennung sowie Übernahme prüfen. Mehrerstattungen als gesonderten Klärungsfall behandeln.

**Nachweis:** `results2.json` → `over_refund`.

### N19 — P2: Automatik ignoriert explizite KI-Einschätzung „keine Verpflichtung“

Fundstelle: `app/services/recurring.py:358`.

Einen offenen Fixkostenvorschlag mit ai.ist_verpflichtung=false speichern, dann Automatik aktivieren und neu analysieren. Der Vorschlag wird trotzdem auto_applied. _is_clear berücksichtigt weder das negative Ergebnis noch seine Begründung. Bei initialem Auto-Modus läuft _automate zudem schon vor der KI-Anreicherung.

**Korrekturrichtung:** Negative semantische Evidenz als Sperrgrund behandeln und die Reihenfolge von Anreicherung und Freigabe definieren. Ein fehlendes KI-Ergebnis darf nicht mit positiver Einordnung gleichgesetzt werden.

**Nachweis:** `results2.json` → `negative_ai_auto`.

### N20 — P2: IBAN-Erkennung verdeckt weitere Referenz-Aliasse desselben Vertrags

Fundstelle: `app/services/merchants.py:50`.

Anbieter mit IBAN-Alias, Vertrag mit Referenz ABCD und zusätzlichem Referenz-Alias EFGH für denselben Vertrag anlegen. Bei gleicher IBAN wird ABCD dem Vertrag zugeordnet, EFGH aber nur dem Anbieter. Nach dem IBAN-Treffer werden Referenz-Aliasse übersprungen; die spätere Suche prüft nur Contract.reference.

**Korrekturrichtung:** Nach Bestimmung des Anbieters alle zugehörigen Vertragsmerkmale auswerten, auch die zusätzlichen Aliasse.

**Nachweis:** `results3.json` → `iban_hides_contract_alias`.

### N21 — P2: Referenz als Teilstring ordnet Buchungen dem falschen Vertrag zu

Fundstelle: `app/services/merchants.py:50`.

Zuerst Vertrag 1234, dann Vertrag 12345 anlegen. Resolver mit „Vertrag 12345“ liefert den ersten Vertrag 1234. Die Suche verwendet den ersten Teilstring-Treffer ohne Grenzen oder Mehrdeutigkeitsprüfung.

**Korrekturrichtung:** Referenzen tokenbasiert oder anhand expliziter Feldgrenzen vergleichen. Mehrere Treffer als mehrdeutig behandeln, statt Datenbankreihenfolge entscheiden zu lassen.

**Nachweis:** `results3.json` → `reference_prefix_wrong_contract`.

### N22 — P2: Abgelehnte Rückfragen verhindern weitere Rückfragen dauerhaft

Fundstelle: `app/services/clarify.py:97`.

Vier Anbieter mit jeweils klärungsbedürftigen Referenzen erzeugen. Es erscheinen drei Fragen. Alle ablehnen und erneut analysieren: Es bleiben dieselben drei abgelehnten Datensätze; die vierte Frage erscheint nicht. detect_questions begrenzt auf drei, bevor bereits entschiedene Vorschläge berücksichtigt werden.

**Korrekturrichtung:** Die Begrenzung auf tatsächlich offene beziehungsweise neu anzeigbare Fragen anwenden, nicht auf die ersten drei Rohfunde.

**Nachweis:** `results3.json` → `questions_starved`.

### N23 — P2: Endgültig fehlgeschlagener Dokumentauftrag bleibt in der Oberfläche wartend

Fundstelle: `app/services/ai_jobs.py:90`.

Drei ungültige Modellantworten für einen Dokumentauftrag simulieren. AiJob wird failed, Document bleibt pending ohne error. useDocuments fragt dadurch weiter alle drei Sekunden ab; der Nutzer erfährt nicht, dass keine Verarbeitung mehr läuft. Originaldatei in dieser Probe liegt nur in einem temporären Verzeichnis.

**Korrekturrichtung:** Terminalen Jobfehler an den fachlichen Dokumentstatus weitergeben und einen expliziten Wiederholungsweg anbieten.

**Nachweis:** `results3.json` → `failed_document_pending`.

### N24 — P2: Nicht aufeinanderfolgende Preisabweichungen ändern den Plan automatisch rückwirkend

Fundstelle: `app/services/upkeep.py:46`.

Bei 20 € Planbetrag nur August und November als Zahlungen über 30 € verknüpfen. Bei aktiver Betragsautomatik wird daraus eine dauerhafte Änderung ab August, obwohl für September und Oktober keine verknüpften Zahlungen vorliegen. Der dokumentierte Nachweis durch zwei aufeinanderfolgende Zahlungen wird nicht geprüft.

**Korrekturrichtung:** Abstände gegen den Vertragsrhythmus und fehlende Zwischenperioden prüfen. Bei unvollständiger Serie nur einen Hinweis geben; Gültigkeitsbeginn anhand vollständiger Evidenz bestimmen.

**Nachweis:** `results3.json` → `nonconsecutive_price_auto`.

### N25 — P3: Rücknahmequote verwendet den falschen Nenner

Fundstelle: `app/services/suggestions.py:231`.

Einen Vorschlag übernehmen und anschließend zurücknehmen. Die Metrik liefert revert_rate=null statt 1.0. Bereits zurückgenommene Fälle werden aus accepted entfernt und anschließend durch diesen Rest geteilt; mit mehreren Fällen sind auch Werte über 100 % möglich.

**Korrekturrichtung:** Zurücknahmen durch alle jemals übernommenen Fälle teilen: accepted + auto_applied + reverted, bei konsistentem Umgang mit direkt zurückgenommenen ChangeLog-Einträgen.

**Nachweis:** `results3.json` → `all_reverted_rate`.

### N26 — P2: Split-Vorlage scheitert bei bereits automatisch kategorisierter Buchung

Fundstelle: `app/services/matching.py:225`.

Zwei bestätigte gleichartige Aufteilungen dienen als Vorlage. Die nächste Buchung besitzt bereits eine KI-Kategorie, ist aber noch nicht bestätigt. Die Erkennung bietet eine Split-Vorlage an; ihre Übernahme scheitert mit 422 split_on_line_level. _split_apply übergibt neue Splits, löscht dabei aber die bestehende Kopfkategorie nicht. Die vorhandene Buchungsvalidierung lehnt diese Kombination korrekt ab.

**Korrekturrichtung:** Bei der Übernahme die Kopfkategorie zusammen mit den Splits konsistent umstellen und den aktuellen Bestätigungs-/Änderungsstand prüfen.

**Nachweis:** `results4.json` → `split_categorized_rejected`.

### N27 — P2: Zwei Fixkosten aus verschiedenen Splits derselben Buchung blockieren sich

Fundstelle: `app/services/recurring.py:319`.

Drei monatliche Sammelbuchungen von je 100 € mit 30 € Internet und 70 € Telefon anlegen. Die Erkennung liefert zwei Fixkostenvorschläge. Den ersten unter eigenem Namen übernehmen; der zweite scheitert trotz anderem Split mit 409 suggestion_stale. _validate prüft nur transaction_id und berücksichtigt split_id nicht.

**Korrekturrichtung:** Die Belegung je Buchungszeile anhand des Paars transaction_id/split_id prüfen, entsprechend dem Datenmodell für Zahlungsverknüpfungen.

**Nachweis:** `results4.json` → `second_split_fixed_rejected`.

### N28 — P2: Einnahmenänderung akzeptiert eine umgekehrte Betragsspanne

Fundstelle: `app/services/outlook.py:80`.

Erwartete Einnahme mit 1.000–2.000 € anlegen und per PATCH nur amount_min auf 3.000 € setzen. Die API akzeptiert 3.000–2.000 €; diese umgekehrte Spanne erscheint anschließend im Forecast. Die Bereichsprüfung existiert nur beim Create-Schema, nicht beim zusammengeführten Änderungsstand oder in der Datenbank.

**Korrekturrichtung:** Nach Zusammenführen bestehender und neuer Werte dieselbe Bereichsvalidierung wie beim Anlegen ausführen; eine passende DB-Constraint ergänzen.

**Nachweis:** `results4.json` → `income_inverted_range`.

### N29 — P2: Ungültige Vorschlagswerte führen zu HTTP 500 statt Validierungsfehler

Fundstelle: `app/routers/suggestions.py:45`.

Einen gültigen Fixkostenvorschlag mit Override amount="0" annehmen. Die Antwort lautet HTTP 500. Der Endpoint akzeptiert ein freies dict, anschließend wirft FixedCostCreate im Service eine unbehandelte Pydantic-ValidationError. Die normale Fixkostenanlage würde diese Eingabe mit 422 ablehnen.

**Korrekturrichtung:** Overrides je Vorschlagsart strukturiert validieren und Modellfehler in das vorhandene 422-Fehlerformat mit Feldbezug übersetzen.

**Nachweis:** `results4.json` → `invalid_override_500`.

### N30 — P2: Alter Erstattungsvorschlag überschreibt zwischenzeitliche manuelle Bestätigung

Fundstelle: `app/services/matching.py:160`.

Zu einer offenen Gutschrift einen Erstattungsvorschlag erzeugen. Die Gutschrift danach manuell als Gehalt kategorisieren und damit bestätigen. Übernahme des alten Vorschlags ersetzt die bestätigte Kategorie trotzdem durch die Ausgabenkategorie des Einkaufs. _refund_apply prüft lediglich Existenz und vorhandene Erstattungslinks.

**Korrekturrichtung:** Bestätigungsstatus, relevante Felder und Versionen erneut prüfen. Eine inzwischen getroffene manuelle Entscheidung macht den alten Vorschlag veraltet.

**Nachweis:** `results4.json` → `refund_overwrites_manual`.

### N31 — P2: Abgelehnter Fixkostenvorschlag erscheint bei einem weiteren Vertrag erneut

Fundstelle: `app/services/recurring.py:200`.

Eine Monatsserie über 20 € ablehnen. Danach eine zweite Serie über 70 € desselben Anbieters hinzufügen und neu erkennen lassen. Neben dem abgelehnten Eintrag entsteht ein neuer offener Vorschlag für dieselbe 20-€-Serie. Der Fingerprint enthält den Betragssuffix nur bei mehreren Clustern; die Identität ändert sich also durch einen unabhängigen zweiten Vertrag.

**Korrekturrichtung:** Den Fingerprint einer Serie unabhängig von der Zahl anderer Cluster stabil halten und bestehende Entscheidungen bei einer notwendigen Neugruppierung zuordnen.

**Nachweis:** `results5.json` → `rejected_reappears_after_second_contract`.

### N32 — P2: Namenskonflikt in der Automatik zerstört die Savepoint-Behandlung

Fundstelle: `app/services/suggestions.py:137`.

Eine inaktive Fixkost namens Anbieter behalten, eine neue eindeutige Serie desselben Namens erkennen und Automatik aktivieren. Refresh endet mit HTTP 500. create_fixed_cost ruft flush_or_conflict auf, das bei der Namenskollision session.rollback() auf der gesamten Transaktion ausführt. Danach versucht _automate, seinen bereits geschlossenen Savepoint zurückzurollen. Auch der äußere Analyse-Savepoint kann den Fehler nicht mehr isolieren.

**Korrekturrichtung:** In verschachtelten Transaktionen nur den zuständigen Savepoint zurückrollen; erwartete Eindeutigkeitskonflikte in prüfbare offene Vorschläge überführen. Kein vollständiges Session-Rollback innerhalb der Fachfunktion.

**Nachweis:** `results5.json` → `auto_collision_breaks_savepoint`.

### N33 — P2: Rücknahme einer Regel löscht eine zwischenzeitliche manuelle Änderung

Fundstelle: `app/services/upkeep.py:189`.

Regelvorschlag übernehmen, bei der erzeugten Regel case_sensitive=true setzen und anschließend den Vorschlag zurücknehmen. Die Rücknahme meldet Erfolg und löscht die Regel. RULE_FIELDS enthält case_sensitive nicht, deshalb bleibt diese tatsächliche manuelle Änderung beim Snapshot-Vergleich unsichtbar.

**Korrekturrichtung:** Alle fachlich veränderbaren Regelfelder einschließlich case_sensitive in den Änderungsvergleich aufnehmen oder einen verlässlichen Versionsstand vergleichen.

**Nachweis:** `results5.json` → `rule_revert_loses_manual_case`.

### N34 — P2: Automatische und manuelle Übernahme derselben Regel erzeugen Duplikate

Fundstelle: `app/services/suggestions.py:128`.

Ein automatischer Regellauf liest einen offenen Vorschlag. Während er vor der Anwendung wartet, übernimmt eine zweite Sitzung denselben Vorschlag manuell. Danach läuft die Automatik weiter: zwei identische Regeln entstehen, und der Vorschlag wird von accepted auf auto_applied überschrieben. Die Probe koordiniert zwei echte DB-Sitzungen mit Events am is_clear-Prüfpunkt; der Produktcode bleibt unverändert.

**Korrekturrichtung:** Auch automatische Übernahmen über dieselbe Zeilensperre und erneute Statusprüfung wie manuelle accept-Aufrufe führen. Status und Ergebnis müssen gemeinsam atomar geändert werden.

**Nachweis:** `results5.json` → `auto_manual_duplicate_rules`.

### N35 — P2: Importassistent beantwortet gewöhnliche Formatfehler mit Serverfehlern

Fundstelle: `app/services/import_assist.py:58`.

Eine Textdatei ohne CSV-Tabelle beim Profilentwurf hochladen: HTTP 500 durch unbehandelte ParseError. Im Vorschauendpoint führen gültiges JSON [] oder null ebenfalls zu 500, weil ohne Typprüfung options.get aufgerufen wird. Als Gegenprobe liefert column_map=null korrekt 422. Der Nutzer erhält für alltägliche falsche Dateien beziehungsweise Parameter keine verwertbare Diagnose.

**Korrekturrichtung:** Parserfehler in strukturierte Eingabefehler umwandeln und die Profiloptionen vor Zugriff mit einem Schema validieren.

**Nachweis:** `results5.json` → `import_errors_500`.

### N36 — P2: KI zur Spaltenerkennung erhält bei unbekanntem Format keine Beispielwerte

Fundstelle: `app/services/import_assist.py:29`.

CSV mit unbekannten Spalten Tag/Wert/Partner/Notiz und gültiger Datenzeile an den KI-Profilentwurf übergeben. Der aufgezeichnete Datenblock enthält beispielzeilen=[]. _ai_roles verwendet die bereits normalisierte Parser-Vorschau; genau die fehlt aber, solange notwendige Rollen noch unbekannt sind. Damit stehen der KI für die geforderte Inhaltszuordnung nur Überschriften zur Verfügung. Die Probe prüft die tatsächlich gesendeten Daten, nicht die Antwortqualität eines externen Modells.

**Korrekturrichtung:** Eine begrenzte Rohvorschau mit Originalspaltennamen vor der fachlichen Parserprüfung bereitstellen und der KI diese Zeilen senden.

**Nachweis:** `results5.json` → `ai_draft_no_samples`.

### N37 — P1: Backup lässt alle Belege aus, solange keine Import-Unterordner existieren

Fundstelle: `scripts/backup.sh:133`.

Nur einen Beleg hochladen, aber noch keine Kontoauszüge importieren; IMPORT_DIR ist leer, DOCUMENT_DIR enthält die Datei. Das echte Backup-Skript beendet sich erfolgreich, erzeugt jedoch ein leeres Dateiarchiv. Die Dokumentaufnahme liegt ausschließlich im else-Zweig vorhandener Import-Unterordner. Im Datenbankdump stehen die Dokumentmetadaten, das Original ist nach Wiederherstellung verloren.

**Korrekturrichtung:** Dokument- und Importquellen unabhängig sammeln. Ein vorhandenes DOCUMENT_DIR muss auch ohne Import-Unterordner gesichert werden; die resultierenden Dateipfade gegen den Dump prüfen.

**Nachweis:** `results6.json` → `backup_without_imports_omits_documents`.

### N38 — P1: Restore überschreibt vorhandene Belege ohne --yes oder Rückfrage

Fundstelle: `scripts/restore.sh:150`.

Eine echte Sicherung mit Dokument erzeugen, am Ziel eine abweichende Datei desselben Dokumentnamens ablegen und in eine neue Probe-Datenbank ohne --yes wiederherstellen. Das Skript beendet sich erfolgreich und ersetzt die bestehende Datei. Die Konfliktsuche prüft IMPORT_DIR/documents/datei, die Extraktion schreibt aber nach DOCUMENT_DIR/datei. Die Probe verwendet nur temporäre Dateien und eine ausdrücklich benannte neue Datenbank.

**Korrekturrichtung:** Archivpfade vor jedem Schreiben auf ihren tatsächlichen Zielordner abbilden. Dokumentkonflikte vor der Datenbankwiederherstellung ebenso wie Importkonflikte erkennen und ohne --yes abbrechen.

**Nachweis:** `results6.json` → `restore_overwrites_document_without_yes`.

### N39 — P2: Docker-Betrieb richtet keinen beschreibbaren gemeinsamen Dokumentordner ein

Fundstelle: `Dockerfile:44`.

DOCUMENT_DIR bleibt im Image beim relativen Standard documents und zeigt damit auf /srv/finanzplaner/documents. Das Dockerfile wechselt zu UID 1000, macht aber ausschließlich /data/imports beschreibbar; der Arbeitsordner ist root-eigen. Compose mountet für App und Worker nur das Importvolume. Der Upload kann den Standardordner daher im unveränderten Image nicht anlegen. Selbst eine isolierte Rechtekorrektur würde Dateien noch nicht zwischen App und Worker teilen oder über Neuerstellungen erhalten.

**Korrekturrichtung:** DOCUMENT_DIR auf einen persistenten, für UID 1000 beschreibbaren Pfad setzen und dasselbe Volume in App und Worker einbinden. Als Konfigurationsbefund belegt; ein Containerlauf war hier mangels Docker/Podman nicht möglich.

**Nachweis:** `statisch` → `Dockerfile, docker-compose.yml, app/config.py`.

## Prüfumfang und verbleibende Arbeit

Die Liste der 158 im letzten Merge geänderten Dateien liegt in [changed-files.txt](pruefung-ki-2026-11-05/changed-files.txt). Der aktuelle Branch entspricht origin/main; als Änderungsinventar dient deshalb der letzte Merge gegen seinen ersten Elternstand. Der vollständige Merge-Diff ist noch nicht abschließend geprüft. Dieser Bericht ist ausdrücklich ein Zwischenstand.

Vollständig gelesen und in die Prüfung einbezogen:

- `app/services/suggestions.py`
- `app/services/changes.py`
- `app/services/recurring.py`
- `app/services/budget.py`
- `app/services/ai_jobs.py`
- `app/services/settings.py`
- `app/services/analysis.py`
- `app/services/upkeep.py`
- `app/services/matching.py`
- `app/services/documents.py`
- `app/services/outlook.py`
- `app/services/coverage.py`
- `app/services/ai_gateway.py`
- `app/services/assistant.py`
- `app/services/clarify.py`
- `app/services/merchants.py`
- `app/services/import_assist.py`
- `app/importers/detect.py`
- `app/routers/suggestions.py`
- `app/routers/documents.py`
- `app/routers/budget.py`
- `app/routers/outlook.py`
- `app/routers/assistant.py`
- `app/routers/merchants.py`
- `app/schemas/outlook.py`
- `app/routers/imports.py`
- `app/errors.py`
- `app/worker.py`
- `app/services/common.py`
- `app/models/rule.py`
- `tests/api/test_ki_phase4.py`
- `scripts/backup.sh`
- `scripts/restore.sh`
- `scripts/lib.sh`
- `Dockerfile`
- `docker/entrypoint.sh`
- `docker-compose.yml`
- `app/config.py`
- `frontend/src/api/documents.ts`
- `frontend/src/pages/einstellungen/automation.ts`

Weitere Modelle, Buchungsservices, Frontendkomponenten und vorhandene Tests wurden gezielt an den relevanten Stellen gelesen; eine vollständige Prüfung dieser Dateien wird damit nicht behauptet. Insbesondere Frontend, Migrationen, Importe, parallele Ausführungen und ältere Kreditpfade bleiben im weiteren Prüfumfang. Die bestehenden KI-Tests `tests/api/test_ki_phase1.py` bis `test_ki_phase7.py` sowie `test_scenarios_recurring.py` wurden anschließend auf einer weiteren isolierten Testdatenbank ausgeführt: **103 bestanden, 1 xfailed** (18,84 s). [Testprotokoll](pruefung-ki-2026-11-05/baseline-tests.log), [isolierter Runner](pruefung-ki-2026-11-05/baseline.py). Der Lauf war vor Ergänzung der Befunde N31–N39; seitdem wurden keine Produktdateien geändert. Die vollständige projektweite Regression ist weiterhin offen. Die zusätzlichen Nachweise schließen Lücken in den vorhandenen Szenarien; grüne Bestandstests widerlegen sie nicht.

## Sicherheitscheck des Review-Skills (Zwischenstand)

| Prüfpunkt | Ergebnis im bisher geprüften Ausschnitt |
|---|---|
| Injection | Strukturierte KI-Werkzeugauswahl und ORM-Pfade gelesen; keine bestätigte SQL-/Shell-Injection. Manipulation durch Dokumenttexte nicht mit realem Modell getestet. |
| XSS | Kein neuer bestätigter Befund; vollständiges Rendering und Dateivorschau noch offen. |
| Authentifizierung | Dokumentiertes passwortloses Heimnetzmodell; nicht als neuer Fehler gezählt. |
| Autorisierung/IDOR | Profilprüfungen in gelesenen Routen/Services vorhanden; vollständige Negativmatrix und alle direkten Handlerpfade noch offen. |
| CSRF | In diesem Abschnitt nicht vollständig verifiziert. |
| Race Conditions | Fehlende erneute Validierung bereits sequenziell reproduziert (N01/N06/N07); N34 zusätzlich mit zwei kontrolliert überlappenden DB-Sitzungen reproduziert; weitere Parallelitätsfälle offen. |
| Sessions | Datenbanksitzungen der neuen Jobpfade gelesen; keine browserseitige Sessionprüfung abgeschlossen. |
| Kryptografie | SHA-256 dient hier Cache-/Dateiidentität; kein neuer kryptografischer Befund. Vollständige Secrets-Prüfung noch offen. |
| Informationsabfluss | Profilbezogene KI-Abschaltung wird umgangen (N15); keine reale Datenübertragung in den Proben. |
| DoS | Dauerpolling nach endgültigem Dokumentfehler (N23); Größen-/Komplexitätsgrenzen für PDF-Verarbeitung noch nicht vollständig verifiziert. |
| Fachliche Logik | Konkrete Fehler mit Assertions dokumentiert; keine pauschale Fehlerfreiheit der übrigen Pfade. Backup-/Restore-Datenverlust in N37/N38 ebenfalls mit echten Skripten nachgewiesen. |

## Nächste Prüfschritte

- Weitere veraltete Vorschläge, automatische Splits und Rücknahmen mit nachfolgenden manuellen Änderungen prüfen.
- Mehrere parallele Analysen/Übernahmen sowie Job-Abschaltung und Neustart untersuchen.
- Importdiagnose, Vorschauparameter und Belegfehlerpfade mit ungültigen Eingaben testen.
- Frontend-Formulare, Cache-Aktualisierung, Profilwechsel und Browserabläufe überprüfen.
- Ältere Berichte mit aktuellem Stand abgleichen und noch offene fachliche Fälle erneut testen.
