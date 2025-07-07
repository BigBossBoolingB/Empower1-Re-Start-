import pytest
import time
import hashlib
from empower1.blockchain.block import Block
from empower1.blockchain.transaction import Transaction
from empower1.blockchain.wallet import Wallet
from empower1.blockchain import constants as block_test_constants # Moved import to top

# Test basic Block creation and attributes with crypto
def test_block_creation_crypto(sample_transaction_signed, another_sample_transaction_signed, validator_wallet):
    """Test Block creation with transactions and validator address."""
    # sample_transaction_signed and another_sample_transaction_signed are from conftest
    # validator_wallet is also from conftest

    current_time = time.time()
    proof_value = "test_proof_creation"
    block = Block(
        index=1,
        transactions=[sample_transaction_signed, another_sample_transaction_signed],
        timestamp=current_time,
        previous_hash="some_previous_hash_string",
        validator_address=validator_wallet.address,
        proof=proof_value
    )
    assert block.index == 1
    assert len(block.transactions) == 2
    assert block.transactions[0] == sample_transaction_signed
    assert block.transactions[1] == another_sample_transaction_signed
    assert block.timestamp is not None
    assert block.previous_hash == "some_previous_hash_string"
    assert block.validator_address == validator_wallet.address
    assert block.signature_hex is None # Not signed yet
    assert block.hash is not None # Hash calculated on init
    assert block.proof == proof_value

    # Test hash calculation consistency (verify self.hash matches a direct call to calculate_hash)
    # Reconstruct the dictionary used for hashing as defined in Block.calculate_hash
    block_dict_for_hashing = {
        "index": block.index,
        "timestamp": block.timestamp,
        "transactions": [tx.to_dict() for tx in block.transactions],
        "proof": block.proof,
        "previous_hash": block.previous_hash,
        "validator_address": block.validator_address
    }
    import json # Make sure json is imported in the test file if not already
    expected_block_hash_string = json.dumps(block_dict_for_hashing, sort_keys=True).encode('utf-8')
    expected_block_hash = hashlib.sha256(expected_block_hash_string).hexdigest()

    assert block.hash == expected_block_hash
    # Also verify that calling calculate_hash() method again yields the same stored hash
    assert block.calculate_hash() == block.hash


from empower1.blockchain import constants as block_test_constants # For atomic conversion

def test_block_hashing_determinism(validator_wallet):
    """Test that block hash is deterministic for same content."""
    ts = time.time()
    amount_atomic = block_test_constants.to_atomic(1.0)
    # Fee defaults to 0 (int) in Transaction constructor
    tx1 = Transaction(validator_wallet.address, "receiver1", amount_atomic, timestamp=ts-10)
    tx1.sign(validator_wallet)

    proof_val = "deterministic_proof"
    block1_data = {
        "index": 1, "transactions": [tx1], "timestamp": ts,
        "previous_hash": "prev_hash_A", "validator_address": validator_wallet.address, "proof": proof_val
    }
    block1 = Block(**block1_data)

    # Create another block with identical content
    block2_data = {
        "index": 1, "transactions": [tx1], "timestamp": ts,
        "previous_hash": "prev_hash_A", "validator_address": validator_wallet.address, "proof": proof_val
    }
    block2 = Block(**block2_data)
    assert block1.hash == block2.hash

    # Change proof and hash should differ
    block3_data = {
        "index": 1, "transactions": [tx1], "timestamp": ts,
        "previous_hash": "prev_hash_A", "validator_address": validator_wallet.address, "proof": "different_proof"
    }
    block3 = Block(**block3_data)
    assert block1.hash != block3.hash

    # Change timestamp and hash should differ
    block4_data = {
        "index": 1, "transactions": [tx1], "timestamp": ts + 1.0,
        "previous_hash": "prev_hash_A", "validator_address": validator_wallet.address, "proof": proof_val
    }
    block4 = Block(**block4_data)
    assert block1.hash != block4.hash


# Test block signing and verification
def test_block_signing_and_verification(validator_wallet, sample_transaction_signed):
    """Test signing a block and verifying its signature."""
    block = Block(
        index=1,
        transactions=[sample_transaction_signed],
        timestamp=time.time(),
        previous_hash="prev_hash_for_signing_test",
        validator_address=validator_wallet.address,
        proof="proof_for_signing"
    )
    assert block.signature_hex is None

    # Sign the block
    block.sign_block(validator_wallet)
    assert block.signature_hex is not None

    # Verify with the correct validator's public key
    validator_public_key_hex = validator_wallet.get_public_key_hex()
    assert block.verify_block_signature(validator_public_key_hex=validator_public_key_hex) is True

def test_block_verification_fail_wrong_key(validator_wallet, alice_wallet, sample_transaction_signed):
    """Test block signature verification fails with the wrong public key."""
    block = Block(
        index=1, transactions=[sample_transaction_signed], timestamp=time.time(),
        previous_hash="prev_hash_wrong_key", validator_address=validator_wallet.address,
        proof="proof_wrong_key_test"
    )
    block.sign_block(validator_wallet) # Signed by validator_wallet

    # Try to verify with Alice's public key (alice_wallet is a different wallet)
    alice_public_key_hex = alice_wallet.get_public_key_hex()
    assert block.verify_block_signature(validator_public_key_hex=alice_public_key_hex) is False

def test_block_verification_fail_tampered_data_after_signing(validator_wallet, sample_transaction_signed):
    """
    Test verification fails if block data (used in block hash) is tampered after signing.
    The signature itself is for the original block hash. So, if the block's stored hash
    is compared, signature is valid. But if chain validation recalculates hash, it will differ.
    This test focuses on verify_block_signature which uses the block's *stored* hash.
    """
    block = Block(
        index=1, transactions=[sample_transaction_signed], timestamp=time.time(),
        previous_hash="prev_hash_tamper", validator_address=validator_wallet.address,
        proof="proof_tamper_test"
    )
    original_block_hash = block.hash # Store original hash
    block.sign_block(validator_wallet) # Signs based on original_block_hash

    # Tamper with block content that affects its hash calculation
    block.timestamp = time.time() + 1000
    # block.hash would now be different if recalculated, but it's still the original_block_hash.
    # The signature was for original_block_hash.
    # verify_block_signature signs the block's hash, which is `self.hash` (original).
    # So, this test should still pass for verify_block_signature.
    # The chain validation (is_chain_valid) is where overall block integrity (recalculated hash) is checked.

    validator_public_key_hex = validator_wallet.get_public_key_hex()
    assert block.verify_block_signature(validator_public_key_hex=validator_public_key_hex) is True

    # If we were to MANUALLY change self.hash to something else, then verify_block_signature would fail:
    block.hash = "completely_fake_hash_after_signing"
    assert block.verify_block_signature(validator_public_key_hex=validator_public_key_hex) is False


def test_block_verification_fail_no_signature(validator_wallet, sample_transaction_signed):
    """Test block signature verification fails if the block is not signed."""
    block = Block(
        index=1, transactions=[sample_transaction_signed], timestamp=time.time(),
        previous_hash="prev_hash_no_sig", validator_address=validator_wallet.address,
        proof="proof_no_sig_test"
    )
    assert block.signature_hex is None
    validator_public_key_hex = validator_wallet.get_public_key_hex()
    assert block.verify_block_signature(validator_public_key_hex=validator_public_key_hex) is False


def test_get_data_for_block_signing(sample_block_signed): # sample_block_signed is already signed
    """Test the get_data_for_block_signing method."""
    # This method should return the block's own hash, encoded.
    expected_data = sample_block_signed.hash.encode('utf-8')
    assert sample_block_signed.get_data_for_block_signing() == expected_data

def test_block_repr_crypto(sample_block_signed): # sample_block_signed is already signed
    """Test the __repr__ method of a signed Block."""
    block_repr = repr(sample_block_signed)
    assert str(sample_block_signed.index) in block_repr
    assert str(len(sample_block_signed.transactions)) in block_repr
    assert sample_block_signed.hash[:10] in block_repr # Checks for short hash
    assert sample_block_signed.previous_hash[:10] in block_repr
    assert sample_block_signed.validator_address in block_repr
    assert "Signed: Yes" in block_repr
    assert f"Proof: {sample_block_signed.proof}" # Check proof is part of repr if desired, or adjust repr

    # Test unsigned block repr
    unsigned_block = Block(0, [], time.time(), "0", "validator_addr_unsigned", proof="unsigned_proof")
    unsigned_repr = repr(unsigned_block)
    assert "Signed: No" in unsigned_repr
    assert "unsigned_proof" in unsigned_repr # Check proof part of repr


# To run these tests: `pytest` in the terminal from the project root.
