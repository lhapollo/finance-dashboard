from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import FRONTEND_ORIGINS
from app.routers import accounts, imports, summary, transactions

app = FastAPI(title="Finance Dashboard API")

# Browsers block a page on localhost:3000 from calling localhost:8000 unless the API allows it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(imports.router)
app.include_router(transactions.router)
app.include_router(summary.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check: answers as long as the server is running."""
    return {"status": "ok"}
