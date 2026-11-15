from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import FRONTEND_ORIGINS
from app.plaid import PlaidError, PlaidNotConfigured
from app.routers import (
    accounts,
    budget,
    imports,
    paychecks,
    plaid,
    rename_rules,
    summary,
    transactions,
)
from app.services.secrets import TokenKeyError

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
app.include_router(rename_rules.router)
app.include_router(plaid.router)
app.include_router(budget.router)
app.include_router(paychecks.router)


# Plaid problems become clear messages for the page, in the same {"detail": ...} shape as
# FastAPI's own errors, instead of a bare "500 Internal Server Error".
@app.exception_handler(PlaidNotConfigured)
@app.exception_handler(TokenKeyError)
def setup_problem(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(PlaidError)
def plaid_problem(request: Request, exc: PlaidError) -> JSONResponse:
    # 502 = "a service behind this one failed": the problem is at Plaid, not in this app.
    return JSONResponse({"detail": f"Plaid: {exc.message} ({exc.code})"}, status_code=502)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check: answers as long as the server is running."""
    return {"status": "ok"}
