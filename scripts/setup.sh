#!/usr/bin/env bash
# Dragnet setup script. Run once after cloning.
set -e

echo "=== Dragnet Setup ==="

# Python
if ! command -v python3.12 &>/dev/null && ! python3 --version | grep -q "3.12"; then
    echo "Python 3.12+ required. Install from python.org."
    exit 1
fi

# Typst — for resume PDF generation
if ! command -v typst &>/dev/null; then
    echo "Installing typst..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install typst || curl -fsSL https://typst.app/install.sh | sh
    else
        curl -fsSL https://typst.app/install.sh | sh
    fi
fi

# Python env
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Playwright browsers (needed by Stagehand)
playwright install chromium

# Env file
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example. Fill in your API keys before continuing."
fi

# DB (requires Postgres running)
echo ""
echo "To start Postgres: docker run -d -e POSTGRES_PASSWORD=dragnet -p 5432:5432 postgres:16"
echo "Then run: dragnet init"
echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Fill in .env"
echo "  2. dragnet init          # create DB tables"
echo "  3. dragnet check-facts   # verify facts.yaml"
echo "  4. dragnet eval-eligibility  # run M2 eval"
echo "  5. dragnet eval-tailoring    # run M3 eval"
echo "  6. dragnet execute --dry-run # verify executor"
echo "  7. dragnet execute --live    # go live"
echo "  8. dragnet worker        # start scheduler"
echo "  9. dragnet serve         # start dashboard (localhost:8080)"
