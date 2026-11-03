#!/usr/bin/env bash
# API-Typen aus dem OpenAPI-Schema des Backends erzeugen: npm run gen:api
set -euo pipefail
cd "$(dirname "$0")/../.."
.venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False))" > frontend/openapi.json
cd frontend
npx --yes openapi-typescript@7.13.0 openapi.json -o src/api/schema.d.ts
rm openapi.json
