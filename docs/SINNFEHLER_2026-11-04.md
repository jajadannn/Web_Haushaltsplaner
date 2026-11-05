# Fachliche Prüfung: Sinn- und Logikfehler – 4. November 2026

Geprüfter Stand: `1bc52a2`. Ergänzung zum bisherigen Sicherheits- und Funktionsreview; keine Änderungen am Anwendungscode.

**9 zusätzliche Befunde: 1 × P1, 7 × P2, 1 × P3.** Dazu kommen zwei weitergehende Reproduktionen bereits dokumentierter Fehler. P1 steht für hohe Priorität bei falschen Finanzdaten, P2 für relevante fachliche oder Bedienfehler, P3 für eine irreführende Bezeichnung. Die Kennungen S1–S9 sind unabhängig von F1–F16 des vorherigen Berichts.

## Maßstab

Geprüft wurden folgende fachliche Eigenschaften aus Code, API-Beschreibungen und Oberfläche:

- Kontotransfers erhalten das Gesamtvermögen; Splitbeträge und Erstattungen stimmen mit Auswertungen überein.
- Kreditrückzahlungen überschreiten die am relevanten Datum bestehende Schuld nicht; Stornos erhalten einen konsistenten Zahlungs- und Fälligkeitsverlauf.
- Zinsen entsprechen der dokumentierten Berechnungsregel und dem Kapital im jeweiligen Zeitraum.
- Historische Berichte und ihre Beschriftungen beziehen sich auf einen erkennbaren Stichtag.
- Fortschritt und Zahlungsstatus stammen aus tatsächlichen Ereignissen; automatische Vorschläge gelten nicht als Nutzerbestätigung.
- Fixkostenvorschläge unterscheiden beobachtete Wiederholung von monatlicher Fälligkeit.
- Eine rein beschreibende Änderung verändert keine Kreditkonditionen.

## Befunde

| Kennung | Priorität | Problem |
|---|---|---|
| S1 | P2 | Das Löschen einer bereits getilgten Belastung erzeugt negative Restschuld |
| S2 | P1 | Privatkredite verzinsen den gesamten Zeitraum mit dem falschen Kapitalstand |
| S3 | P2 | Storno nach einer Ratenpause entfernt die ursprüngliche Fälligkeit |
| S4 | P2 | Historischer Kreditbericht vermischt verschiedene Stichtage |
| S5 | P2 | Tilgungsfortschritt verwendet Planwerte statt tatsächlicher Zahlungen |
| S6 | P2 | Quartalszahlungen werden als monatliche Fixkosten vorgeschlagen |
| S7 | P2 | Unbestätigte Regel- und KI-Vorschläge erscheinen als geprüft |
| S8 | P3 | Kapitalisierte Zinsen werden als bereits gezahlt bezeichnet |
| S9 | P2 | Buchungssummen behandeln Erstattungen als Einnahmen |

### S1 – P2: Das Löschen einer bereits getilgten Belastung erzeugt negative Restschuld

Fundstelle: [app/services/loans/payments.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:316).

Privatkredit mit 1.000 € Restschuld anlegen, 100 € dem Kreditkonto belasten, anschließend 1.100 € zurückzahlen und die Belastung löschen. Alle Schritte werden akzeptiert; danach meldet der Kredit `remaining_debt=-100.00` und `status=paid_off`. Der normale Zahlungspfad verhindert Tilgung oberhalb der Restschuld, der nachträgliche Löschpfad umgeht diese fachliche Grenze. Der positive Kontosaldo ist rechnerisch die Folge der Rücknahme; problematisch ist der ungesicherte Übergang in einen Überzahlungszustand, den die Kreditlogik sonst nicht unterstützt und pauschal als abbezahlt behandelt.

**Korrekturrichtung:** Abhängige spätere Zahlungen vor dem Entfernen einer Belastung prüfen. Die Änderung ablehnen und eine geordnete Rückabwicklung verlangen oder alle betroffenen Zahlungen ausdrücklich konsistent neu berechnen. Eine negative Restschuld darf nicht stillschweigend als normal abbezahlter Kredit behandelt werden.

**Nachweis:** `delete_charge_after_payoff` im Nachweisordner.

### S2 – P1: Privatkredite verzinsen den gesamten Zeitraum mit dem falschen Kapitalstand

Fundstelle: [app/services/loans/payments.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:122).

Ohne Tilgungsplan wird die aktuelle Gesamtrestschuld mit den Tagen seit der letzten Zahlung multipliziert. Bei 1.000 € am 1. Januar, 1.000 € zusätzlicher Belastung am 6. Januar und einer Zahlung am 11. Januar werden bei 36,5 % Jahreszins 20 € Zinsen gebucht. Nach der im Projekt dokumentierten act/365-Regel wären es 15 €: fünf Tage auf 1.000 € und fünf Tage auf 2.000 €. Die Tilgung fällt dadurch 5 € zu niedrig aus. Außerdem umfasst `remaining_debt()` ohne Stichtag sogar spätere Buchungen: Eine Belastung von 100 € am 1. März ermöglicht bereits am 1. Februar eine Tilgung von 1.100 € auf ursprünglich 1.000 €. Der historische Februarsaldo wird −100 € Restschuld, obwohl die Überzahlungsprüfung vorhanden ist.

**Korrekturrichtung:** Zinsen entlang der tatsächlich datierten Saldoänderungen abschnittsweise berechnen. Restschuldprüfungen auf den Zahlungstag beziehen und die Konsistenz nachfolgender Ereignisse prüfen. Alternativ nicht unterstützte Kombinationen aus freien Zahlungen und Kapitaländerungen explizit ablehnen.

**Nachweis:** `private_charge_interest_interval; future_charge_allows_early_overpayment` im Nachweisordner.

### S3 – P2: Storno nach einer Ratenpause entfernt die ursprüngliche Fälligkeit

Fundstelle: [app/services/loans/payments.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py:272).

Rate 1 vom 31. Januar bezahlen, Rate 2 vom 28. Februar aussetzen, dann die letzte Zahlung stornieren. Anschließend fehlt Rate 1 vollständig. Der Plan beginnt mit der ausgesetzten Rate 2, die nächste offene Rate ist erst am 31. März. `delete_payment()` macht Rate 1 wieder offen; `rebuild_schedule()` entfernt sie anschließend und setzt hinter der letzten ausgesetzten Rate fort. Die Restschuld wird zwar erhöht, die ursprüngliche überfällige Forderung aber aus dem Kalender entfernt.

**Korrekturrichtung:** Storno gegen nachfolgende Planereignisse absichern. Entweder zunächst die spätere Ratenpause zurücknehmen lassen oder den Plan ab dem tatsächlich zurückgenommenen Ereignis neu aufbauen und die Pause erhalten.

**Nachweis:** `cancel_after_skip` im Nachweisordner.

### S4 – P2: Historischer Kreditbericht vermischt verschiedene Stichtage

Fundstelle: [app/services/reports.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/reports.py:316).

Ein Kredit über 1.000 € erhält erst am 28. Februar eine Zahlung von 100 €. Für `until=2026-01-31&months=1` liefert derselbe Bericht oben 900 € Restschuld, in der einzigen Monatsspalte aber korrekt 1.000 €. Der Frontend-Bericht zeigt beides im ausgewählten Januarzeitraum ohne Kennzeichnung des abweichenden Stands. Auch Status, nächste Rate und monatliche Belastung stammen aus dem aktuellen Plan.

**Korrekturrichtung:** Stichtagsbezogene Restschuld mit `until` berechnen. Historischen Status und Belastung entweder aus geeigneten historischen Daten ableiten oder aktuelle Kennzahlen ausdrücklich als aktuellen Stand getrennt kennzeichnen.

**Nachweis:** `historical_loan_report` im Nachweisordner.

### S5 – P2: Tilgungsfortschritt verwendet Planwerte statt tatsächlicher Zahlungen

Fundstelle: [frontend/src/lib/loanProgress.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/lib/loanProgress.ts:12).

Ohne angegebene ursprüngliche Kreditsumme summiert der Fortschrittsbalken `planned_principal` bezahlter Planzeilen. Bei 1.000 € Restschuld, 12 % Jahreszins und geplanter Rate von 100 € enthält die erste Zeile 90 € geplante Tilgung. Tatsächlich gezahlte 250 € tilgen aber 240 €. Die reale Restschuld beträgt 760 €. Die unveränderte Frontendfunktion berechnet 90/(90+760) = 10,59 % und zeigt gerundet 11 % „Bereits getilgt“ statt 24 %.

**Korrekturrichtung:** Tatsächliche Tilgungsanteile aus LoanPayment verwenden beziehungsweise die Kennzahl im Backend bereitstellen. Belastungen, Stornos und Kredite ohne Plan müssen dieselbe definierte Fortschrittsbasis verwenden.

**Nachweis:** `progress; frontend-nachweise.json: progress` im Nachweisordner.

### S6 – P2: Quartalszahlungen werden als monatliche Fixkosten vorgeschlagen

Fundstelle: [frontend/src/pages/einstellungen/fixedCostCandidates.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/einstellungen/fixedCostCandidates.ts:52).

Zwei Zahlungen zu je 90 € an denselben Empfänger am 15. Juli und 15. Oktober ergeben `monthly=true`. Der Algorithmus zählt nur verschiedene Monate und ähnliche Beträge, prüft aber die zeitlichen Abstände nicht. Das UI zeigt den Kandidaten als „monatlich“ und übernimmt 90 € in einen ausschließlich monatlichen Fixkostenposten. Damit kann aus 90 € pro Quartal eine Reservierung von 90 € pro Monat werden.

**Korrekturrichtung:** Abstände und aufeinanderfolgende Monate berücksichtigen. Bei wenigen oder lückenhaften Beobachtungen nur einen unbestätigten Wiederholungshinweis anzeigen. Nichtmonatliche Intervalle unterstützen oder vor Übernahme ausdrücklich nach monatlichem Planbetrag fragen.

**Nachweis:** `frontend-nachweise.json: quarterly` im Nachweisordner.

### S7 – P2: Unbestätigte Regel- und KI-Vorschläge erscheinen als geprüft

Fundstelle: [frontend/src/pages/buchungen/TransactionsPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/buchungen/TransactionsPage.tsx:201).

Eine Buchung wird per Regel auf `auto_categorized` gesetzt und bleibt laut API in der Prüfliste. In der tatsächlich serverseitig gerenderten Buchungsliste erhält sie trotzdem das Häkchen mit Titel „geprüft“. „Nur ungeprüfte“ sendet ausschließlich `review_status=needs_review` und blendet sie aus: API-Prüfliste enthält eine Buchung, der Filter null. Dasselbe Zustandsproblem betrifft KI-Vorschläge. Automatische Zuordnung wird so mit Bestätigung verwechselt.

**Korrekturrichtung:** Alle drei Zustände getrennt abbilden: ohne Kategorie, automatisch vorgeschlagen und vom Nutzer bestätigt. Filter und Symbolik entsprechend vereinheitlichen; falls nur fehlende Kategorien gemeint sind, den Filter genau so benennen.

**Nachweis:** `unreviewed_rule_suggestion; frontend-nachweise.json; render-nachweise.json` im Nachweisordner.

### S8 – P3: Kapitalisierte Zinsen werden als bereits gezahlt bezeichnet

Fundstelle: [frontend/src/pages/berichte/ReportsPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/berichte/ReportsPage.tsx:366).

Bei einem Privatkredit werden 20 € Zinsen ausschließlich der Schuld zugeschlagen; es gibt keine Zahlung. Die Kredit-Jahreszusammenfassung liefert korrekt `interest_paid=0` und `interest_charged=20`. Der allgemeine Kreditbericht addiert die Belastung jedoch in `interest_paid_by_year`; das Frontend beschriftet diese 20 € als „Gezahlte Zinsen“. Ein vorhandener Test schreibt die Addition ausdrücklich fest. Der Befund betrifft daher die fachliche Bedeutung und Darstellung, nicht eine unbeabsichtigte Änderung des bisherigen Tests.

**Korrekturrichtung:** Gezahlte und belastete/kapitalisierte Zinsen getrennt darstellen. Falls die Summe bewusst gewünscht ist, sie als gesamte erfasste Zinskosten bezeichnen, nicht als Zahlung.

**Nachweis:** `capitalized_interest_label` im Nachweisordner.

### S9 – P2: Buchungssummen behandeln Erstattungen als Einnahmen

Fundstelle: [frontend/src/pages/buchungen/TransactionsPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/buchungen/TransactionsPage.tsx:81).

Ein Einkauf über 100 € mit einer Erstattung von 30 € in derselben Ausgabenkategorie ergibt im Backendbericht 70 € Ausgaben. Die echte TransactionsPage-Komponente rendert für dieselbe Betragskonstellation dagegen „Einnahmen 30,00 €“ und „Ausgaben 100,00 €“, weil nur das Vorzeichen ausgewertet wird. Damit haben identische Begriffe in Buchungsliste, Budget und Berichten unterschiedliche Bedeutungen; die Erstattung wird scheinbar zu Einkommen.

**Korrekturrichtung:** Für Einnahmen/Ausgaben dieselbe Kategorie- und Erstattungslogik wie im Backend verwenden. Sind bewusst Brutto-Geldbewegungen gemeint, die Felder als Zu-/Abflüsse bezeichnen und diese Unterscheidung erklären.

**Nachweis:** `controls; render-nachweise.json` im Nachweisordner.

## Vertiefungen bereits bekannter Befunde

**F15 – Umbenennen verändert auch ein Tilgungsdarlehen:** Nach einer von zehn gezahlten Raten hat der Kredit neun offene Raten. Der vom vorhandenen Formular erzeugte PATCH für eine Namensänderung sendet erneut die ursprüngliche Laufzeit von zehn Monaten. Danach sind zehn statt neun Raten offen. Die Probe verwendet den tatsächlichen API-Pfad und die aus dem Formularcode abgeleiteten Planfelder; sie ist kein erneuter Browserklicktest. Nachweis: `installment_rename_extends_term`.

**F3/F4 – Zahlung im Folgemonat:** Eine am 28. Februar fällige Rate wird am 1. März bezahlt. Im März existiert daneben die noch offene Märzrate. Bei 1.000 € März-Einnahmen, 100 € tatsächlichem Abfluss und 100 € weiterer Reservierung zeigt der Planer 900 € statt 800 € Spielraum. Die Februaransicht markiert die Rate rückblickend als bezahlt, die Märzansicht enthält den tatsächlichen Abfluss nicht zusätzlich. Nachweis: `payment_in_following_month`. Die Korrektur muss geplante Verpflichtungen und tatsächliche Zahlungen nach Buchungs- und Fälligkeitsmonat getrennt verrechnen.

Die früheren Befunde bleiben in [docs/PRUEFBERICHT_2026-11-03.md](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/PRUEFBERICHT_2026-11-03.md) dokumentiert; die Vertiefungen werden nicht als weitere unabhängige Fehler gezählt.

## Nachweise und Kontrollproben

Die Backendprobe erzeugt eine eigene PostgreSQL-Datenbank, migriert sie auf den aktuellen Stand, führt reguläre API-Aufrufe mit synthetischen Daten aus und entfernt die Datenbank im `finally`-Block. Es werden keine Anwendungsdatensätze verwendet. Die Zinsformel wird anhand der projektinternen act/365-Konvention geprüft, nicht anhand externer Bankbedingungen.

Die Frontendproben laden die unveränderten Projektmodule über Vite. Für Summen und Prüfstatus wird die tatsächliche TransactionsPage mit synthetisch vorbelegtem Query-Cache serverseitig gerendert. Das ist ein Komponentennachweis, kein vollständiger interaktiver Browserlauf.

Positive Kontrollen bestanden: Eine interne Umbuchung verändert das Gesamtvermögen nicht; ihr Löschen entfernt auch die Gegenseite. Ein Einkauf von 100 € mit 30 € Erstattung ergibt im Backend korrekt 70 € Ausgaben und 4.930 € Vermögen aus 5.000 € Anfangsbestand. Eine weitere Ausgabe mit Splits von 70 € und 30 € ergibt 170 € Gesamtausgaben und 4.830 € Vermögen. Die API-Prüfliste behält automatische Vorschläge bis zur Bestätigung korrekt bei.

Die vollständigen Tests des unveränderten Stands wurden im vorherigen Review ausgeführt: 780 Backend- und 97 Frontend-Tests bestanden. Für diese Vertiefung wurden gezielte Szenarien ergänzt; ein erneuter vollständiger Lauf war ohne Änderungen am Anwendungscode nicht erforderlich. Die neue Reproduktionsprobe wurde nach Ergänzungen vollständig erfolgreich ausgeführt. Grüne Bestandsprüfungen beweisen nicht die fachliche Richtigkeit der oben genannten Fälle; insbesondere die Bezeichnung kapitalisierter Zinsen wird durch einen bestehenden Test nicht hinterfragt.

- [docs/pruefung-sinnfehler-2026-11-04/nachweise.json](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/pruefung-sinnfehler-2026-11-04/nachweise.json)
- [docs/pruefung-sinnfehler-2026-11-04/frontend-nachweise.json](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/pruefung-sinnfehler-2026-11-04/frontend-nachweise.json)
- [docs/pruefung-sinnfehler-2026-11-04/render-nachweise.json](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/pruefung-sinnfehler-2026-11-04/render-nachweise.json)
- [docs/pruefung-sinnfehler-2026-11-04/probe_logic.py](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/pruefung-sinnfehler-2026-11-04/probe_logic.py)
- [docs/pruefung-sinnfehler-2026-11-04/probe_frontend.mjs](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/pruefung-sinnfehler-2026-11-04/probe_frontend.mjs)
- [docs/pruefung-sinnfehler-2026-11-04/probe_render.mjs](/home/fabian/Dokumente/Web_Haushaltsplaner/docs/pruefung-sinnfehler-2026-11-04/probe_render.mjs)

## Prüfumfang und Grenzen

Vollständig in dieser Vertiefung gelesen: die nachfolgend aufgeführten Dateien. Weitere Dateien wurden anhand von Fundstellen, Testausschnitten und dem vorausgegangenen Review einbezogen; daraus wird keine erneute vollständige Einzeldateiprüfung abgeleitet.

- [app/services/budget.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/budget.py)
- [app/services/balances.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/balances.py)
- [app/services/reports.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/reports.py)
- [app/services/loans/schedule.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/schedule.py)
- [app/services/loans/payments.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/loans/payments.py)
- [app/services/accounts.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/accounts.py)
- [app/services/transactions.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/transactions.py)
- [app/services/dedup.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/dedup.py)
- [app/services/import_commit.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/services/import_commit.py)
- [app/routers/loans.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/routers/loans.py)
- [app/routers/transactions.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/routers/transactions.py)
- [app/schemas/budget.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/schemas/budget.py)
- [app/schemas/loan.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/schemas/loan.py)
- [app/schemas/rule.py](/home/fabian/Dokumente/Web_Haushaltsplaner/app/schemas/rule.py)
- [frontend/src/lib/loanProgress.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/lib/loanProgress.ts)
- [frontend/src/lib/moneyInput.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/lib/moneyInput.ts)
- [frontend/src/lib/dates.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/lib/dates.ts)
- [frontend/src/pages/start/StartPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/start/StartPage.tsx)
- [frontend/src/pages/start/parts.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/start/parts.tsx)
- [frontend/src/pages/berichte/ReportsPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/berichte/ReportsPage.tsx)
- [frontend/src/pages/kredite/LoanDialogs.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/kredite/LoanDialogs.tsx)
- [frontend/src/pages/buchungen/filters.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/buchungen/filters.ts)
- [frontend/src/pages/buchungen/TransactionsPage.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/buchungen/TransactionsPage.tsx)
- [frontend/src/app/AddEntry.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/app/AddEntry.tsx)
- [frontend/src/app/ProfileContext.tsx](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/app/ProfileContext.tsx)
- [frontend/src/pages/einstellungen/fixedCostCandidates.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/einstellungen/fixedCostCandidates.ts)
- [frontend/src/pages/einstellungen/fixedCostCandidates.test.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/pages/einstellungen/fixedCostCandidates.test.ts)
- [frontend/src/wall/display.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/src/wall/display.ts)
- [tests/api/test_budget.py](/home/fabian/Dokumente/Web_Haushaltsplaner/tests/api/test_budget.py)
- [frontend/vite.config.ts](/home/fabian/Dokumente/Web_Haushaltsplaner/frontend/vite.config.ts)

Sicherheitscheck des Review-Skills: Injection, XSS, Authentifizierung, Autorisierung/IDOR, CSRF, Sessions, Kryptografie, Informationsabfluss und DoS wurden hinsichtlich neu berührter Datenpfade eingeordnet; diese Vertiefung liefert dort keinen zusätzlichen bestätigten Sicherheitsbefund und ersetzt keinen Penetrationstest. Das bewusst passwortlose Heimnetzmodell bleibt die dokumentierte Vertrauensgrenze. Parallelität ist weiterhin Gegenstand von F2; die neuen Stornofehler benötigen keine parallelen Requests. Die fachliche Logik ist durch die oben genannten positiven und negativen Szenarien geprüft. Unveränderte Ergebnisse und Grenzen des vorherigen Sicherheitsreviews gelten weiter, ohne eine pauschale Fehlerfreiheit zu behaupten.

Nicht vollständig verifiziert: sämtliche Kombinationen von Importhistorie, Kontowechseln und Vertragsänderungen; konkrete Bank-Zinskonventionen außerhalb der implementierten Formel; historische Konditionen, die das Datenmodell nicht speichert; vollständige Browserinteraktion der neuen Szenarien. Unklare Produktregeln wie Rücklagen aus Vormonaten oder die untermonatige Aktivierung einer Fixkost wurden nicht ohne Spezifikation als bestätigte Rechenfehler gewertet. Eine automatische Reparatur, fachliche Umgestaltung oder Veröffentlichung war nicht beauftragt und wurde nicht durchgeführt.
