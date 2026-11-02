#!/usr/bin/env bash
# Generate an image via OpenAI GPT Image 2, using the Codex CLI authenticated
# with a ChatGPT (Plus) account. No OpenAI API key, no per-image API billing.
#
# Usage:
#   generate-image.sh "<prompt>" [--out <dir-or-file>] [--name <basename>]
#
# Output resolution (when --out is not given):
#   1. ./public/ exists  -> ./public/images/
#   2. otherwise          -> ./assets/images/   (created if missing)

set -euo pipefail

# --- parse args -------------------------------------------------------------
PROMPT=""
OUT=""
NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)  OUT="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *)
      if [[ -z "$PROMPT" ]]; then PROMPT="$1"; shift
      else echo "error: unexpected argument: $1" >&2; exit 1; fi ;;
  esac
done

if [[ -z "$PROMPT" ]]; then
  echo "error: no prompt given. usage: generate-image.sh \"<prompt>\" [--out <path>] [--name <basename>]" >&2
  exit 1
fi

# --- preconditions ----------------------------------------------------------
if ! command -v codex >/dev/null 2>&1; then
  echo "error: codex CLI not found. install with: brew install --cask codex" >&2
  exit 1
fi
if ! codex login status 2>&1 | grep -qi "ChatGPT"; then
  echo "error: codex is not logged in with a ChatGPT account. run: codex login" >&2
  exit 1
fi

# --- resolve output path ----------------------------------------------------
slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' \
    | cut -c1-50
}

if [[ -n "$OUT" && "$OUT" == *.png ]]; then
  OUT_DIR="$(cd "$(dirname "$OUT")" 2>/dev/null && pwd || true)"
  [[ -z "$OUT_DIR" ]] && { mkdir -p "$(dirname "$OUT")"; OUT_DIR="$(cd "$(dirname "$OUT")" && pwd)"; }
  OUT_FILE="$OUT_DIR/$(basename "$OUT")"
else
  if [[ -n "$OUT" ]]; then
    OUT_DIR="$OUT"
  elif [[ -d "./public" ]]; then
    OUT_DIR="./public/images"
  else
    OUT_DIR="./assets/images"
  fi
  mkdir -p "$OUT_DIR"
  OUT_DIR="$(cd "$OUT_DIR" && pwd)"
  BASE="${NAME:-$(slugify "$PROMPT")}"
  [[ -z "$BASE" ]] && BASE="image"
  OUT_FILE="$OUT_DIR/${BASE}.png"
  # avoid clobbering: append -2, -3, ... if exists
  n=2
  while [[ -e "$OUT_FILE" ]]; do
    OUT_FILE="$OUT_DIR/${BASE}-${n}.png"; n=$((n+1))
  done
fi

# --- generate ---------------------------------------------------------------
echo "Generating image -> $OUT_FILE"
codex exec -C "$OUT_DIR" -s workspace-write --skip-git-repo-check \
  "use the image generation tool to create the following image: ${PROMPT}. Save the result as a PNG to the absolute path ${OUT_FILE}. Do not write any other files."

# --- verify -----------------------------------------------------------------
if [[ -f "$OUT_FILE" ]]; then
  echo "OK: $OUT_FILE"
else
  echo "warning: expected file not found at $OUT_FILE. check codex output above." >&2
  exit 1
fi
