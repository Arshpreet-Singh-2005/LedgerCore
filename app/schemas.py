from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ── Auth ──

class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Accounts ──

class AccountCreate(BaseModel):
    currency: str = Field("INR", min_length=3, max_length=3)


class AccountResponse(BaseModel):
    id: int
    account_number: str
    balance_minor: int
    currency: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Money movement ──
# Amounts are accepted in *major* units (rupees/dollars) from the client for
# usability, then converted to minor units internally before touching the DB.

class DepositRequest(BaseModel):
    amount: float = Field(..., gt=0)

    @field_validator("amount")
    @classmethod
    def max_two_decimals(cls, v):
        if round(v, 2) != v:
            raise ValueError("amount supports at most 2 decimal places")
        return v


class WithdrawRequest(DepositRequest):
    pass


class TransferRequest(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: float = Field(..., gt=0)
    idempotency_key: str = Field(..., min_length=8, max_length=64)
    
    @field_validator("amount")
    @classmethod
    def max_two_decimals(cls, v):
        if round(v, 2) != v:
            raise ValueError("amount supports at most 2 decimal places")
        return v

    @field_validator("to_account_id")
    @classmethod
    def not_self_transfer(cls, v, info):
        if "from_account_id" in info.data and v == info.data["from_account_id"]:
            raise ValueError("from_account_id and to_account_id must differ")
        return v


class LedgerEntryResponse(BaseModel):
    id: int
    entry_type: str
    amount_minor: int
    balance_after_minor: int
    reference_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class TransferResponse(BaseModel):
    reference_id: str
    from_account_id: int
    to_account_id: int
    amount_minor: int
    from_balance_after_minor: int
    to_balance_after_minor: int