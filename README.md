<div align="center">

#  LedgerCore
**ACID-Compliant Core Banking API**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

A production-grade REST API simulating a core banking backend. LedgerCore handles secure user authentication, account management, and concurrent money transfers with financial-grade data integrity.

</div>

---

##  Key Features

* **Double-Entry Ledger** — Every financial movement creates immutable `DEBIT` and `CREDIT` records, ensuring a non-repudiable audit trail.
* **ACID Transactions** — Transfer operations are wrapped in atomic transaction blocks. If any step fails (e.g., validation, server crash), the entire operation rolls back.
* **Concurrency Safe (Row-Level Locking)** — Utilizes `SELECT ... FOR UPDATE` with ordered ID locking to prevent race conditions (double-spending) and deadlocks during simultaneous transfers.
* **Integer Currency Handling** — All balances are stored as integers (paise/cents) rather than floats to eliminate floating-point precision errors.
* **Idempotency** — API supports `idempotency_key` checks on transfers, preventing duplicate transactions if a client retries a network request.
* **JWT Authentication** — Secure stateless authentication routing ensuring users can only interact with their own accounts.

---

##  System Architecture

The system is designed to handle concurrent transaction requests safely, ensuring no two requests can modify the same account balance simultaneously without waiting in a secure queue.

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant DB as PostgreSQL
    
    Client->>API: POST /transfer (Amount, Receiver, IdempotencyKey)
    API->>DB: Check IdempotencyKey
    alt Key Exists
        DB-->>API: Return Existing Transaction ID
        API-->>Client: 200 OK (Already Processed)
    else New Request
        API->>DB: BEGIN TRANSACTION
        Note over API,DB: Sort Account IDs to prevent deadlocks
        API->>DB: SELECT FOR UPDATE (Smaller Account ID)
        API->>DB: SELECT FOR UPDATE (Larger Account ID)
        
        alt Insufficient Funds
            API->>DB: ROLLBACK
            API-->>Client: 400 Bad Request
        else Valid Funds
            API->>DB: UPDATE Sender Balance (-Amount)
            API->>DB: UPDATE Receiver Balance (+Amount)
            API->>DB: INSERT LedgerEntry (DEBIT Sender)
            API->>DB: INSERT LedgerEntry (CREDIT Receiver)
            API->>DB: COMMIT
            API-->>Client: 200 OK (Transfer Successful)
        end
    end
```

---

##  Project Structure

```text
LedgerCore/
├── app/
|   ├── __init__.py          # Marks app/ as a package
│   ├── main.py              # FastAPI application setup & routing
│   ├── models.py            # SQLAlchemy ORM models (Users, Accounts, Ledger)
│   ├── database.py          # DB engine/session management (SQLite by default, Postgres via DATABASE_URL)
│   ├── auth.py              # JWT hashing & token verification logic
│   ├── deps.py              # Auth dependency + account-
|   └── schemas.py           # Pydantic models for request/response validation
├── tests/
|   ├── __init__.py          # Marks tests/ as a package
│   ├── conftest.py          # Pytest fixtures (DB setup/teardown for tests)
│   └── test_transfers.py    # Successful transfer, insufficient funds, idempotency, and concurrency tests
├── requirements.txt         # Python dependencies
└── README.md                # Project documentation
```

---

##  Database Schema

The schema is heavily normalized and designed for high financial integrity.

```mermaid
erDiagram
    USERS ||--o{ ACCOUNTS : owns
    ACCOUNTS ||--o{ LEDGER_ENTRIES : has
    TRANSACTIONS ||--|{ LEDGER_ENTRIES : contains

    USERS {
        int id PK
        string email
        string hashed_password
    }
    ACCOUNTS {
        int id PK
        int user_id FK
        int balance_paise
    }
    TRANSACTIONS {
        int id PK
        string idempotency_key UK
        string status
        datetime created_at
    }
    LEDGER_ENTRIES {
        int id PK
        int transaction_id FK
        int account_id FK
        string entry_type "DEBIT or CREDIT"
        int amount_paise
    }
```

---

## Getting Started
 
### Prerequisites
 
- Python 3.10+
- `pip`
### 1. Clone the repository
 
```bash
git clone https://github.com/Arshpreet-Singh-2005/LedgerCore.git
cd LedgerCore
```
 
### 2. Create a virtual environment and install dependencies
 
```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
 
pip install -r requirements.txt
```
 
### 3. Run the server
 
```bash
uvicorn app.main:app --reload
```
 
The API is now running at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.
 
By default LedgerCore uses a local SQLite database (`ledger.db`) — no extra setup needed. See [Configuration](#configuration) to point it at PostgreSQL instead.
 
---

---

##  Running the Test Suite

LedgerCore includes a Pytest suite covering a successful transfer, insufficient-funds rollback, idempotency-key replay, and — the centerpiece — a multithreaded concurrency test that fires 5 simultaneous transfers of the full balance at the same receiver and asserts exactly one succeeds while the rest correctly reject, with the database left in a consistent state either way.

```bash
# Run tests with verbose output
pytest tests/ -v
```
---
 
## Configuration
 
LedgerCore reads its config from environment variables (a `.env` file works if you load it, e.g. via `python-dotenv` or your shell):
 
| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./ledger.db` | Any SQLAlchemy-compatible connection string. Set this to a PostgreSQL URL (e.g. `postgresql://user:pass@localhost:5432/ledgercore`) for real row-level locking. |
| `SECRET_KEY` | `dev-only-secret-change-me` | JWT signing secret. **Must** be overridden with a strong random value outside local development. |
 
---

##  API Reference

Interactive Swagger UI documentation is available at `http://localhost:8000/docs` when the server is running.

### Transfer Funds
`POST /transfer/`

Executes a secure, ACID-compliant transfer between two accounts.

**Request Body:**
```json
{
  "sender_account_id": 1,
  "receiver_account_id": 2,
  "amount_paise": 5000,
  "idempotency_key": "req-987-xyz"
}
```

**Success Response (200 OK):**
```json
{
  "message": "Transfer successful",
  "transaction_id": 42
}
```

**Error Response (400 Bad Request - Insufficient Funds):**
```json
{
  "detail": "Insufficient funds"
}
```

---
### Other endpoints
 
| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/signup` | Create a user, returns a JWT |
| `POST` | `/auth/login` | Log in, returns a JWT |
| `POST` | `/accounts` | Create an account for the current user |
| `GET` | `/accounts/{id}` | Fetch an owned account |
| `GET` | `/accounts/{id}/transactions` | List ledger entries for an owned account |
| `POST` | `/accounts/{id}/deposit` | Deposit into an owned account |
| `POST` | `/accounts/{id}/withdraw` | Withdraw from an owned account |
| `GET` | `/health` | Liveness check |
 
---
##  Author

**Arshpreet Singh**
*  **LinkedIn:** [linkedin.com/in/arshpreet-singh-56089531a](https://linkedin.com/in/arshpreet-singh-56089531a)
*  **GitHub:** [github.com/Arshpreet-Singh-2005](https://github.com/Arshpreet-Singh-2005)
*  **Email:** sarshpreet653@gmail.com
