import os
import pytest
from fastapi.testclient import TestClient

# Point at a dedicated test DB *before* importing app.database, so we reuse
# its engine (and the SQLite BEGIN IMMEDIATE serialization fix on it)
# instead of building a second, divergent engine here.
TEST_DB_PATH = "./test_ledger.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.main import app  # noqa: E402
from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models  # noqa: E402
from app.auth import hash_password  # noqa: E402


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    # No dependency override: the app uses its real get_db, which already
    # opens a fresh SessionLocal() per request. That's what makes concurrent
    # requests safe — every request gets its own session/connection, and
    # SQLite's own file-level locking (via our BEGIN IMMEDIATE fix)
    # serializes the writes correctly across them.
    return TestClient(app)


@pytest.fixture
def test_user(db_session):
    user = models.User(username="testuser", hashed_password=hash_password("securepass"))
    db_session.add(user)
    db_session.commit()
    # No .refresh() here: with expire_on_commit=False, user.id is already
    # populated after commit — an explicit refresh would issue a fresh
    # SELECT that (correctly) grabs the write lock via BEGIN IMMEDIATE,
    # holding it open for the rest of this fixture's lifetime for no reason.
    return user


@pytest.fixture
def auth_headers(client, test_user):
    response = client.post("/auth/login", data={"username": "testuser", "password": "securepass"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
