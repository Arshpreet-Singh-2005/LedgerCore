"""
LedgerAPI - ORM models

Schema design:
  users           — login identity.
  accounts        — belongs to a user. `balance_minor` is an INTEGER in
                     minor currency units (paise/cents), never a float —
                     floats introduce rounding errors that are unacceptable
                     for money. `version` supports optimistic locking as a
                     second line of defense alongside row-level locking.
  ledger_entries  — one immutable row per money movement. Never updated or
                     deleted, only inserted — a proper audit trail rather
                     than a balance column that silently changes. Transfers
                     write two linked rows (TRANSFER_OUT + TRANSFER_IN)
                     sharing a `reference_id` so both legs can be traced
                     back to the same transfer.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, ForeignKey, Enum, Index
)
from sqlalchemy.orm import relationship

from app.database import Base


class EntryType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    accounts = relationship("Account", back_populates="owner")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_number = Column(String(20), unique=True, nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    balance_minor = Column(BigInteger, nullable=False, default=0)  # paise/cents — never a float
    currency = Column(String(3), nullable=False, default="INR")
    version = Column(Integer, nullable=False, default=0)  # optimistic-locking guard
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="accounts")
    entries = relationship("LedgerEntry", back_populates="account", cascade="all, delete-orphan")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    entry_type = Column(Enum(EntryType), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)  # always positive; direction is in entry_type
    balance_after_minor = Column(BigInteger, nullable=False)  # snapshot for audit/debugging
    reference_id = Column(String(36), nullable=True, index=True)  # links both legs of a transfer
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    account = relationship("Account", back_populates="entries")


Index("ix_account_created_at", LedgerEntry.account_id, LedgerEntry.created_at)