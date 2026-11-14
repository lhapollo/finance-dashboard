import os
from pathlib import Path

# Local default matches docker-compose; override with the DATABASE_URL env var.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://finance:change-me@localhost:5432/finance"
)

# The gitignored folder with real CSVs and personal settings. backend/../data on your Mac;
# docker-compose mounts the same folder at /data, which this also resolves to inside Docker.
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

FRONTEND_ORIGINS = os.environ.get("FRONTEND_ORIGINS", "http://localhost:3000").split(",")

# Plaid (bank connections). Empty values mean "not set up yet": the app still runs, and the
# Plaid endpoints say what's missing.
PLAID_CLIENT_ID = os.environ.get("PLAID_CLIENT_ID", "")
PLAID_ENV = os.environ.get("PLAID_ENV", "sandbox")  # sandbox / production
PLAID_SECRET = os.environ.get(
    "PLAID_SECRET_PROD" if PLAID_ENV == "production" else "PLAID_SECRET_SANDBOX", ""
)
# Key for encrypting access tokens before they're saved (see app/services/secrets.py).
PLAID_TOKEN_KEY = os.environ.get("PLAID_TOKEN_KEY", "")
