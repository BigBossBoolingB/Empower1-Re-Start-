import pytest
import time
import hashlib
import json
from empower1.blockchain.transaction import Transaction
from empower1.blockchain.wallet import Wallet # Needed for signing

# Test basic Transaction creation and attributes with new crypto integration
def test_transaction_creation_crypto(alice_wallet, bob_wallet):
    """Test Transaction creation with sender/receiver addresses, amount, etc."""
    tx = Transaction(
        sender_address=alice_wallet.address,
        receiver_address=bob_wallet.address,
        amount=50.0,
        asset_id="EMP_CryptoCoin",
        fee=0.05,
        metadata={"reason": "Crypto test payment"}
    )
    assert tx.sender_address == alice_wallet.address
    assert tx.receiver_address == bob_wallet.address
    assert tx.amount == 50.0
    assert tx.asset_id == "EMP_CryptoCoin"
    assert tx.fee == 0.05
    assert tx.metadata == {"reason": "Crypto test payment"}
    assert tx.timestamp is not None
    assert tx.signature_hex is None # Signature is None until signed

    # Test transaction_id calculation
    expected_data_for_signing = (
        f"{alice_wallet.address}{bob_wallet.address}{50.0:.8f}{'EMP_CryptoCoin'}"
        f"{tx.timestamp:.6f}{0.05:.8f}"
        f"{json.dumps({'reason': 'Crypto test payment'}, sort_keys=True)}"
    ).encode('utf-8')
    expected_tx_id = hashlib.sha256(expected_data_for_signing).hexdigest()
    assert tx.transaction_id == expected_tx_id

def test_transaction_creation_minimal_crypto(alice_wallet, bob_wallet):
    """Test minimal Transaction creation."""
    tx = Transaction(sender_address=alice_wallet.address, receiver_address=bob_wallet.address, amount=5.0)
    assert tx.sender_address == alice_wallet.address
    assert tx.receiver_address == bob_wallet.address
    assert tx.amount == 5.0
    assert tx.asset_id == "EPC" # Default asset_id updated
    assert tx.fee == 0.0 # Default fee
    assert tx.metadata == {} # Default metadata

def test_get_data_for_signing_determinism(alice_wallet, bob_wallet):
    """Test that get_data_for_signing is deterministic."""
    ts = time.time()
    tx1_data = {
        "sender_address": alice_wallet.address, "receiver_address": bob_wallet.address,
        "amount": 10.0, "asset_id": "coin", "timestamp": ts, "fee": 0.1,
        "metadata": {"b": 2, "a": 1} # Order should be fixed by json.dumps(sort_keys=True)
    }
    tx1 = Transaction(**tx1_data)

    tx2_data = { # Same data, different metadata order initially
        "sender_address": alice_wallet.address, "receiver_address": bob_wallet.address,
        "amount": 10.0, "asset_id": "coin", "timestamp": ts, "fee": 0.1,
        "metadata": {"a": 1, "b": 2}
    }
    tx2 = Transaction(**tx2_data)

    assert tx1.get_data_for_signing() == tx2.get_data_for_signing()
    assert tx1.transaction_id == tx2.transaction_id

# Test signing and verification
def test_transaction_signing_and_verification(alice_wallet, bob_wallet):
    """Test signing a transaction and then verifying it successfully."""
    tx = Transaction(
        sender_address=alice_wallet.address,
        receiver_address=bob_wallet.address,
        amount=100.0,
        asset_id="EMP_Main",
        metadata={"memo": "Lunch money"}
    )
    assert tx.signature_hex is None

    # Sign the transaction
    tx.sign(alice_wallet)
    assert tx.signature_hex is not None

    # Verify with the correct public key
    alice_public_key_hex = alice_wallet.get_public_key_hex()
    assert tx.verify_signature(sender_public_key_hex=alice_public_key_hex) is True

def test_transaction_verification_fail_wrong_key(alice_wallet, bob_wallet):
    """Test that verification fails if the wrong public key is used."""
    tx = Transaction(
        sender_address=alice_wallet.address,
        receiver_address=bob_wallet.address,
        amount=10.0
    )
    tx.sign(alice_wallet) # Signed by Alice

    # Try to verify with Bob's public key
    bob_public_key_hex = bob_wallet.get_public_key_hex()
    assert tx.verify_signature(sender_public_key_hex=bob_public_key_hex) is False

def test_transaction_verification_fail_tampered_data(alice_wallet, bob_wallet):
    """Test that verification fails if transaction data is tampered after signing."""
    tx = Transaction(
        sender_address=alice_wallet.address,
        receiver_address=bob_wallet.address,
        amount=20.0,
        metadata={"original": True}
    )
    tx.sign(alice_wallet)
    original_signature_hex = tx.signature_hex

    # Tamper with data (e.g., amount)
    tx.amount = 200.0
    # Note: The signature_hex is still the old one.
    # The transaction_id would also change if recalculated, but verify_signature uses get_data_for_signing()

    alice_public_key_hex = alice_wallet.get_public_key_hex()
    assert tx.verify_signature(sender_public_key_hex=alice_public_key_hex) is False

    # Restore amount, verify it works again
    tx.amount = 20.0
    assert tx.verify_signature(sender_public_key_hex=alice_public_key_hex) is True
    assert tx.signature_hex == original_signature_hex # Ensure signature wasn't re-signed by mistake

def test_transaction_verification_fail_no_signature(alice_wallet, bob_wallet):
    """Test verification fails if the transaction is not signed."""
    tx = Transaction(
        sender_address=alice_wallet.address,
        receiver_address=bob_wallet.address,
        amount=5.0
    )
    assert tx.signature_hex is None
    alice_public_key_hex = alice_wallet.get_public_key_hex()
    assert tx.verify_signature(sender_public_key_hex=alice_public_key_hex) is False


def test_transaction_to_dict_crypto(sample_transaction_signed): # Uses fixture from conftest
    """Test the to_dict method of a signed Transaction."""
    tx = sample_transaction_signed # This transaction is already signed by alice_wallet in fixture
    tx_dict = tx.to_dict()

    assert tx_dict["transaction_id"] == tx.transaction_id
    assert tx_dict["sender_address"] == tx.sender_address
    assert tx_dict["receiver_address"] == tx.receiver_address
    assert tx_dict["amount"] == tx.amount
    assert tx_dict["asset_id"] == tx.asset_id
    assert tx_dict["timestamp"] == tx.timestamp
    assert tx_dict["fee"] == tx.fee
    assert tx_dict["signature_hex"] == tx.signature_hex
    assert tx_dict["metadata"] == tx.metadata

def test_transaction_repr_crypto(sample_transaction_signed):
    """Test the __repr__ method of a signed Transaction."""
    tx = sample_transaction_signed
    tx_repr = repr(tx)

    assert tx.transaction_id in tx_repr
    assert tx.sender_address in tx_repr
    assert tx.receiver_address in tx_repr
    assert str(tx.amount) in tx_repr
    assert tx.asset_id in tx_repr
    assert "Signed: Yes" in tx_repr

    unsigned_tx = Transaction(tx.sender_address, tx.receiver_address, tx.amount)
    unsigned_repr = repr(unsigned_tx)
    assert "Signed: No" in unsigned_repr

# To run these tests: `pytest` in the terminal from the project root.
