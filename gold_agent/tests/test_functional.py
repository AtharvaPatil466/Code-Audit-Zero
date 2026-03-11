import requests
import pytest
import os

BASE_URL = os.getenv("TARGET_URL", "http://target_app:8000")

def test_api_is_online():
    """Ensure the API is responsive."""
    try:
        # Use a very short timeout for the first check
        res = requests.get(f"{BASE_URL}/docs", timeout=1)
        assert res.status_code == 200
    except Exception:
        pytest.fail("API_DOWN")

def test_user_wallet_access():
    """Ensure normal users can still access their wallet (Regression Check)."""
    headers = {"user-id": "1"} # Alice
    res = requests.get(f"{BASE_URL}/wallet", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "balance" in data
    assert isinstance(data["balance"], (int, float))

def test_buy_item_normal():
    """Ensure normal users can still buy items."""
    headers = {"user-id": "1"}
    payload = {"item": "apple", "quantity": 1}
    res = requests.post(f"{BASE_URL}/buy", json=payload, headers=headers)
    
    # It might be 200 or 400 (if insufficient funds), but NOT 500 or 404
    assert res.status_code in [200, 400] 
    if res.status_code == 200:
        assert "new_balance" in res.json()
