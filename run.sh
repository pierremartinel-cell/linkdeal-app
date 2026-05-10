#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── First run: create venv and install deps ──────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "🔧 Première installation…"
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r backend/requirements.txt
  playwright install chromium
  echo "✅ Installation terminée"
else
  source .venv/bin/activate
fi

# ── Check .env ───────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  Fichier .env créé — remplis tes clés :"
  echo "   open .env"
  echo ""
  echo "Puis relance : ./run.sh"
  exit 1
fi

# ── Get local IP for phone access ────────────────────────────────────────────
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "localhost")

echo ""
echo "🟢 LinkDeal démarré !"
echo ""
echo "   Sur ton Mac    → http://localhost:8000"
echo "   Sur ton iPhone → http://$LOCAL_IP:8000"
echo ""
echo "   (assure-toi que ton iPhone est sur le même WiFi)"
echo ""

# ── Start backend ────────────────────────────────────────────────────────────
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
