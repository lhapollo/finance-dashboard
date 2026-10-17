from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import FRONTEND_ORIGINS

app = FastAPI(title="Finance Dashboard API")

# Browsers block a page on localhost:3000 from calling localhost:8000 unless the API allows it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check: answers as long as the server is running."""
    return {"status": "ok"}
