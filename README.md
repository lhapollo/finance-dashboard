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

Run the tests. Database tests use a separate `finance_test` database (set by `TEST_DATABASE_URL` in `.env`), which they wipe and rebuild, so your real data is never touched. Create it once, with Docker running:

```bash
docker compose exec db createdb -U finance finance_test
```

```bash
cd backend && uv sync && uv run pytest
cd frontend && npm install && npx vitest run
```

## Importing a CSV

With `docker compose up` running, open <http://localhost:8000/docs>, choose `POST /import`, pick the account and the file. Re-importing an overlapping download is safe: rows already saved are skipped. Supported so far: CIBC credit card, Tangerine chequing, Tangerine savings, and Tangerine Mastercard.

## Connecting banks with Plaid

Optional: instead of downloading CSVs, new transactions can come straight from your bank. Sign up at <https://dashboard.plaid.com/signup> ("Personal use"), then put your client id and secrets in `.env` (see `.env.example`), along with a `PLAID_TOKEN_KEY` for encrypting access tokens. Restart the backend with `docker compose up -d --build backend`, then use **Connect a bank** on the Accounts page and choose which of your accounts each bank account is. With `PLAID_ENV=sandbox`, Plaid shows test banks: log in with `user_good` / `pass_good`.

Opening the dashboard syncs banks that haven't synced in 6 hours; **Sync now** on the Accounts page syncs right away. Transactions already imported from CSVs are matched by account, date and amount, so switching an account to Plaid adds nothing twice. After an account is linked, CSV rows after its last CSV day are skipped.

## Privacy

Real bank CSVs go in `data/`, which is gitignored and never committed. Test fixtures use fake data only.
