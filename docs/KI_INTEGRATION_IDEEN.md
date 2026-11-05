# KI im Finanzplaner: Ideen und Ausbauplan

Stand: 05.11.2026. Grundlage ist eine Durchsicht des vorhandenen Projekts, keine externe Marktstudie. Die Beispiele sind erfunden. Dieses Dokument beschreibt Möglichkeiten, keine bereits umgesetzten Funktionen oder verbindlichen Aufwandsschätzungen.

Die zuerst besprochenen Ideen wurden vom Nutzer positiv bewertet. Die weiteren Ideen ergänzen diese Sammlung. Ziel ist weniger manuelle Pflege bei nachvollziehbaren Buchungen und verlässlichen Auswertungen. Die vorhandene lokale KI-Anbindung soll dafür weiterverwendet werden.

## 1. Vorhandene Grundlagen

- `app/services/ai_review.py`: lokale KI über Ollama oder einen OpenAI-kompatiblen Server; Kategorienvorschläge mit Begründung und Selbsteinschätzung, bis zu fünf bestätigte Beispiele derselben Gegenpartei. Vorschläge werden bislang nicht selbst bestätigt. Hintergrundverarbeitung ist bereits vorhanden.
- `frontend/src/pages/einstellungen/fixedCostCandidates.ts`: regelbasierte Erkennung ähnlicher Beträge und wiederkehrender Zahlungsabstände. Gruppierung nach Empfänger beziehungsweise Text; keine KI.
- `frontend/src/pages/einstellungen/FixedCostsSection.tsx`: Auswahl beim manuellen Anlegen einer Fixkost; betrachtet derzeit höchstens 200 Buchungen aus vier Monaten. Damit fehlen ausreichende Daten für Halbjahres- und Jahresmuster, obwohl die Erkennungsfunktion solche Intervalle kennt.
- `app/models/fixed_cost.py` und `app/services/budget.py`: Fixkosten sind monatlich modelliert. Zahlungen werden über Kategorie und/oder Suchtext zugeordnet. Ein belastbarer Vertragsbezug fehlt.
- Importprofile, Regeln, Prüfliste, Splits, Kredite und Berichte bieten weitere Anknüpfungspunkte. Krediterkennung und Regelvorschläge sind teilweise schon vorhanden; Erweiterungen sollen darauf aufbauen.

## 2. Bereits besprochene Ideen

### 01 — Fixkosten erkennen und vorschlagen

**Beispiel:** „Internetanschluss: dreimal 39,99 €, monatlich zwischen dem 3. und 5. Als Fixkost übernehmen?“

Nach einem Import untersucht ein Backend-Dienst zusammengehörige Zahlungen. Er berechnet Rhythmus, Betragsstabilität und mögliche Fälligkeit. Die KI hilft bei Vertragszuordnung, verständlichen Namen und der Unterscheidung zwischen Verpflichtungen und regelmäßigem Konsum. Wiederholte Supermarkteinkäufe allein begründen keine Fixkost.

Der Vorschlag enthält Betrag, Rhythmus, Fälligkeit, Kategorie und die zugrunde liegenden Buchungen. Aktionen: Übernehmen, Bearbeiten, Ablehnen. Ablehnungen werden gespeichert, damit dieselben Fälle nicht ständig wieder erscheinen.

**Voraussetzungen:** Verarbeitung im Backend unabhängig vom Öffnen der Einstellungen; vollständige relevante Historie statt der aktuellen Oberflächengrenze; Prüfung bestehender Fixkosten und Kredite; Trennung mehrerer Verträge beim selben Anbieter.

### 02 — Eindeutige Fixkosten automatisch anlegen

**Beispiel:** „Internetanschluss automatisch als Fixkost angelegt: 39,99 € monatlich. Grundlage: vier passende Zahlungen. Rückgängig.“

Je Profil und Funktion wählbar: Aus, Nur Vorschläge, Eindeutige Fälle automatisch übernehmen. Ein möglicher konservativer Startpunkt sind mindestens drei aufeinanderfolgende monatliche Zahlungen mit identischem Betrag, eindeutigem Vertragsbezug, konsistenter Kategorie und ohne Konflikt mit bestehenden Einträgen. Diese Bedingungen sind eine Arbeitshypothese, keine garantierte Erkennungsqualität.

Die Selbstaussage des Modells „hoch“ genügt nicht. Freigaben beruhen auf prüfbaren Merkmalen und später gemessener Qualität. Bei unklaren Fällen bleibt es beim Vorschlag. Automatisch entsteht ein Planposten, keine zusätzliche Kontobuchung. Anfangs nur monatliche Fälle automatisieren; neue Einträge nicht ungefragt rückwirkend auf alte Monatsplanungen anwenden.

**Voraussetzungen:** Änderungsprotokoll, Dublettenschutz auch bei paralleler Verarbeitung, Rücknahme und gespeicherte Ablehnungen. Rücknahme muss nachträgliche manuelle Änderungen erkennen und darf sie nicht überschreiben.

### 03 — Betragsänderungen bestehender Fixkosten erkennen

**Beispiel:** „Der Internetanschluss wurde zuletzt mit 44,99 € statt 39,99 € abgebucht. Planbetrag ab November anpassen?“

Vergleich mit dem bisherigen Vertrag und seiner Historie. Einmalige Gebühren, Nachzahlungen, Erstattungen und dauerhafte Preisanpassungen unterscheiden. Eine einzelne abweichende Zahlung zunächst nur melden; automatische Anpassungen erst bei zusätzlicher Evidenz und aktivierter Funktion.

**Voraussetzungen:** Beträge mit Gültigkeitszeitraum statt Überschreiben historischer Werte; getrennte Behandlung laufender Kosten und Einmaleffekte.

### 04 — Aus Korrekturen Kategorisierungsregeln vorschlagen

**Beispiel:** „Du hast diesen Anbieter mehrfach als Mobilfunk eingeordnet. Künftige Buchungen ebenso zuordnen?“

Die KI formuliert eng gefasste Regeln aus bestätigten Entscheidungen. Eine Vorschau zeigt passende und widersprüchliche historische Buchungen. Bestehende Regelvorschläge erweitern, keine zweite konkurrierende Regelverwaltung aufbauen. Bestätigte Regeln können danach ohne erneute KI-Anfrage angewendet werden.

### 05 — Fehlende und ungewöhnliche Zahlungen melden

**Beispiel:** „Die erwartete Stromzahlung ist in den bisher importierten Buchungen noch nicht enthalten.“

Erwartete Termine, Betragsspannen und Verlauf vergleichen. Hinweise können fehlende Zahlungen, ungewöhnlich hohe Abbuchungen oder mehrfach abgebuchte Vertragsraten betreffen. Kein automatisches Löschen vermeintlicher Dubletten und keine Behauptung, eine Zahlung sei sicher ausgeblieben.

**Voraussetzungen:** Importabdeckung je Konto und angemessene Toleranz für Wochenenden, Feiertage und Buchungsverzögerungen. Das Datum der letzten Buchung allein beweist keine vollständige Importabdeckung.

### 06 — Umbuchungen und Erstattungen besser zuordnen

**Beispiel:** „Diese Gutschrift über 29,90 € könnte zu deinem Einkauf vom 12. Oktober gehören.“

Das Backend sucht passende Beträge, Zeiträume und Konten; die KI vergleicht uneinheitliche Texte. Vorschläge unterscheiden vollständige und teilweise Erstattungen sowie Umbuchungen zwischen eigenen Konten. Teilbeträge und Sammelabrechnungen bleiben gesonderte Fälle. Profilübergreifende Zuordnung braucht eine explizite Freigabe.

### 07 — Monatsveränderungen verständlich erklären

**Beispiel:** „Die Ausgaben liegen 180 € über dem Vormonat. Davon entfallen 120 € auf eine Reparatur und 60 € auf höhere laufende Kosten.“

Das Backend berechnet Vergleich und Ursachenbeiträge; die KI formuliert daraus eine kurze Erklärung mit verlinkten Buchungen. Unvollständige Monate, Erstattungen und Umbuchungen korrekt behandeln. Keine erfundenen Ursachen wie „Urlaub“, wenn die Daten das nicht belegen.

### 08 — Fragen zu eigenen Buchungen beantworten

**Beispiele:** „Welche Abos habe ich?“, „Wie viel ging dieses Jahr an die Stadtwerke?“, „Warum war Oktober teurer?“

Die KI übersetzt die Frage in erlaubte Suchfilter und Berichtsanfragen. Die Antwort enthält Zeitraum, Datenstand und Belege. Für Berechnungen vorhandene Services verwenden; keine frei ausgeführten SQL-Abfragen des Modells. Zunächst ausschließlich lesend.

## 3. Weitere Ideen

### 09 — Händler und Verträge hinter wechselnden Texten erkennen

**Beispiel:** Verschiedene Schreibweisen eines Mobilfunkanbieters werden demselben Anbieter zugeordnet, zwei unterschiedliche Vertragsnummern bleiben getrennt.

Die KI schlägt normalisierte Händlernamen und Vertragsbezüge vor. Originaltexte bleiben erhalten. IBAN, Referenzen und bestätigte Zuordnungen liefern zusätzliche Evidenz. Zahlungsdienstleister wie PayPal dürfen nicht pauschal als ein Vertrag behandelt werden.

**Nutzen:** Gemeinsame Grundlage für Fixkosten, Suche, Erstattungen und bessere Berichte. **Aufwand:** mittel bis hoch; braucht ein Modell für Aliasse und Vertragsbezüge. **Automatik:** bestätigte Zuordnungen wiederverwenden, unsichere Verknüpfungen vorschlagen.

### 10 — Ähnliche offene Buchungen gemeinsam prüfen

**Beispiel:** „18 Buchungen sehen nach demselben Mobilfunkvertrag aus. Kategorie gemeinsam übernehmen?“

Offene Buchungen nach nachvollziehbaren Merkmalen bündeln. Die Oberfläche zeigt Gemeinsamkeiten und Ausnahmen; einzelne Buchungen lassen sich abwählen. Eine Nutzerentscheidung klärt mehrere Fälle und liefert Beispiele für spätere Zuordnungen.

**Nutzen:** Besonders hilfreich nach großen Erstimporten. **Aufwand:** mittel. **Automatik:** Gruppierung automatisch, Übernahme zunächst gemeinsam bestätigen; Kreditraten und Splits gesondert behandeln.

### 11 — Neue CSV-Importprofile aus Beispieldateien vorbereiten

**Beispiel:** „Buchungstag erkannt, Betrag mit Dezimalkomma, Soll/Haben in separater Spalte. So würden die ersten zehn Zeilen eingelesen.“

Deterministische Erkennung von Trennzeichen und Formaten mit KI-Unterstützung für uneindeutige Spaltennamen kombinieren. Die KI erstellt einen Profilentwurf; der vorhandene Parser prüft Datum, Betrag, Vorzeichen und Pflichtfelder in einer Vorschau.

**Nutzen:** Weniger Handarbeit bei neuen Banken oder geänderten Exportformaten. **Aufwand:** mittel. **Automatik:** Profil vorschlagen; ein neues Format erst nach geprüfter Vorschau produktiv verwenden. Nicht für jede Zeile erneut die KI aufrufen.

### 12 — Importprobleme verständlich erklären

**Beispiel:** „Diese Datei verwendet ein anderes Datumsformat als dein Importprofil. Betroffen sind 34 Zeilen.“

Technische Fehler, Profilkonfiguration und ausgewählte Beispielzeilen in eine konkrete Erklärung übersetzen. Änderung am Profil vorschlagen und die Auswirkungen vor einem erneuten Import prüfen. Echte doppelte Zahlungen nicht mit Dateidubletten verwechseln.

**Nutzen:** Schnellere Fehlerbehebung. **Aufwand:** klein bis mittel. **Automatik:** Diagnose automatisch, Änderungen als Entwurf; bei eindeutigen Fehlercodes genügen feste Texte ohne KI.

### 13 — Wiederkehrende Aufteilungen vorbereiten

**Beispiel:** Eine regelmäßig bestätigte Sammelzahlung enthält zwei bekannte Vertragsbestandteile; beim nächsten Mal werden diese als Split vorgeschlagen.

Bestätigte Split-Vorlagen wiederverwenden und durch die KI passende neue Buchungen finden. Das Backend prüft, dass alle Teilbeträge exakt der Gesamtsumme entsprechen. Aus einem Supermarkt-Gesamtbetrag lassen sich ohne Beleg keine belastbaren Einzelkategorien ableiten. Kreditaufteilungen bleiben Aufgabe des Kreditservices.

**Nutzen:** Weniger wiederholte Eingaben. **Aufwand:** mittel. **Automatik:** zuerst nur Vorschläge; bei stabiler bestätigter Vorlage später optional automatisch.

### 14 — Belege und Rechnungen Buchungen zuordnen

**Beispiel:** Ein hochgeladener Beleg wird anhand von Händler, Datum und Betrag einer vorhandenen Buchung zugeordnet; enthaltene Positionen können einen Split vorbereiten.

OCR oder ein geeignetes Bildmodell liest strukturierte Felder aus. Originalbeleg und erkannte Werte werden nebeneinander gezeigt. Rechnungen beweisen noch keine Zahlung; aus einem Beleg nicht automatisch eine bereits importierte Buchung duplizieren.

**Nutzen:** Nachvollziehbare Details und einfachere Aufteilungen. **Aufwand:** hoch; Upload, Speicherung, Dokumentanzeige und lokale OCR/Bildverarbeitung fehlen als Grundlage. **Automatik:** Zuordnung vorschlagen, Beträge validieren.

### 15 — Vertragsdaten aus Dokumenten übernehmen

**Beispiel:** Aus einer Versicherungsrechnung werden Beitrag, Zahlungsrhythmus und nächste Fälligkeit als Vertragsentwurf übernommen.

Extraktion nur aus tatsächlich vorliegenden Dokumenten mit Verweis auf Textstelle oder Seite. Kündigungs- und Verlängerungsdaten nur bei eindeutigem Wortlaut übernehmen; fehlende Angaben nicht ergänzen. Vertragsende nicht aus einer ausbleibenden Abbuchung ableiten.

**Nutzen:** Weniger manuelle Stammdatenpflege. **Aufwand:** hoch; Vertragsmodell und Dokumentverarbeitung erforderlich. **Automatik:** zunächst Entwurf mit Bestätigung, keine automatische Kündigung oder Nachricht an Anbieter.

### 16 — Wiederkehrende Einnahmen erkennen

**Beispiel:** „Diese Gehaltszahlung kommt normalerweise am Monatsende. Für die Vorschau verwenden?“

Regelmäßige Einnahmen, schwankende Bestandteile und Einmalzahlungen unterscheiden. Das Backend berechnet aus bestätigten Serien eine Erwartung oder Spanne; die KI hilft bei Zuordnung und Erklärung.

**Nutzen:** Grundlage einer brauchbaren Vorschau. **Aufwand:** mittel; eigenes Modell erwarteter Einnahmen nötig. **Automatik:** Planwerte vorschlagen, niemals zukünftige Kontobuchungen als tatsächlich eingegangen behandeln.

### 17 — Kontostände bis zum nächsten Zahlungseingang vorschauen

**Beispiel:** „Vor dem erwarteten Gehalt fallen auf diesem Konto noch drei bekannte Zahlungen an.“

Heutiger Kontostand, bekannte Verpflichtungen und erwartete Einnahmen ergeben eine zeitliche Vorschau pro Konto. Rechenlogik und Unsicherheit liegen im Backend; die KI erläutert die wesentlichen Einflüsse. Aktuelle Fixkosten haben noch keinen festen Kontobezug, der dafür ergänzt werden müsste.

**Nutzen:** Anstehende Belastungen früher erkennen. **Aufwand:** hoch; Kontozuordnung, echte Intervalle und Einnahmenplanung vorausgesetzt. **Automatik:** lesende Vorschau mit Szenarien, keine Überweisungen. Erwartete und tatsächliche Werte sichtbar trennen.

### 18 — Saisonale Ausgaben und Jahreskosten sichtbar machen

**Beispiel:** „Im letzten Herbst fiel ein größerer Versicherungsbeitrag an. Soll dieser als jährlicher Posten geprüft werden?“

Längere Zeitreihen auf saisonale Muster untersuchen. Echte Jahresverpflichtungen von bloß ähnlichen Vorjahresausgaben unterscheiden. Ein einzelnes Ereignis im Vorjahr ist nur ein schwacher Hinweis.

**Nutzen:** Weniger übersehene Jahreskosten. **Aufwand:** mittel bis hoch. **Automatik:** Hinweise und Planentwürfe; tatsächliche Fälligkeit und monatlichen Rücklagenanteil getrennt abbilden. Ohne ausreichende Historie keine belastbare Saisonprognose.

### 19 — Kategorien und widersprüchliche Zuordnungen aufräumen

**Beispiel:** „Derselbe Vertrag wurde teils als Telefon, teils als Internet bestätigt. Absichtlich?“

Inkonsistenzen, sehr ähnliche Kategorien und zu breite Regeln finden. Die KI erklärt mögliche Zusammenhänge, die App zeigt betroffene Buchungen und Auswirkungen einer Änderung. Unterschiedliche Kategorien bei einem Händler können berechtigt sein.

**Nutzen:** Verständlichere Berichte und bessere künftige Vorschläge. **Aufwand:** mittel. **Automatik:** nur Vorschläge; Kategorien nicht eigenständig zusammenführen oder bestätigte Historie umschreiben.

### 20 — Gezielte Rückfragen statt wiederholter Fehlvorschläge

**Beispiel:** „Gehören diese zwei Referenzen zum gleichen Vertrag oder zu zwei verschiedenen?“

Bei wiederkehrender Unsicherheit eine konkrete, kurze Frage stellen. Die Antwort als strukturierte Zuordnung oder Präferenz speichern. Neue Fragen bündeln und nur dann stellen, wenn die Entscheidung mehrere Fälle verbessert.

**Nutzen:** Weniger Korrekturen und bessere Vertragszuordnung. **Aufwand:** mittel. **Automatik:** Fragen vorbereiten; Antworten gelten im jeweiligen Kontext, nicht pauschal für alle Zahlungen des Empfängers.

### 21 — Buchungen in natürlicher Sprache vorbereiten

**Beispiel:** „Gestern 18,50 € bar für Mittagessen“ öffnet einen ausgefüllten Buchungsentwurf.

Datum, Betrag, Kategorie und gegebenenfalls Konto extrahieren. Mehrdeutige Konten oder fehlende Angaben gezielt klären. Vor dem Speichern eine mögliche vorhandene Buchung anzeigen. Optional später Spracheingabe ergänzen.

**Nutzen:** Schnellere manuelle Erfassung, besonders am Handy. **Aufwand:** mittel, Spracheingabe zusätzlich. **Automatik:** zunächst Entwurf bestätigen; keine erfundenen Konten oder stillen Standardzuordnungen.

### 22 — Prüfliste nach Klärungsbedarf ordnen

**Beispiel:** „Zuerst drei Fälle mit möglicher Doppelzuordnung prüfen; zwölf ähnliche Kategorienvorschläge anschließend gesammelt bestätigen.“

Mögliche Auswirkungen, Konflikte und Gruppierbarkeit bestimmen eine erklärbare Reihenfolge. Filter und vollständige Liste bleiben erhalten. Ein einfacher regelbasierter Ansatz reicht als Ausgangspunkt; KI kann ähnliche Fälle bündeln und die Begründung formulieren.

**Nutzen:** Weniger Zeit bis zu einer aussagekräftigen Auswertung. **Aufwand:** klein bis mittel. **Automatik:** nur Reihenfolge und Gruppierung; Fälle nicht verstecken oder selbst als erledigt markieren.

## 4. Gemeinsame technische Grundlage

### Einheitliche Vorschläge und Änderungsverlauf

Vorschläge sollten als eigene Datensätze vorliegen: Profil, Typ, betroffene Objekte, zugrunde liegende Buchungen, strukturierte vorgeschlagene Werte, Begründung, Modell-/Regelversion, Datenstand und Status. Denkbare Statuswerte: offen, angenommen, abgelehnt, automatisch angewendet, zurückgenommen, veraltet.

Eine Ablehnung verhindert Wiederholungen desselben Vorschlags. Wesentlich neue Evidenz darf eine erneute Bewertung auslösen, muss aber erklären, was sich geändert hat. Automatische Änderungen speichern vorherige und neue Werte sowie einen Bezug zum Vorschlag. Personenbezogene Freitextantworten nur speichern, soweit die Funktion sie benötigt.

### Rechnen, Interpretieren und Schreiben trennen

- Backend: Geldbeträge als Decimal, Intervalle, Statistiken, Suchkandidaten, Profilgrenzen, Duplikatprüfung und fachliche Invarianten.
- KI: Textverständnis, mögliche Vertragsbezüge, Formulierung und strukturierte Vorschläge.
- Aktionsdienst: erlaubte Aktion erneut validieren und atomar anwenden; vorhandene Services verwenden. Keine direkten Datenbankänderungen durch das Modell.
- Vor dem Schreiben den aktuellen Datenstand prüfen. Manuelle Änderungen während einer KI-Anfrage dürfen nicht überschrieben werden.
- Buchungstexte und Dokumentinhalte sind Daten, keine auszuführenden Anweisungen. Strukturierte Modellausgaben gegen erlaubte Felder, IDs und Profilzugehörigkeit prüfen.

### Fixkostenmodell erweitern

Für Quartals-, Halbjahres- und Jahreszahlungen werden Rhythmus, nächste Fälligkeit, Gültigkeitszeitraum, optional Konto und Vertragsbezug benötigt. Monatliche Rücklage und tatsächliche Belastung sind unterschiedliche Größen. Änderungen dürfen alte Berichte nicht still rückwirkend verfälschen. Eine konkrete Verknüpfung zwischen Zahlung und Verpflichtung wäre belastbarer als allein Kategorie und Suchtext.

### Qualität vor Automatik messen

Zuerst Vorschläge beziehungsweise einen Probelauf ohne automatische Änderungen betreiben. Mit bestätigten und abgelehnten Fällen je Funktion messen: Annahmequote, Korrekturquote, irrtümliche Übernahmen, übersehene Fälle und Rücknahmen. Eine hohe Annahmequote allein beweist keine hohe Trefferqualität. Keine erfundenen Prozentwerte aus der Selbsteinschätzung des Modells anzeigen.

Einen getrennten Prüfsatz mit realistisch anonymisierten Fällen aufbauen: gleiche Anbieter mit mehreren Verträgen, wechselnde Beträge, Jahresbeiträge, Kreditraten, Erstattungen, fehlende Importmonate, doppelte Imports und parallele manuelle Bearbeitung. Schwellen anhand dieser Fälle wählen und nach Modellwechsel neu prüfen.

### Hintergrundverarbeitung und Oberfläche

Nach erfolgreichen Imports und relevanten Korrekturen gezielt betroffene Serien neu bewerten. Günstige Prüfungen zuerst, KI nur für verbleibende Interpretationsfragen. Bestätigte Regeln und Zuordnungen wiederverwenden. Begrenzte Parallelität, Wiederholungslogik und Weiterbetrieb bei nicht erreichbarer KI vorsehen.

Neue Vorschlagstypen möglichst in die vorhandene Prüfliste integrieren. Automatische Änderungen in einem separaten, leicht auffindbaren Verlauf anzeigen, ohne wieder eine Pflichtprüfung jeder Änderung einzuführen. Detailkarten zeigen konkrete Belege und erlauben die Rücknahme. Hinweise bündeln und bei unverändertem Zustand nicht ständig erneut melden.

## 5. Empfohlene Reihenfolge

| Phase | Umfang | Ergebnis |
|---|---|---|
| 1 | Vorschlagsspeicher, Backend-Erkennung monatlicher Fixkosten, Ablehnen/Übernehmen, nachvollziehbare Evidenz | Fixkostenvorschläge entstehen nach dem Import und bleiben erhalten |
| 2 | Probelauf auswerten, Vertragszuordnung verbessern, Änderungsverlauf und optionale automatische Übernahme | Eindeutige monatliche Fixkosten werden mit Rücknahmemöglichkeit angelegt |
| 3 | Betragsänderungen, bessere Regelvorschläge, gemeinsame Prüfung ähnlicher Buchungen | Weniger wiederkehrende Pflege |
| 4 | Importassistent, Importdiagnose, gezielte Rückfragen, Konsistenzhinweise | Einfacheres Einrichten und Klären |
| 5 | Echte Zahlungsintervalle, Kontobezug, erwartete Einnahmen, Importabdeckung | Belastbare Grundlage für Jahreskosten und Kontovorschau |
| 6 | Monatskommentare und lesende Fragen zu Buchungen | Einfacherer Zugang zu vorhandenen Auswertungen |
| 7 | Dokumente, Belegzuordnung, Vertragsauslesen und weitergehende Split-Vorschläge | Größerer Ausbau nach Stabilisierung der Kernabläufe |

Die Phasen sind ein Priorisierungsvorschlag. Monatskommentare oder lesende Fragen können unabhängig von Phase 5 vorgezogen werden. Die Aufwandsangaben der Ideen sind relativ, keine zugesagten Zeitpläne.

## 6. Bewusste Grenzen

Keine automatischen Banküberweisungen, Vertragskündigungen, Löschung möglicher Dubletten oder unbelegten Änderungen historischer Buchungen. Diese Aktionen sind nicht Teil der vorgeschlagenen Automatik. Ausgaben allein verraten weder die Nutzung eines Abos noch den Inhalt eines Einkaufs. Dafür braucht es zusätzliche Angaben oder Dokumente.

Der größte unmittelbare Nutzen liegt bei Fixkosten, wiederholten Zuordnungen und schnellerem Prüfen. Ein umfassender Chat ist eine mögliche spätere Oberfläche, aber keine Voraussetzung für diese Verbesserungen.
