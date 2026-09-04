import pytest
from app import models
from app.auth import hash_password
import concurrent.futures
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

def test_concurrent_transfers_prevent_double_spend(client, setup_accounts, auth_headers, db_session):
    """
    Fires 5 concurrent transfer requests of the full sender balance at the
    same receiver. Exactly one should succeed (first to acquire the lock);
    the rest must see the now-lower balance and correctly reject as
    insufficient funds — never double-spend the same money.
    """
    sender_id, receiver_id = setup_accounts

    def make_transfer(req_id):
        payload = {
            "from_account_id": sender_id,
            "to_account_id": receiver_id,
            "amount": 1000.00,
            "idempotency_key": f"concurrent-key-{req_id}",
        }
        return client.post("/transfer", json=payload, headers=auth_headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_transfer, i) for i in range(5)]
        responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    success_count = sum(1 for r in responses if r.status_code == 200)
    rejected_count = sum(1 for r in responses if r.status_code == 400)

    # Exactly ONE transfer should have succeeded; the rest correctly
    # rejected once the (now serialized) balance check saw insufficient funds.
    assert success_count == 1, f"Expected exactly 1 success, got {success_count}: {[r.status_code for r in responses]}"
    assert rejected_count == 4
    assert success_count + rejected_count == 5

    # Sender owns their account, so this is fine over the API. The receiver
    # account belongs to a *different* user (deliberately, to test
    # cross-account transfers) — testuser's token can't read it via the
    # API by design (ownership check), so verify it directly via the DB
    # instead, same as the original version of this test did.
    final_sender = client.get(f"/accounts/{sender_id}", headers=auth_headers).json()
    assert final_sender["balance_minor"] == 0

    db_session.expire_all()
    receiver = db_session.query(models.Account).filter_by(id=receiver_id).first()
    assert receiver.balance_minor == 100000