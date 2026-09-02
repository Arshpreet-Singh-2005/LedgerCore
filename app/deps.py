from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.auth import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    username = decode_access_token(token)
    if username is None:
        raise credentials_error

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_error
    return user


def get_owned_account(account_id: int, db: Session, user: models.User) -> models.Account:
    """Fetch an account and verify the current user owns it — prevents
    one user from depositing/withdrawing/transferring on someone else's account."""
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this account")
    return account