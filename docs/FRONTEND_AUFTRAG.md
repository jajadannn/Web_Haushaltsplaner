# Gestaltungsauftrag: Finanzplaner-Frontend

Bestätigt am 02.11.2026. Visuelle Richtung gewählt über `/impeccable shape` (Seed `863d9162`, Runde „safer“): **Smart-Home-Panel**. Entwurfsbild: `.impeccable/mocks/decision/safe-smarthome.png` (sofern erzeugt).

## 1. Aufgabe und Nutzer
- **Wanddisplay im Wohnzimmer** (nur Anzeige): gemeinsamer Überblick für alle, abgelesen aus ca. 3 m, dauerhaft an, abends gedämpftes Licht. Keine Bedienung, aktualisiert sich selbst.
- **Persönliche Ansicht** je Profil auf Handy/Desktop: eigene Ausgaben sehen und eine Ausgabe erfassen; Arbeit überwiegend am Desktop.
- Modus: Bedienen (Operate) – Klarheit vor Ausdruck.

## 2. Ergebnis
- **Wand:** je Person **„Frei verfügbar“** diesen Monat als größte Zahl im Raum; anstehende Fixkosten und Kreditraten mit Status (bezahlt / fällig am); je Kredit **Restschuld und Abbezahlt-Datum** samt verbleibender Raten. Keine einzelnen Buchungen.
- **Persönlich:** **„Ausgabe hinzufügen“** als Hauptaktion (Betrag, Kategorie, Konto – wenige Schritte); eigener Spielraum, eigene letzte Ausgaben und Fixkosten.
- **Frei verfügbar** = Einnahmen des Monats − Fixkosten des Monats − bisherige variable Ausgaben. Kreditraten zählen automatisch zu den Fixkosten.

## 3. Richtung: Smart-Home-Panel
- Die Finanzen sehen aus wie der Rest des smarten Zuhauses: dunkler Grund, abgerundete Kacheln, Status auf einen Blick.
- Grün = bezahlt, Orange = fällig, Rot nur für überfällig; einfache Linien-Icons, Tabellenziffern.
- Wand als Kachelraster: oben je Person eine große Spielraum-Kachel, darunter kleine Fixkosten-Kacheln, rechts eine hohe Kreditkachel.
- Persönliche Ansicht in derselben Kachelsprache, verdichtet für Handy/Desktop.
- Umsetzung nach Entwurfsbild: vor dem Bau eine Runde mit drei Entwurfsvarianten; die freigegebene wird zum Maßstab.

## 4. Umfang
- Ganzes Frontend in Etappen: Wanddisplay → persönliche Startseite mit „Ausgabe hinzufügen“ → Buchungen → Import & Klärung → Prüfliste → Kredite → Berichte → Einstellungen (Profile, Konten, Kategorien, Regeln, Fixkosten).
- Unverändert: die fachliche Backend-Logik.
- Nicht gewollt: Diagramm-Spielereien, Gamification, verniedlichte Texte.

## 5. Zustände und Mengen
- 1–4 Profile, 3–15 Fixkosten pro Person, 0–3 Kredite.
- Monatsanfang ohne Einnahmen; negativer Spielraum (überzogen); Kredit abbezahlt; Display ohne Netz bzw. veraltete Daten (Zeitstempel „Stand: …“); erste Nutzung ohne Konten/Fixkosten.

## 6. Bedienung und Aufbau
- **Wand:** Querformat, keine Bedienelemente, automatische Aktualisierung (z. B. jede Minute), Einbrennschutz durch leichte Bewegung, abends gedämpfte Helligkeit.
- **Persönlich:** Profil einmal wählen und im Browser merken; Handy mit Daumen-Navigation, Desktop mit Seitenleiste; „Ausgabe hinzufügen“ überall mit einem Tipp erreichbar.

## 7. Rahmen und offene Punkte
- React + Vite + TypeScript, Deutsch, Beträge als Dezimalstrings; Fehlercodes der API in verständliche Texte übersetzen.
- **Backend-Erweiterungen (umgesetzt):**
  - `GET/POST/PATCH/DELETE /fixed-costs`: Fixkosten mit Name, Betrag, Fälligkeitstag, optional Kategorie und Suchtext (`match_text`), Laufzeit (`start_date`/`end_date`) und `active`. Kategorie und/oder Suchtext erkennen die Zahlung im Monat; jede Buchungszeile zählt nur für eine Fixkost.
  - `GET /budget/month?month=…`: Spielraum je Profil – Einnahmen (Einnahmen-Kategorien), Fixkosten inkl. fälliger Kreditraten, variable Ausgaben, frei verfügbar, Tage übrig, Betrag pro Tag; jede Fixkost/Rate mit Status `paid` / `open` / `overdue`.
  - `GET /wall`: gemeinsamer Überblick ohne Profilwahl, nur lesend, nur aus dem lokalen Netz (`WALL_ALLOWED_NETWORKS`): je Profil Spielraum und offene Fälligkeiten, alle Kredite mit Restschuld, Abbezahlt-Datum und Restraten.
- **Entschieden:** Das Wanddisplay nutzt die eigene Route `/wand` im Frontend und `GET /wall` ohne Profil. Einnahmen sind Buchungen in Einnahmen-Kategorien; unkategorisierte Eingänge erscheinen als „ungeklärt“ (`uncategorized_in`), bis sie in der Prüfliste eingeordnet sind.
