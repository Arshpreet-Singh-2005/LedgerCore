import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.pool import NullPool
from app.main import app
from app.database import Base, get_db
from app import models
from app.auth import hash_password

# 1. Setup In-Memory SQLite Database (blazing fast, resets every test)
TEST_DB_PATH = "./test_ledger.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"

# tests/conftest.py
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    # The timeout tells SQLite to queue concurrent requests instead of crashing!
    connect_args={"check_same_thread": False, "timeout": 15.0}, 
    poolclass=NullPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    # Create tables before each test
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Drop tables after each test to ensure a clean slate
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    # Override FastAPI's database dependency to use our test DB
    db = TestingSessionLocal()
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def test_user(db_session):
    # Automatically create a user for tests that require login
    user = models.User(username="testuser", hashed_password=hash_password("securepass"))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

@pytest.fixture
def auth_headers(client, test_user):
    # Automatically log in the test_user and return the JWT header
    response = client.post("/auth/login", data={"username": "testuser", "password": "securepass"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

