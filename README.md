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

* ** Double-Entry Ledger** — Every financial movement creates immutable `DEBIT` and `CREDIT` records, ensuring a non-repudiable audit trail.
* ** ACID Transactions** — Transfer operations are wrapped in atomic transaction blocks. If any step fails (e.g., validation, server crash), the entire operation rolls back.
* ** Concurrency Safe (Row-Level Locking)** — Utilizes `SELECT ... FOR UPDATE` with ordered ID locking to prevent race conditions (double-spending) and deadlocks during simultaneous transfers.
* ** Integer Currency Handling** — All balances are stored as integers (paise/cents) rather than floats to eliminate floating-point precision errors.
* ** Idempotency** — API supports `idempotency_key` checks on transfers, preventing duplicate transactions if a client retries a network request.
* ** JWT Authentication** — Secure stateless authentication routing ensuring users can only interact with their own accounts.

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
│   ├── main.py              # FastAPI application setup & routing
│   ├── models.py            # SQLAlchemy ORM models (Users, Accounts, Ledger)
│   ├── database.py          # PostgreSQL connection & session management
│   ├── auth.py              # JWT hashing & token verification logic
│   └── schemas.py           # Pydantic models for request/response validation
├── tests/
│   ├── conftest.py          # Pytest fixtures (DB setup/teardown for tests)
│   ├── test_auth.py         # Unit tests for registration and login
│   └── test_transfers.py    # Concurrency, insufficient funds, & idempotency tests
├── docker-compose.yml       # Multi-container orchestration (API + Postgres)
├── Dockerfile               # API image build instructions
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

##  Local Setup (Docker)

The easiest way to run LedgerCore is via Docker, which automatically spins up the FastAPI server alongside a fully configured PostgreSQL database.

**1. Clone the repository**
```bash
git clone https://github.com/Arshpreet-Singh-2005/LedgerCore.git
cd LedgerCore
```

**2. Build and start the containers**
```bash
docker compose up --build
```
*The API is now running at `http://localhost:8000`.*

---

##  Running the Test Suite

LedgerCore includes a comprehensive Pytest suite validating edge cases like insufficient funds, invalid account routing, and idempotency locks.

```bash
# Run tests with verbose output
pytest tests/ -v
```

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

##  Author

**Arshpreet Singh**
*  **LinkedIn:** [linkedin.com/in/arshpreet-singh-56089531a](https://linkedin.com/in/arshpreet-singh-56089531a)
*  **GitHub:** [github.com/Arshpreet-Singh-2005](https://github.com/Arshpreet-Singh-2005)
*  **Email:** sarshpreet653@gmail.com
