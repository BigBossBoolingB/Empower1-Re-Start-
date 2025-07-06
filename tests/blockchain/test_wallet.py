import pytest
from empower1.blockchain.wallet import Wallet
import hashlib
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec

# Test Wallet creation (new wallet)
def test_wallet_creation_new(alice_wallet): # Using fixture from conftest
    """Test creating a new Wallet instance with real crypto keys."""
    wallet = alice_wallet
    assert wallet.private_key is not None
    assert isinstance(wallet.private_key, ec.EllipticCurvePrivateKey)
    assert wallet.public_key is not None
    assert isinstance(wallet.public_key, ec.EllipticCurvePublicKey)
    assert wallet.address is not None
    assert wallet.address.startswith("Emp1")
    assert len(wallet.address) == 40 + 4 # "Emp1" + 40 hex chars for 20 bytes hash

def test_wallet_uniqueness(alice_wallet, bob_wallet): # Fixtures provide unique wallets
    """Test that two newly created wallets are unique."""
    assert alice_wallet.private_key != bob_wallet.private_key
    # Compare serialized public keys as objects might differ in memory location
    assert alice_wallet.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint # Corrected
    ) != bob_wallet.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint # Corrected
    )
    assert alice_wallet.address != bob_wallet.address

# Test Wallet loading from existing private key PEM hex
def test_wallet_loading_from_private_key_pem_hex(alice_wallet):
    """Test creating a Wallet by loading an existing private key PEM hex."""
    original_wallet = alice_wallet
    private_key_pem_hex = original_wallet.get_private_key_pem_hex()

    loaded_wallet = Wallet(private_key_pem_hex=private_key_pem_hex, curve=original_wallet.curve)

    # Compare private keys by serializing them as they are objects
    original_priv_bytes = original_wallet.private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    )
    loaded_priv_bytes = loaded_wallet.private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    )
    assert loaded_priv_bytes == original_priv_bytes

    # Compare public keys by serializing them
    original_pub_bytes = original_wallet.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint # Corrected
    )
    loaded_pub_bytes = loaded_wallet.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint # Corrected
    )
    assert loaded_pub_bytes == original_pub_bytes

    assert loaded_wallet.address == original_wallet.address
    assert loaded_wallet.get_private_key_pem_hex() == private_key_pem_hex

def test_wallet_loading_invalid_pem_hex():
    """Test loading wallet with invalid PEM hex for private key."""
    with pytest.raises(ValueError) as excinfo:
        Wallet(private_key_pem_hex="this_is_not_valid_hex_obviously")
    assert "Failed to load private key" in str(excinfo.value) # More specific check

# Test key getters (PEM for private, X962 hex for public)
def test_wallet_key_getters(alice_wallet):
    wallet = alice_wallet
    priv_pem_hex = wallet.get_private_key_pem_hex()
    pub_hex_uncompressed = wallet.get_public_key_hex() # Default uncompressed
    pub_hex_compressed = wallet.get_public_key_hex(compressed=True)

    assert isinstance(priv_pem_hex, str)
    assert isinstance(pub_hex_uncompressed, str)
    assert isinstance(pub_hex_compressed, str)

    # Check if private key PEM can be loaded back (basic check)
    try:
        serialization.load_pem_private_key(bytes.fromhex(priv_pem_hex), password=None)
    except Exception as e:
        pytest.fail(f"Failed to load private key from its PEM hex: {e}")

    # Check if public key hex can be loaded back (uncompressed)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(wallet.curve, bytes.fromhex(pub_hex_uncompressed))
    except Exception as e:
        pytest.fail(f"Failed to load uncompressed public key from its X962 hex: {e}")

    # Check if public key hex can be loaded back (compressed)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(wallet.curve, bytes.fromhex(pub_hex_compressed))
    except Exception as e:
        pytest.fail(f"Failed to load compressed public key from its X962 hex: {e}")

    assert len(pub_hex_compressed) < len(pub_hex_uncompressed)


# Test signing data
def test_wallet_sign_data(alice_wallet):
    """Test the sign_data method with actual crypto."""
    wallet = alice_wallet
    data_to_sign_str = "Test data for signing by wallet"
    data_hash = hashlib.sha256(data_to_sign_str.encode('utf-8')).digest()

    signature_der = wallet.sign_data(data_hash)
    assert isinstance(signature_der, bytes)
    assert len(signature_der) > 0 # DER signatures are not empty

    # Attempt to verify this signature (basic check that it's verifiable by its own public key)
    try:
        wallet.public_key.verify(signature_der, data_hash, ec.ECDSA(hashes.SHA256()))
    except Exception as e:
        pytest.fail(f"Signature verification failed with wallet's own public key: {e}")

def test_wallet_sign_data_requires_bytes(alice_wallet):
    """Test that sign_data raises TypeError if data is not bytes."""
    with pytest.raises(TypeError):
        alice_wallet.sign_data("this is a string, not bytes")


# Test signature verification (static method)
def test_wallet_verify_signature_valid(alice_wallet):
    """Test Wallet.verify_signature with a valid signature."""
    wallet = alice_wallet
    data_str = "Data for static verification test"
    data_hash = hashlib.sha256(data_str.encode('utf-8')).digest()
    signature_der = wallet.sign_data(data_hash)

    pub_key_hex = wallet.get_public_key_hex() # Uncompressed

    is_valid = Wallet.verify_signature(
        public_key_bytes_hex=pub_key_hex,
        data_hash=data_hash,
        signature_der=signature_der,
        curve=wallet.curve
    )
    assert is_valid is True

def test_wallet_verify_signature_invalid_signature(alice_wallet):
    """Test Wallet.verify_signature with an invalid (tampered) signature."""
    wallet = alice_wallet
    data_str = "Data for invalid signature test"
    data_hash = hashlib.sha256(data_str.encode('utf-8')).digest()
    signature_der = wallet.sign_data(data_hash)

    tampered_signature_der = signature_der[:-1] + b'\x00' # Modify last byte

    pub_key_hex = wallet.get_public_key_hex()
    is_valid = Wallet.verify_signature(pub_key_hex, data_hash, tampered_signature_der, curve=wallet.curve)
    assert is_valid is False

def test_wallet_verify_signature_wrong_public_key(alice_wallet, bob_wallet):
    """Test Wallet.verify_signature with a correct signature but wrong public key."""
    signer_wallet = alice_wallet
    verifier_wallet_public_key_hex = bob_wallet.get_public_key_hex() # Bob's pubkey

    data_str = "Data signed by Alice, verified by Bob's key"
    data_hash = hashlib.sha256(data_str.encode('utf-8')).digest()
    signature_der = signer_wallet.sign_data(data_hash) # Alice signs

    is_valid = Wallet.verify_signature(verifier_wallet_public_key_hex, data_hash, signature_der, curve=signer_wallet.curve)
    assert is_valid is False

def test_wallet_verify_signature_wrong_data_hash(alice_wallet):
    """Test Wallet.verify_signature with correct signature and pubkey but wrong data hash."""
    wallet = alice_wallet
    data_str_original = "Original data"
    data_hash_original = hashlib.sha256(data_str_original.encode('utf-8')).digest()
    signature_der = wallet.sign_data(data_hash_original)

    data_str_tampered = "Tampered data"
    data_hash_tampered = hashlib.sha256(data_str_tampered.encode('utf-8')).digest()

    pub_key_hex = wallet.get_public_key_hex()
    is_valid = Wallet.verify_signature(pub_key_hex, data_hash_tampered, signature_der, curve=wallet.curve)
    assert is_valid is False

def test_wallet_verify_signature_malformed_inputs():
    """Test Wallet.verify_signature with malformed inputs that should lead to False not errors."""
    # Malformed public key hex
    assert Wallet.verify_signature("not-a-hex-string", b"data_hash", b"sig_der") is False
    # Malformed signature DER (e.g., not valid hex if it were passed as hex, or not valid DER if passed as bytes)
    # bytes.fromhex will fail if signature_hex is not hex.
    # Here signature_der is bytes, but ec.EllipticCurvePublicKey.from_encoded_point might fail on bad pubkey bytes.
    # The verify_signature method has a broad except Exception that should catch these and return False.

    # Example: public key hex that's too short or invalid format for from_encoded_point
    dummy_wallet = Wallet() # To get a valid curve
    invalid_pub_key_hex = "04112233" # Too short for a valid uncompressed point
    some_hash = hashlib.sha256(b"test").digest()
    some_sig = dummy_wallet.sign_data(some_hash)

    assert Wallet.verify_signature(invalid_pub_key_hex, some_hash, some_sig, curve=dummy_wallet.curve) is False

    # Invalid signature DER bytes (not hex)
    valid_pub_key_hex = dummy_wallet.get_public_key_hex()
    assert Wallet.verify_signature(valid_pub_key_hex, some_hash, b"not_der_signature_bytes", curve=dummy_wallet.curve) is False


def test_wallet_repr(alice_wallet):
    """Test the __repr__ method of Wallet with crypto."""
    wallet_repr = repr(alice_wallet)
    assert alice_wallet.address in wallet_repr
    assert alice_wallet.get_public_key_hex()[:20] in wallet_repr # Checks for the short pubkey

# To run these tests: `pytest` in the terminal from the project root.
