# Umsetzungsplan: KI-Ausbau des Finanzplaners

Stand: 05.11.2026. Grundlage: [KI_INTEGRATION_IDEEN.md](KI_INTEGRATION_IDEEN.md) (Ideen 01–22) und der Code nach den Korrekturen aus den Prüfberichten vom 3./4. November (Branch `fix/pruefberichte-2026-11`). Dieser Plan ist zum späteren Umsetzen gedacht. Phase 1 ist bis auf Dateien, Tabellen, Endpunkte und Tests ausgearbeitet; die späteren Phasen sind gröber und werden vor ihrem Start verfeinert.

## Leitlinien für alle Phasen

1. **Rechnen im Backend, Formulieren durch die KI.** Beträge (Decimal), Intervalle, Statistiken, Duplikat- und Profilprüfungen liegen in Python-Services. Die KI liefert nur Text, Namen und strukturierte Vorschläge, die gegen erlaubte Felder, IDs und Profilzugehörigkeit geprüft werden.
2. **Vor dem Schreiben neu prüfen.** Jede Übernahme sperrt die betroffenen Zeilen und validiert den aktuellen Datenstand erneut (Muster aus F16: `ai_review.review_one`). Manuelle Änderungen gewinnen immer.
3. **Buchungstexte sind Daten.** Verwendungszwecke und Dokumentinhalte werden der KI nur als markierte Daten übergeben; Antworten werden ausschließlich als JSON nach Schema ausgewertet.
4. **Erst Vorschlag, dann gemessene Automatik.** Automatische Übernahmen erst, wenn der Prüfsatz und reale Annahme-/Korrekturquoten sie stützen; nie auf Grundlage der Selbsteinschätzung des Modells.
5. **Ohne KI lauffähig.** Ist `AI_URL` nicht gesetzt oder der Server nicht erreichbar, laufen alle deterministischen Teile weiter; KI-Anteile werden nachgeholt.
6. **Test-first.** Je Funktion zuerst Regressions- bzw. Szenariotests (wie `tests/api/test_pruefbericht_2026_11.py`), dann Umsetzung.

## Überblick

| Phase | Inhalt | Ideen | Abhängigkeit |
|---|---|---|---|
| 0 | Prüfsatz und Messgrundlage | – | keine |
| 1 | Fixkostenmodell mit Rhythmus und fester Zahlungsverknüpfung, Vorschlagsspeicher, Fixkostenerkennung im Backend | 01, Teil von 09 | 0 |
| 2 | KI-Namen/Vertragszuordnung, Probelauf, Änderungsverlauf, optionale automatische Übernahme | 01, 02, 09 | 1 |
| 3 | Betragsänderungen, Regelvorschläge aus Korrekturen, gemeinsame Prüfung ähnlicher Buchungen | 03, 04, 10, 22 | 1–2 |
| 4 | Importassistent, Importdiagnose, gezielte Rückfragen, Konsistenzhinweise | 11, 12, 19, 20 | 1 |
| 5 | Importabdeckung, fehlende Zahlungen, erwartete Einnahmen, Kontovorschau, Jahreskosten | 05, 16, 17, 18 | 1–2 |
| 6 | Monatserklärungen, lesende Fragen, Buchungen in natürlicher Sprache | 07, 08, 21 | 1 |
| 7 | Erstattungen, Split-Vorlagen, Belege und Verträge aus Dokumenten | 06, 13, 14, 15 | 1–5 |

Abweichung von der Reihenfolge im Ideendokument: Das erweiterte Fixkostenmodell (dort Phase 5) und die feste Verknüpfung zwischen Zahlung und Fixkost werden in Phase 1 vorgezogen. Sonst entstünden Vorschläge für ein rein monatliches Modell, die später umgebaut werden müssten. Die Zuordnung über Kategorie und Suchtext war außerdem die Ursache von F5.

---

## Phase 0 – Prüfsatz und Messgrundlage

**Ziel:** Bevor Erkennung oder KI gebaut werden, gibt es reproduzierbare Fälle, gegen die jede spätere Änderung gemessen wird.

- `tests/fixtures/recurring/` mit anonymisierten Szenarien als Python-Builder (keine echten Daten), je Szenario: Buchungen, erwartetes Ergebnis (Fixkost ja/nein, Rhythmus, Betrag, Fälligkeitstag).
- Pflichtfälle aus dem Ideendokument: gleicher Anbieter mit zwei Verträgen, schwankende Beträge (Strom), Quartals- und Jahresbeiträge, Kreditraten, Erstattungen, Supermarkt (regelmäßig, aber keine Fixkost), PayPal als Zahlungsdienstleister, fehlender Importmonat, doppelter Import, Preiserhöhung, Vertragsende.
- `tests/unit/test_recurring_scenarios.py` führt alle Szenarien gegen die Erkennung aus und gibt eine Trefferliste aus (richtig erkannt, falsch erkannt, übersehen).
- Abnahme: Szenarien liegen vor; die Tests sind zunächst als `xfail` markiert, bis Phase 1 sie erfüllt.

## Phase 1 – Fixkostenmodell, Vorschlagsspeicher, Erkennung im Backend

**Ergebnis:** Nach jedem Import entstehen Fixkostenvorschläge mit nachvollziehbaren Belegbuchungen. Sie bleiben gespeichert, lassen sich übernehmen, bearbeiten oder ablehnen; Ablehnungen werden nicht wiederholt. Fixkosten kennen Quartals-, Halbjahres- und Jahresrhythmus, und Zahlungen sind fest mit ihrer Fixkost verknüpft.

### 1.1 Fixkostenmodell erweitern

Migration `alembic/versions/<datum>_fixed_cost_interval_and_links.py`:

| Tabelle/Spalte | Typ | Bedeutung |
|---|---|---|
| `fixed_cost.interval_months` | int, Standard 1, Check `IN (1, 3, 6, 12)` | Rhythmus |
| `fixed_cost.first_due_date` | date, null | Erste Fälligkeit; legt bei `interval_months > 1` die Fälligkeitsmonate fest (`due_day` bleibt der Tag) |
| `fixed_cost.account_id` | int, null, FK `account` (gleiches Profil) | Konto, von dem gezahlt wird – Vorbereitung für Kontovorschau (Phase 5) |
| neue Tabelle `fixed_cost_payment` | `id`, `fixed_cost_id`, `transaction_id`, `split_id` (null), `due_month` (date, Monatserster), `source` (`manual`/`suggestion`/`matcher`), `created_at` | Feste Verknüpfung einer Zahlung mit einer Fälligkeit |

Constraints: `UNIQUE (transaction_id, split_id)` mit `NULLS NOT DISTINCT` (eine Buchungszeile gehört höchstens zu einer Fixkost), `UNIQUE (fixed_cost_id, due_month)`; FK mit `ON DELETE CASCADE` auf Transaktion und Fixkost. Bestehende Fixkosten erhalten `interval_months = 1`.

Anpassungen:
- `app/models/fixed_cost.py`, `app/schemas/budget.py` (Create/Update/Read um `interval_months`, `first_due_date`, `account_id`; Validierung: bei `interval_months > 1` ist `first_due_date` Pflicht).
- `app/services/budget.py`:
  - `_active_fixed_costs` liefert nur Fixkosten, die im Monat fällig sind (`(monat − first_due_date) mod interval_months == 0`).
  - Zuordnung zuerst über `fixed_cost_payment` (Verknüpfung für `due_month`), danach Rückfall auf den heutigen Kategorie-/Suchtext-Abgleich. Gefundene Treffer des Rückfalls werden **nicht** automatisch gespeichert (lesende Monatsansicht), nur angezeigt.
  - Neuer Endpunkt zum Bestätigen einer Zuordnung schreibt die Verknüpfung (siehe 1.4).
- `frontend/src/pages/einstellungen/FixedCostsSection.tsx`: Rhythmus-Auswahl und erste Fälligkeit; die Umrechnung „90 € je Quartal → 30 €/Monat“ aus S6 entfällt, Quartalszahlungen werden als Quartalsposten angelegt.

**Entschieden (05.11.2026):** Ein Quartals-, Halbjahres- oder Jahresposten zählt nur im Fälligkeitsmonat mit vollem Betrag. In den übrigen Monaten erscheint eine Anzeige „Rücklage für X: 30 €“ ohne Abzug vom Spielraum (`reserves` in `month_budget`).

Tests (`tests/api/test_budget.py` erweitern): Quartalsposten nur im Fälligkeitsmonat; feste Verknüpfung hat Vorrang vor Textabgleich; eine verknüpfte Buchungszeile zählt für keine zweite Fixkost; Löschen der Buchung löst die Verknüpfung; bestehendes November-Szenario (1.749,21 €) unverändert.

### 1.2 Vorschlagsspeicher

Neue Tabelle `suggestion` (Modell `app/models/suggestion.py`, Migration in derselben oder eigener Revision):

| Spalte | Typ | Inhalt |
|---|---|---|
| `id`, `user_id` | int | Profilbezug |
| `kind` | enum | zunächst `fixed_cost_new`; später `fixed_cost_change`, `rule`, `group_review`, … |
| `status` | enum | `open`, `accepted`, `rejected`, `auto_applied`, `reverted`, `stale` |
| `fingerprint` | text | stabiler Schlüssel des Falls, z. B. `iban:DE…|interval:1` oder `name:telekom|interval:1` |
| `payload` | JSONB | vorgeschlagene Werte (Name, Betrag, Rhythmus, Fälligkeitstag, erste Fälligkeit, Kategorie, Konto, `match_text`) |
| `evidence` | JSONB | Belegbuchungen (IDs, Datum, Betrag), Kennzahlen (Anzahl, mittlerer Abstand, Betragsstreuung) |
| `reason` | text | kurze, prüfbare Begründung („4 Zahlungen, monatlich am 3.–5., Betrag identisch“) |
| `generator` | text | Regel-/Modellversion, z. B. `recurring-v1` oder `recurring-v1+gemma4:e2b` |
| `data_as_of` | timestamptz | Datenstand der Berechnung |
| `result_type`, `result_id` | text, int | z. B. `fixed_cost`, ID nach der Übernahme |
| `created_at`, `updated_at`, `decided_at` | timestamptz | Verlauf |

Constraint: `UNIQUE (user_id, kind, fingerprint)`. Damit gilt:
- Ein abgelehnter Vorschlag bleibt `rejected` und wird bei der nächsten Erkennung nicht neu angelegt.
- **Wiederaufnahme nur bei wesentlich neuer Evidenz** (Phase-1-Regel: anderer Rhythmus oder Betragsabweichung > 20 % gegenüber der abgelehnten Fassung). Dann wird der Vorschlag mit Status `open` und einem Hinweis in `reason` („Neu bewertet: Betrag jetzt 44,99 € statt 39,99 €“) aktualisiert.
- Offene Vorschläge, deren Belegbuchungen verschwunden oder ausgeschlossen sind, oder für die inzwischen eine passende Fixkost existiert, werden `stale`.

Service `app/services/suggestions.py`: `upsert(session, user, kind, fingerprint, payload, evidence, reason, generator)`, `list_open`, `accept`, `reject`, `mark_stale`.

### 1.3 Erkennung wiederkehrender Zahlungen im Backend

Neuer Service `app/services/recurring.py` (deterministisch, ohne KI):

1. **Kandidaten laden:** reguläre Abflüsse der letzten 15 Monate eines Profils, ohne Umbuchungen, ohne ausgeschlossene Buchungen, ohne Kreditraten (`LoanPayment`) und Kreditkonto-Buchungen, ohne Buchungen, die bereits mit einer Fixkost verknüpft sind. Bei Splits je Splitzeile.
2. **Gruppieren:** nach Gegenpartei-IBAN, sonst normalisiertem Gegenparteinamen (Kleinschreibung, Rechtsformen und Ziffernfolgen entfernt). Zahlungsdienstleister (PayPal, Klarna, Amazon Payments; Liste in `app/services/recurring.py`) zusätzlich nach Mandats-/Referenznummer im Verwendungszweck trennen; ohne Referenz kein Vorschlag.
3. **Unterteilen** einer Gruppe nach Betragsclustern (mehrere Verträge beim selben Anbieter).
4. **Rhythmus bestimmen:** Abstände in Monaten und Tagen; monatlich bei mindestens 3 aufeinanderfolgenden Monaten mit 25–35 Tagen Abstand; Quartal/Halbjahr/Jahr bei mindestens 2 Zahlungen mit passendem Monatsabstand (Jahr: als schwacher Hinweis markiert). Logik aus `frontend/src/pages/einstellungen/fixedCostCandidates.ts` übernehmen und dort entfernen.
5. **Bewerten:** Betragsstreuung, Tagesspanne der Fälligkeit, Kategorie-Konsistenz. Kategorien mit typischem Konsumcharakter (Lebensmittel, Restaurant, Tanken; über `system_key`/Standardkategorien) erzeugen keinen Vorschlag – regelmäßiger Einkauf ist keine Fixkost.
6. **Abgleich mit Bestand:** Existiert eine aktive Fixkost mit gleicher Gegenpartei bzw. passendem `match_text`/Kategorie, entsteht kein neuer Vorschlag (Betragsänderung ist Phase 3).
7. **Vorschlag schreiben** über `suggestions.upsert` mit `fingerprint` aus Gruppierungsschlüssel und Rhythmus.

**Auslöser:**
- Im Import-Worker (`app/worker.py`) nach `process_queue`: für Profile, deren Import seit dem letzten Lauf den Status `done` erreicht hat. Merker: neue Spalte `import_batch.recurring_checked_at` oder eine Profil-Spalte `user.recurring_checked_at`; Neuberechnung nur bei neuen Buchungen.
- Manuell: `POST /suggestions/refresh` (für Tests und die Schaltfläche „Jetzt prüfen“).
- Laufzeit begrenzen: höchstens ein Profil je Worker-Durchlauf, Lauf in eigener Session; Fehler loggen, nicht den Import blockieren.

### 1.4 API

Router `app/routers/suggestions.py` (Tag „Vorschläge“):

| Methode und Pfad | Wirkung |
|---|---|
| `GET /suggestions?status=open&kind=fixed_cost_new` | Liste mit Payload, Evidenz und Belegbuchungen (Kurzform) |
| `POST /suggestions/refresh` | Erkennung für das aktuelle Profil sofort ausführen; Antwort: neue/aktualisierte/veraltete Anzahl |
| `POST /suggestions/{id}/accept` | Optionaler Body mit geänderten Werten (Name, Betrag, Rhythmus, Tag, Kategorie, Konto). Sperrt den Vorschlag (`FOR UPDATE`), prüft erneut (Status `open`, Belege vorhanden, keine inzwischen angelegte gleichartige Fixkost), legt die Fixkost über `budget.create_fixed_cost` an, verknüpft die Belegbuchungen in `fixed_cost_payment` (`source=suggestion`), setzt `accepted` und `result_id`. Bei Konflikt 409 `suggestion_stale`. |
| `POST /suggestions/{id}/reject` | Setzt `rejected` und `decided_at` |
| `POST /fixed-costs/{id}/payments` / `DELETE …/payments/{link_id}` | Zahlung manuell mit einer Fälligkeit verknüpfen bzw. lösen |

Fehlercodes in `frontend/src/api/messages.ts` ergänzen; `npm run gen:api` nach den Schemaänderungen.

### 1.5 Oberfläche

- **Einstellungen › Fixkosten:** Abschnitt „Erkannte Fixkosten“ ersetzt die heutige Clientberechnung (`fixedCostCandidates.ts`, `FixedCostsSection.tsx:227` mit 200 Buchungen/4 Monaten entfällt). Je Vorschlag: Name, Betrag, Rhythmus, Fälligkeit, Begründung, aufklappbare Belegbuchungen; Aktionen Übernehmen, Bearbeiten (öffnet das vorbefüllte Formular), Ablehnen.
- **Prüfliste:** Zähler „N Fixkosten-Vorschläge“ mit Link in die Einstellungen; keine Pflichtprüfung.
- **Monatsansicht/Start:** Bei Treffern über den Rückfall (Textabgleich) Aktion „Zuordnung bestätigen“, die die feste Verknüpfung schreibt.

### 1.6 Tests und Abnahme

- Backend: Szenarien aus Phase 0 grün; API-Tests für Upsert/Fingerprint, Ablehnung bleibt bestehen, Wiederaufnahme nur bei neuer Evidenz, `accept` mit Überschreibungen, `accept` nach paralleler Änderung → 409, `stale` nach Löschen der Belege, Profiltrennung.
- Parallelität: zwei gleichzeitige `accept` desselben Vorschlags legen genau eine Fixkost an (Test mit zwei Datenbankverbindungen wie bei F2).
- Frontend: Vitest für Darstellung der Rhythmen/Beträge; Browserlauf `e2e/paket4.mjs` (Import → Vorschlag → Übernehmen → Fixkost erscheint auf Start, zweiter Vorschlag → Ablehnen → erscheint nach erneutem Import nicht wieder).
- Abnahme: alle bestehenden Tests grün; Demo-Daten (`scripts/seed_demo.py`) um wiederkehrende Zahlungen ergänzen, sodass Vorschläge sichtbar werden.

**Ungefährer Umfang:** 2 Migrationen, 3 neue Backend-Module (Modell, Service, Router), Erweiterung von Budget und Worker, eine überarbeitete Einstellungsseite. KI wird in Phase 1 nicht benötigt.

---

## Phase 2 – KI für Namen und Verträge, Probelauf, optionale Automatik

- **KI-Anreicherung offener Vorschläge** (`app/services/ai_suggestions.py`): je Vorschlag eine Anfrage mit Belegtexten (als Daten markiert), Antwort-Schema `{name, ist_verpflichtung: bool, vertrag_referenz|null, begruendung}`. Nutzt `ai_review.chat()` und die vorhandene Warteschlange (`work_queue`) mit eigener Pending-Abfrage. Ergebnis ergänzt `payload`/`reason`, ändert nie Beträge oder Rhythmus. `ist_verpflichtung=false` setzt den Vorschlag auf niedrige Priorität, nicht auf abgelehnt.
- **Händler-/Vertragsaliasse (Teil von Idee 09):** Tabelle `counterparty_alias` (Profil, Rohname/IBAN, normalisierter Anbieter, optionale Vertragsreferenz, Quelle, bestätigt). Bestätigte Aliasse werden in 1.3 Schritt 2 zur Gruppierung genutzt.
- **Probelauf:** Einstellung je Profil `fixed_cost_automation`: `off` / `suggest` (Standard) / `auto_clear_cases`. Im Probelauf zeichnet das System auf, welche Vorschläge es automatisch übernommen *hätte*; Auswertung über `GET /suggestions/metrics` (Annahme-, Korrektur-, Ablehnungsquote je `generator`).
- **Automatische Übernahme (Idee 02):** nur bei `auto_clear_cases` und nur, wenn alle prüfbaren Bedingungen erfüllt sind: monatlich, ≥ 3 aufeinanderfolgende Zahlungen, identischer Betrag, eindeutige Gegenpartei (IBAN oder bestätigter Alias), konsistente Kategorie, kein Konflikt mit Bestand. Status `auto_applied`, Hinweis „automatisch angelegt – Rückgängig“.
- **Änderungsverlauf:** Tabelle `change_log` (Profil, Objekt, vorher/nachher als JSONB, Bezug auf Vorschlag, Zeitpunkt). Rücknahme prüft, ob die Fixkost seitdem manuell geändert wurde; dann nur Hinweis statt Überschreiben.
- Freigabe der Automatik erst, wenn der Prüfsatz keine Fehlübernahmen zeigt und der Probelauf über mindestens zwei Importzyklen keine Fehlübernahme ergeben hätte.

## Phase 3 – Weniger wiederkehrende Pflege

- **Betragsänderungen (Idee 03):** Tabelle `fixed_cost_amount` (Fixkost, gültig ab, Betrag); Budget liest den zum Monat gültigen Betrag. Erkennung in `recurring.py`: verknüpfte Zahlungen weichen ab → einmalige Abweichung nur melden, zwei aufeinanderfolgende gleiche neue Beträge → Vorschlag `fixed_cost_change` „ab Monat X anpassen“.
- **Regelvorschläge aus Korrekturen (Idee 04):** auf `review.suggest_rule` aufbauen; Auslöser: dieselbe Gegenpartei dreimal manuell gleich kategorisiert. Vorschlag `rule` mit Vorschau passender und widersprechender Buchungen (vorhandener Endpunkt `/mapping-rules/preview`).
- **Gemeinsame Prüfung ähnlicher Buchungen (Idee 10) und Reihenfolge der Prüfliste (Idee 22):** Gruppierung offener Buchungen nach Gegenpartei/Alias in `review.py`; Sammelbestätigung existiert bereits (`bulk_confirm`) und erhält Abwahl einzelner Buchungen. Kreditraten und Splits bleiben ausgenommen.

## Phase 4 – Einrichten und Klären

- **Importassistent (Idee 11):** Endpunkt `POST /import-profiles/draft` mit Beispieldatei; deterministische Erkennung von Trennzeichen, Kodierung, Datums- und Betragsformat; KI nur für uneindeutige Spaltennamen; Vorschau der ersten zehn Zeilen über den vorhandenen Parser (`app/importers/csv_profile.py`) vor dem Speichern.
- **Importdiagnose (Idee 12):** zuerst feste Texte je Fehlercode, KI nur für zusammenfassende Erklärung mit Beispielzeilen.
- **Gezielte Rückfragen (Idee 20) und Konsistenzhinweise (Idee 19):** neue Vorschlagsarten `question`/`consistency` im Vorschlagsspeicher; Antworten werden als Alias bzw. Präferenz gespeichert. Keine eigenständigen Kategoriezusammenführungen.

## Phase 5 – Belastbare Vorschau

- **Importabdeckung:** je Konto die lückenlos importierten Zeiträume aus den Importaufträgen ableiten (`import_batch` um `period_from`/`period_to`). Grundlage für alles Folgende.
- **Fehlende und ungewöhnliche Zahlungen (Idee 05):** erwartete Fälligkeiten aus Fixkosten mit Rhythmus und Toleranz (Wochenende, Feiertage, +5 Bankarbeitstage) nur innerhalb abgedeckter Zeiträume prüfen; Hinweise, nie Löschungen.
- **Erwartete Einnahmen (Idee 16):** Modell `expected_income` analog zu Fixkosten (Betrag oder Spanne, Rhythmus, Konto); Vorschläge aus bestätigten Serien.
- **Kontovorschau (Idee 17):** lesender Endpunkt `GET /accounts/{id}/forecast?until=` aus Saldo, Fixkosten mit `account_id`, Kreditraten (Zahlkonto) und erwarteten Einnahmen; erwartete und tatsächliche Werte getrennt.
- **Jahreskosten und Saison (Idee 18):** Hinweis auf Jahresposten erst ab 12 Monaten Historie; tatsächliche Fälligkeit und Rücklage getrennt (siehe Entscheidung in 1.1).

## Phase 6 – Erklären und Fragen

- **Monatserklärung (Idee 07):** Backend berechnet Abweichung je Kategorie und die größten Einzelbuchungen gegenüber dem Vormonat (Erstattungen und Umbuchungen wie im Budget); KI formuliert zwei bis drei Sätze mit Verweisen. Unvollständige Monate werden als solche benannt.
- **Lesende Fragen (Idee 08):** Die KI übersetzt eine Frage in einen erlaubten Werkzeugaufruf (Buchungsfilter `TransactionFilter`, Berichte aus `app/services/reports.py`); das Ergebnis wird mit Zeitraum, Datenstand und Belegen formuliert. Kein freies SQL, keine schreibenden Aktionen.
- **Natürliche Spracheingabe (Idee 21):** „Gestern 18,50 € bar Mittagessen“ → vorbefüllter Entwurf im vorhandenen Dialog `frontend/src/app/AddEntry.tsx`; Konto nur bei Eindeutigkeit vorbelegen, sonst nachfragen.

## Phase 7 – Größerer Ausbau

- Erstattungen und Umbuchungen zuordnen (Idee 06), wiederkehrende Split-Vorlagen (Idee 13).
- Belege und Verträge aus Dokumenten (Ideen 14, 15): Upload, Speicherung neben den Importdateien, lokale OCR; Werte immer mit Verweis auf Seite/Textstelle. Erst nach Stabilisierung der Phasen 1–5 genauer planen.

---

## Offene Entscheidungen

| Nr. | Frage | Empfehlung |
|---|---|---|
| E1 | Darstellung von Quartals-/Jahresposten im Monatsbudget (1.1) | **Entschieden:** voller Betrag im Fälligkeitsmonat, Rücklage nur als Anzeige |
| E2 | Wo erscheinen Fixkosten-Vorschläge zuerst? | Einstellungen › Fixkosten, Zähler in der Prüfliste |
| E3 | Historientiefe der Erkennung | 15 Monate (reicht für Jahresrhythmus mit einer Wiederholung) |
| E4 | KI-Anreicherung schon in Phase 1? | Nein, Phase 1 bleibt deterministisch; KI ab Phase 2 |
| E5 | Standard für die Automatik je Profil | `suggest`; `auto_clear_cases` nur nach ausdrücklicher Aktivierung |
| E6 | Behandlung bestehender Fixkosten ohne Verknüpfung | Rückfall-Abgleich bleibt; Verknüpfung entsteht erst durch Bestätigung |

## Risiken

- **Lokale KI-Last:** Anreicherung nur für offene Vorschläge, Ergebnis je Fingerprint zwischenspeichern, bestehende Parallelitätsgrenze `AI_PARALLEL` nutzen.
- **Falsche Gruppierung bei Zahlungsdienstleistern:** ohne Referenz kein Vorschlag (1.3 Schritt 2).
- **Budgetänderungen durch das neue Modell:** bestehende handgerechnete Szenarien in `tests/api/test_budget.py` und `tests/api/test_pruefbericht_2026_11.py` müssen unverändert grün bleiben; neue Rhythmen bekommen eigene Szenarien.
- **Rückwirkende Effekte:** neue oder geänderte Fixkosten wirken nicht ungefragt auf vergangene Monate (`start_date` beim Übernehmen auf den aktuellen Monat setzen).
