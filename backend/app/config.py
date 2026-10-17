import os

# Local default matches docker-compose; override with the DATABASE_URL env var.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://finance:change-me@localhost:5432/finance"
)

FRONTEND_ORIGINS = os.environ.get("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
