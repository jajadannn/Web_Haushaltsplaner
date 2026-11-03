# Finanzplaner – Oberfläche

React + Vite + TypeScript. Einrichtung, Entwicklung, Demo-Daten und Betrieb im Heimnetz stehen in der
[Projekt-README](../README.md#oberfläche-frontend).

- `src/wall/` – Wanddisplay (`/wand`), nur Anzeige
- `src/pages/` – persönliche Ansicht: Start, Buchungen, Import, Prüfen, Kredite, Berichte, Einstellungen
- `src/api/` – API-Client, Fehlertexte, Daten-Hooks; `schema.d.ts` per `npm run gen:api` erzeugt
- `src/ui/`, `src/styles/` – Bausteine und Gestaltungswerte (Smart-Home-Panel)
- `e2e/` – Durchklick-Tests gegen die Demo-API, `scripts/shot.mjs` – Screenshots
