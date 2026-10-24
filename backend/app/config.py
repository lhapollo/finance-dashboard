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
