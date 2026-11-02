# Arbeitsplan: Finanzplaner (Internes Netzwerk)

Dieses Dokument beschreibt die schrittweise Entwicklung eines reinen Finanzplaners. Das System ist für den internen Gebrauch konzipiert und verzichtet auf komplexe Authentifizierung zugunsten einer einfachen Benutzerwahl.

## 🎯 Projektziele
- Vollständige Erfassung von Einnahmen und Ausgaben.
- Verwaltung mehrerer Konten (Bank, Bargeld, Kreditkarten).
- Automatische Verarbeitung von Kontoauszügen (CSV, OFX, MT940).
- Kategorisierung von Transaktionen durch intelligente Mapping-Regeln.
- Übersichtliche Berichterstattung und Ausgabenanalyse.

---

## 🛠 Technischer Stack
- **Backend:** FastAPI (Python)
- **Datenbank:** PostgreSQL (oder SQLite für lokale Nutzung)
- **ORM:** SQLModel (oder SQLAlchemy)
- **Import-Engine:** `watchdog` (File Watcher) & Custom Parser Logic
- **Frontend:** React (Geplant)
- **Infrastruktur:** Docker (optional)

---

## 🗺 Roadmap

### Phase 1: Datenmodellierung & Basis-Infrastruktur
*Ziel: Das Datenbank-Fundament schaffen.*

- [ ] **Datenbank-Setup:** Einrichten der DB-Verbindung.
- [ ] **Datenmodelle definieren:**
    - `Account`: Name, Kontostand, Währung, Typ.
    - `Category`: Name, Typ (Einnahme/Ausgabe), Icon/Farbe.
    - `Transaction`: Datum, Betrag, Beschreibung, Kategorie-ID, Konto-ID, Status (Abgestimmt/Offen).
    - `MappingRule`: Suchbegriff (Regex), Ziel-Kategorie, Ziel-Konto (für Automatisierung).
- [ ] **Basis-Endpunkte:**
    - `GET /accounts` & `GET /categories`
    - `POST /accounts` & `POST /categories`

### Phase 2: Manuelles Finanztracking (CRUD)
*Ziel: Grundlegende Nutzung des Planers ermöglichen.*

- [ ] **Transaktions-Management:**
    - `POST /transactions`: Manuelle Eingabe von Ausgaben/Einnahmen.
    - `GET /transactions`: Abfrage mit Filtern (Datum, Konto, Kategorie).
    - `PATCH /transactions/{id}`: Bearbeiten von Einträgen.
    - `DELETE /transactions/{id}`: Löschen von Einträgen.
- [ ] **Konten-Logik:** Automatische Aktualisierung des Kontostands beim Erfassen einer Transaktion.

### Phase 3: Import-Engine & Dateiwachung
*Ziel: Die Automatisierung der Datenpflege.*

- [ ] **File Watcher:** Hintergrundprozess, der einen Ordner (`/imports`) auf neue Dateien überwacht.
- [ ] **Parser-Module:**
    - CSV-Parser (für gängige Bankformate).
    - OFX/MT940 Parser (optional für spätere Erweiterung).
- [ ] **Import-Logik:**
    - Einlesen der Datei -> Identifikation der Bank -> Zuordnung zu bestehendem Konto.
    - Abgleich mit `MappingRules` zur automatischen Kategorisierung.

### Phase 4: Intelligentes Mapping & Validierung
*Ziel: Den Import so präzise wie möglich machen.*

- [ ] **Mapping-System:** Interface zur Definition von Regeln (z.B. "Wenn 'Amazon' in Beschreibung -> Kategorie 'Shopping'").
- [ ] **Review-Queue:** Anzeige von Transaktionen, die nicht automatisch zugeordnet werden konnten, zur manuellen Bestätigung.
- [ ] **Dublettenprüfung:** Abgleich von Transaktions-IDs/Zeitstempeln, um doppelte Importe zu verhindern.

### Phase 5: Analytik & Reporting
*Ziel: Daten in Erkenntnisse verwandeln.*

- [ ] **Aggregations-Endpunkte:**
    - `GET /reports/summary`: Gesamtsaldo und monatliche Netto-Bilanz.
    - `GET /reports/categories`: Ausgabenverteilung pro Kategorie (für Diagramme).
    - `GET /reports/trends`: Vergleich der Ausgaben der letzten X Monate.
- [ ] **Export-Funktion:** Export der Daten als CSV oder PDF.

### Phase 6: Frontend & Deployment
*Ziel: Benutzerfreundliche Oberfläche.*

- [ ] **Frontend-Entwicklung:**
    - Dashboard mit Kontoständen und aktuellen Ausgaben.
    - Transaktionsliste mit Filtern.
    - Einfaches Modal für die manuelle Eingabe.
- [ ] **Frontend-User-Auswahl:** Einfache Auswahl des Profils (Speicherung der ID im Browser).
- [ ] **Deployment:** Hosting auf internem Server/VPS.

---

## 📋 Definition of Done (DoD)
- Alle API-Endpunkte sind dokumentiert (Swagger/OpenAPI).
- Transaktionen werden korrekt in der Datenbank persistiert.
- Der Import-Ordner verarbeitet neue Dateien ohne manuellen Start.
- Die Berichte stimmen mit den manuellen Berechnungen überein.
