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

## Demo with fake data

A second copy of the app runs on made-up data (a year of transactions, a budget, paychecks), in its own `finance_demo` database, so it can be clicked through freely without touching real data:

```bash
docker compose --profile demo up -d    # then open http://localhost:3001
docker compose exec backend-demo python -m app.demo --reset    # fresh fake data
```

Its Plaid is sandbox-only, so it can't connect a real bank.

## Ask (AI chatbot)

Questions in plain English ("how much did I spend on food last month vs September?"). The AI only picks which of the app's functions to call (`backend/app/ai/tools.py`); every number comes from the same code as the dashboard, and each answer shows the tools it used. Add a free `GEMINI_API_KEY` to `.env` (see `.env.example`).

Gemini's free tier may use what it's sent for training, so Ask refuses to send real data: it only answers on the demo (http://localhost:3001/ask).

Accuracy is measured with 25 questions about the demo data, each checked against the right numbers worked out by code:

```bash
docker compose exec backend-demo python -m app.ai.eval
```

Last run: 25/25 with `gemini-3.5-flash-lite`.

## Privacy

Real bank CSVs go in `data/`, which is gitignored and never committed. Test fixtures use fake data only.
