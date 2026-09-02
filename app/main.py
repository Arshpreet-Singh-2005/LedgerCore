"""
LedgerAPI - Mini core-banking backend

Centerpiece: POST /transfer moves money between two accounts atomically.
Both the debit and the credit happen inside a single DB transaction with
locked rows, in a deadlock-safe lock order (lower account ID first) — if
anything fails partway through, the whole transfer rolls back and neither
balance changes.
"""

import os
import secrets
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app import models, schemas
from app.auth import hash_password, verify_password, create_access_token
from app.deps import get_current_user, get_owned_account

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="LedgerAPI", version="1.0.0", lifespan=lifespan)


def to_minor(amount: float) -> int:
    """Convert a major-unit amount (e.g. rupees) to an integer minor-unit
    amount (paise) using round-half-up on cents to avoid float drift."""
    return round(amount * 100)


def generate_account_number(db: Session) -> str:
    for _ in range(10):
        candidate = "ACC" + "".join(secrets.choice("0123456789") for _ in range(10))
        if not db.query(models.Account).filter(models.Account.account_number == candidate).first():
            return candidate
    raise RuntimeError("Could not generate a unique account number")


@app.get("/health")
def health():
    return {"status": "healthy", "service": "LedgerAPI"}


# ── Auth ──

@app.post("/auth/signup", response_model=schemas.TokenResponse, status_code=201)
def signup(req: schemas.SignupRequest, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = models.User(username=req.username, hashed_password=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return schemas.TokenResponse(access_token=create_access_token(user.username))


@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return schemas.TokenResponse(access_token=create_access_token(user.username))


# ── Accounts ──

@app.post("/accounts", response_model=schemas.AccountResponse, status_code=201)
def create_account(
    req: schemas.AccountCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = models.Account(
        account_number=generate_account_number(db),
        owner_id=user.id,
        balance_minor=0,
        currency=req.currency.upper(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@app.get("/accounts/{account_id}", response_model=schemas.AccountResponse)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return get_owned_account(account_id, db, user)


@app.get("/accounts/{account_id}/transactions", response_model=list[schemas.LedgerEntryResponse])
def get_transactions(
    account_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    get_owned_account(account_id, db, user)  # ownership check
    entries = (
        db.query(models.LedgerEntry)
        .filter(models.LedgerEntry.account_id == account_id)
        .order_by(models.LedgerEntry.created_at.desc())
        .limit(limit)
        .all()
    )
    return entries


# ── Deposit / Withdraw ──

@app.post("/accounts/{account_id}/deposit", response_model=schemas.AccountResponse)
def deposit(
    account_id: int,
    req: schemas.DepositRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = (
        db.query(models.Account)
        .filter(models.Account.id == account_id)
        .with_for_update()
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this account")

    amount_minor = to_minor(req.amount)
    account.balance_minor += amount_minor
    account.version += 1
    db.add(models.LedgerEntry(
        account_id=account.id,
        entry_type=models.EntryType.DEPOSIT,
        amount_minor=amount_minor,
        balance_after_minor=account.balance_minor,
    ))
    db.commit()
    db.refresh(account)
    return account


@app.post("/accounts/{account_id}/withdraw", response_model=schemas.AccountResponse)
def withdraw(
    account_id: int,
    req: schemas.WithdrawRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = (
        db.query(models.Account)
        .filter(models.Account.id == account_id)
        .with_for_update()
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this account")

    amount_minor = to_minor(req.amount)
    if account.balance_minor < amount_minor:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    account.balance_minor -= amount_minor
    account.version += 1
    db.add(models.LedgerEntry(
        account_id=account.id,
        entry_type=models.EntryType.WITHDRAWAL,
        amount_minor=amount_minor,
        balance_after_minor=account.balance_minor,
    ))
    db.commit()
    db.refresh(account)
    return account


# ── Transfer — the centerpiece ──

@app.post("/transfer", response_model=schemas.TransferResponse)
def transfer(
    req: schemas.TransferRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    existing_out = db.query(models.LedgerEntry).filter(
        models.LedgerEntry.reference_id == req.idempotency_key,
        models.LedgerEntry.entry_type == models.EntryType.TRANSFER_OUT
    ).first()
    
    existing_in = db.query(models.LedgerEntry).filter(
        models.LedgerEntry.reference_id == req.idempotency_key,
        models.LedgerEntry.entry_type == models.EntryType.TRANSFER_IN
    ).first()

    if existing_out and existing_in:
        return schemas.TransferResponse(
            reference_id=req.idempotency_key,
            from_account_id=existing_out.account_id,
            to_account_id=existing_in.account_id,
            amount_minor=existing_out.amount_minor,
            from_balance_after_minor=existing_out.balance_after_minor,
            to_balance_after_minor=existing_in.balance_after_minor,
        )
    # Lock both account rows in a consistent order (lower ID first) to
    # prevent deadlocks when two transfers cross the same pair of accounts
    # in opposite directions at the same time.
    first_id, second_id = sorted([req.from_account_id, req.to_account_id])

    try:
        first = (
            db.query(models.Account)
            .filter(models.Account.id == first_id)
            .with_for_update()
            .first()
        )
        second = (
            db.query(models.Account)
            .filter(models.Account.id == second_id)
            .with_for_update()
            .first()
        )

        accounts = {first_id: first, second_id: second}
        from_account = accounts[req.from_account_id]
        to_account = accounts[req.to_account_id]

        if from_account is None or to_account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if from_account.owner_id != user.id:
            raise HTTPException(status_code=403, detail="You do not own the source account")

        amount_minor = to_minor(req.amount)
        if from_account.balance_minor < amount_minor:
            raise HTTPException(status_code=400, detail="Insufficient funds")

        reference_id = req.idempotency_key

        from_account.balance_minor -= amount_minor
        to_account.balance_minor += amount_minor
        from_account.version += 1
        to_account.version += 1

        db.add(models.LedgerEntry(
            account_id=from_account.id,
            entry_type=models.EntryType.TRANSFER_OUT,
            amount_minor=amount_minor,
            balance_after_minor=from_account.balance_minor,
            reference_id=reference_id,
        ))
        db.add(models.LedgerEntry(
            account_id=to_account.id,
            entry_type=models.EntryType.TRANSFER_IN,
            amount_minor=amount_minor,
            balance_after_minor=to_account.balance_minor,
            reference_id=reference_id,
        ))

        db.commit()

        return schemas.TransferResponse(
            reference_id=reference_id,
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            amount_minor=amount_minor,
            from_balance_after_minor=from_account.balance_minor,
            to_balance_after_minor=to_account.balance_minor,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise