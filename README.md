# Finance Dashboard

A personal finance dashboard. It imports bank and credit card CSVs, cleans and categorizes the transactions, and shows where the money goes.

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic
- **Database:** PostgreSQL
- **Frontend:** Next.js (TypeScript), Tailwind, shadcn/ui, Recharts
- **Dev environment:** Docker Compose

## Getting started

Requires Docker (e.g. [OrbStack](https://orbstack.dev)). For running tests outside Docker you also need [uv](https://docs.astral.sh/uv/) and Node 26.

```bash
cp .env.example .env        # then replace "change-me" with a real password
docker compose up --build
```

- Frontend: <http://localhost:3000>
- API: <http://localhost:8000> (interactive docs at `/docs`)

Run the tests:

```bash
cd backend && uv sync && uv run pytest
cd frontend && npm install && npx vitest run
```

## Privacy

Real bank CSVs go in `data/`, which is gitignored and never committed. Test fixtures use fake data only.
