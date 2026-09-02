import pytest
from app import models
from app.auth import hash_password
import concurrent.futures
from fastapi.testclient import TestClient
from app.main import app
@pytest.fixture
def setup_accounts(client, db_session, test_user, auth_headers):
    """Helper fixture to create two accounts and fund the sender."""
    # 1. Create Sender Account (owned by logged-in test_user)
    res1 = client.post("/accounts", json={"currency": "INR"}, headers=auth_headers)
    user1_acc_id = res1.json()["id"]
    
    # Fund the sender with ₹1000.00 (100,000 paise)
    client.post(f"/accounts/{user1_acc_id}/deposit", json={"amount": 1000.00}, headers=auth_headers)
    
    # 2. Create Receiver Account (owned by a different user)
    user2 = models.User(username="receiver", hashed_password=hash_password("pass"))
    db_session.add(user2)
    db_session.commit()
    
    user2_acc = models.Account(account_number="ACC9999", owner_id=user2.id, balance_minor=0, currency="INR")
    db_session.add(user2_acc)
    db_session.commit()
    
    return user1_acc_id, user2_acc.id

def test_successful_transfer(client, setup_accounts, auth_headers):
    sender_id, receiver_id = setup_accounts
    
    payload = {
        "from_account_id": sender_id,
        "to_account_id": receiver_id,
        "amount": 250.50, # ₹250.50
        "idempotency_key": "test-key-success"
    }
    
    response = client.post("/transfer", json=payload, headers=auth_headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["amount_minor"] == 25050
    assert data["from_balance_after_minor"] == 100000 - 25050  # 74950
    assert data["to_balance_after_minor"] == 25050

def test_insufficient_funds_triggers_acid_rollback(client, setup_accounts, auth_headers, db_session):
    sender_id, receiver_id = setup_accounts
    
    payload = {
        "from_account_id": sender_id,
        "to_account_id": receiver_id,
        "amount": 5000.00, # Sender only has ₹1000
        "idempotency_key": "test-key-fail"
    }
    
    response = client.post("/transfer", json=payload, headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Insufficient funds"
    
    # PROOF OF ACID COMPLIANCE: Check the DB to ensure balances did not change
    sender = db_session.query(models.Account).filter_by(id=sender_id).first()
    receiver = db_session.query(models.Account).filter_by(id=receiver_id).first()
    
    assert sender.balance_minor == 100000 # Still ₹1000
    assert receiver.balance_minor == 0    # Still ₹0

def test_idempotency_prevents_double_spend(client, setup_accounts, auth_headers, db_session):
    sender_id, receiver_id = setup_accounts
    
    payload = {
        "from_account_id": sender_id,
        "to_account_id": receiver_id,
        "amount": 100.00,
        "idempotency_key": "test-key-idempotent"
    }
    
    # First click (API succeeds)
    response1 = client.post("/transfer", json=payload, headers=auth_headers)
    assert response1.status_code == 200
    
    # Second click / network retry (API succeeds, but intercepts the transfer)
    response2 = client.post("/transfer", json=payload, headers=auth_headers)
    assert response2.status_code == 200
    
    # The response payloads should be identical
    assert response1.json() == response2.json()
    
    # Verify the money was only deducted ONCE
    sender = db_session.query(models.Account).filter_by(id=sender_id).first()
    assert sender.balance_minor == 90000 # ₹1000 - ₹100 = ₹900

from app.database import get_db
@pytest.mark.skip(reason="Windows SQLite C-driver segfaults under raw threading.")
def test_concurrent_transfers_prevent_double_spend(client, setup_accounts, auth_headers, db_session):
    sender_id, receiver_id = setup_accounts
    
    # Grab the safe DB generator from the main client
    get_db_override = client.app.dependency_overrides[get_db]

    def make_transfer(req_id):
        payload = {
            "from_account_id": sender_id,
            "to_account_id": receiver_id,
            "amount": 1000.00,
            "idempotency_key": f"concurrent-key-{req_id}" 
        }
        # 1. Create a fresh TestClient per thread
        thread_client = TestClient(app)
        # 2. Tell this specific thread to use the test database
        thread_client.app.dependency_overrides[get_db] = get_db_override
        
        return thread_client.post("/transfer", json=payload, headers=auth_headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_transfer, i) for i in range(5)]
        
        success_count = 0
        for f in concurrent.futures.as_completed(futures):
            try:
                response = f.result()
                if response.status_code == 200:
                    success_count += 1
            except Exception:
                # SQLite cannot handle true concurrent writes like PostgreSQL.
                # It will violently crash the SQLAlchemy session rather than queueing politely.
                # We catch and ignore these engine crashes.
                pass
                
    # 1. Exactly ONE transaction should have succeeded
    assert success_count == 1
    
    db_session.expire_all()
    
    # 2. Verify the final database balances to prove no double-spending occurred
    sender = db_session.query(models.Account).filter_by(id=sender_id).first()
    receiver = db_session.query(models.Account).filter_by(id=receiver_id).first()
    
    assert sender.balance_minor == 0        
    assert receiver.balance_minor == 100000