import hashlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

class Wallet:
    """
    Represents a user's wallet in the EmPower1 Blockchain.
    Manages ECDSA private/public key pairs and signing data.
    Uses secp256k1 curve by default.
    """
    DEFAULT_CURVE = ec.SECP256K1() # Commonly used in blockchains like Bitcoin and Ethereum

    def __init__(self, private_key_pem_hex=None, curve=DEFAULT_CURVE):
        """
        Initializes a Wallet. If private_key_pem_hex is provided (hex of PEM bytes),
        it loads the wallet; otherwise, it generates a new private/public key pair.

        Args:
            private_key_pem_hex (str, optional): Hex-encoded PEM representation of the private key.
            curve (ec.EllipticCurve, optional): The elliptic curve to use. Defaults to SECP256K1.
        """
        self.curve = curve
        if private_key_pem_hex:
            try:
                private_key_pem_bytes = bytes.fromhex(private_key_pem_hex)
                self.private_key = serialization.load_pem_private_key(
                    private_key_pem_bytes,
                    password=None # Assuming no encryption for PEM private key for now
                )
            except Exception as e:
                raise ValueError(f"Failed to load private key from PEM hex: {e}")
        else:
            # Generate a new key pair
            self.private_key = ec.generate_private_key(self.curve)

        # Public key is derived from the private key
        self.public_key = self.private_key.public_key()

        # The address is derived from the public key
        self.address = self.generate_address(self.public_key)

    @staticmethod
    def generate_address(public_key_object: ec.EllipticCurvePublicKey):
        """
        Generates a wallet address from an ECDSA public key object.
        Uses uncompressed public key bytes, hashes it, and prefixes.
        A common pattern: Hash(public_key_bytes) -> take part of it -> add prefix/checksum/encoding.
        Example: SHA256(public_key_bytes (uncompressed)) then take a slice and prefix.
        """
        public_key_bytes_uncompressed = public_key_object.public_bytes(
            encoding=serialization.Encoding.X962, # Uncompressed point format
            format=serialization.PublicFormat.UncompressedPoint # Corrected to PascalCase
        )
        # First hash: SHA256
        h1 = hashlib.sha256(public_key_bytes_uncompressed).digest()
        # Second hash (optional, like Bitcoin's HASH160 = RIPEMD160(SHA256(pubkey))):
        # For simplicity here, we'll just use SHA256 again on the first hash, or just use h1.
        # Let's use RIPEMD160 if available, else another SHA256 for a "hash of a hash" feel.
        try:
            h_ripemd160 = hashlib.new('ripemd160')
            h_ripemd160.update(h1)
            address_hash_bytes = h_ripemd160.digest()
        except ValueError: # ripemd160 might not be available on all systems by default with hashlib
            # Fallback to SHA256(SHA256(pubkey)) if ripemd160 is not found
            address_hash_bytes = hashlib.sha256(h1).digest()

        # Using the first 20 bytes of the hash (similar to Ethereum addresses from Keccak256)
        # We'll use the first 20 bytes of our chosen hash.
        address_hex_part = address_hash_bytes[:20].hex()
        return f"Emp1{address_hex_part}" # Example: Emp1<40 hex chars>

    def get_private_key_pem_hex(self):
        """Returns the private key as a hex-encoded PEM string."""
        pem_bytes = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8, # Standard format
            encryption_algorithm=serialization.NoEncryption() # No password for PEM
        )
        return pem_bytes.hex()

    def get_public_key_hex(self, compressed=False):
        """
        Returns the public key as a hexadecimal string (X962 format).
        Args:
            compressed (bool): If True, returns compressed public key, else uncompressed.
        """
        fmt = serialization.PublicFormat.CompressedPoint if compressed else serialization.PublicFormat.UncompressedPoint # Corrected to PascalCase
        pub_key_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=fmt
        )
        return pub_key_bytes.hex()

    def sign_data(self, data: bytes):
        """
        Signs arbitrary byte data using the wallet's private key.
        The data should typically be a hash of the actual message/transaction content.
        Args:
            data (bytes): The data to sign (e.g., SHA256 hash of a message).
        Returns:
            bytes: The signature in DER format.
        """
        if not isinstance(data, bytes):
            raise TypeError("Data to sign must be bytes.")

        signature = self.private_key.sign(
            data,
            ec.ECDSA(hashes.SHA256()) # The signature algorithm itself often specifies the hash.
                                     # It's common to hash the message first, then sign that hash.
                                     # Here, 'data' is assumed to be the hash to be signed.
        )
        return signature # DER encoded signature

    @staticmethod
    def verify_signature(public_key_bytes_hex: str, data_hash: bytes, signature_der: bytes, curve=DEFAULT_CURVE):
        """
        Verifies a signature against a public key and the original data's hash.
        Args:
            public_key_bytes_hex (str): Hex string of the public key (X962 format, uncompressed or compressed).
            data_hash (bytes): The hash of the original data that was signed.
            signature_der (bytes): The signature (DER format bytes) to verify.
            curve (ec.EllipticCurve, optional): The curve used for this key.
        Returns:
            bool: True if the signature is valid, False otherwise.
        """
        if not isinstance(public_key_bytes_hex, str) or not isinstance(data_hash, bytes) or not isinstance(signature_der, bytes):
            # print("Debug: Type error in verify_signature inputs")
            return False
        try:
            public_key_bytes = bytes.fromhex(public_key_bytes_hex)
            public_key = ec.EllipticCurvePublicKey.from_encoded_point(curve, public_key_bytes)

            public_key.verify(
                signature_der,
                data_hash, # The data here is the HASH that was signed
                ec.ECDSA(hashes.SHA256())
            )
            return True
        except InvalidSignature:
            return False
        except Exception: # Other errors like malformed key, etc.
            # import traceback
            # print(f"Debug: Exception in verify_signature: {traceback.format_exc()}")
            return False

    def __repr__(self):
        return (f"Wallet(Address: {self.address}, "
                f"Public Key (short hex, uncompressed): {self.get_public_key_hex()[:20]}...)")

if __name__ == '__main__':
    # Create a new wallet
    wallet1 = Wallet()
    print(f"New Wallet 1: {wallet1}")
    print(f"  Address: {wallet1.address}")
    print(f"  Public Key (uncompressed hex): {wallet1.get_public_key_hex()}")
    print(f"  Public Key (compressed hex):   {wallet1.get_public_key_hex(compressed=True)}")
    priv_pem_hex = wallet1.get_private_key_pem_hex()
    print(f"  Private Key (PEM hex, first 64 chars): {priv_pem_hex[:64]}...")

    print("-" * 30)

    # Create another new wallet
    wallet2 = Wallet()
    print(f"New Wallet 2 Address: {wallet2.address}")

    print("-" * 30)

    # Load wallet1 from its private key PEM hex
    loaded_wallet1 = Wallet(private_key_pem_hex=priv_pem_hex)
    print(f"Loaded Wallet 1 Address: {loaded_wallet1.address}")
    assert wallet1.address == loaded_wallet1.address
    assert wallet1.get_public_key_hex() == loaded_wallet1.get_public_key_hex()
    assert wallet1.get_public_key_hex(compressed=True) == loaded_wallet1.get_public_key_hex(compressed=True)
    print("Wallet loading test passed.")

    print("-" * 30)

    # Signing and Verifying
    message_str = "EmPower1: Test message for signing!"
    message_bytes = message_str.encode('utf-8')

    # 1. Hash the message (this is what gets signed)
    message_hash = hashlib.sha256(message_bytes).digest()
    print(f"Message to sign: '{message_str}'")
    print(f"Hash of message (hex): {message_hash.hex()}")

    # 2. Wallet 1 signs the hash
    signature_bytes_der = wallet1.sign_data(message_hash)
    print(f"Signature from Wallet 1 (DER hex, first 64 chars): {signature_bytes_der.hex()[:64]}...")

    # 3. Verification
    # Get public key of Wallet 1 (signer) for verification
    wallet1_public_key_hex_uncompressed = wallet1.get_public_key_hex() # Uncompressed
    wallet1_public_key_hex_compressed = wallet1.get_public_key_hex(compressed=True)

    # Verify with Wallet 1's uncompressed public key (should be True)
    is_valid_w1_uncompressed = Wallet.verify_signature(
        public_key_bytes_hex=wallet1_public_key_hex_uncompressed,
        data_hash=message_hash,
        signature_der=signature_bytes_der
    )
    print(f"Is signature valid (using Wallet 1's UNCOMPRESSED public key)? {is_valid_w1_uncompressed}")
    assert is_valid_w1_uncompressed

    # Verify with Wallet 1's compressed public key (should also be True)
    is_valid_w1_compressed = Wallet.verify_signature(
        public_key_bytes_hex=wallet1_public_key_hex_compressed,
        data_hash=message_hash,
        signature_der=signature_bytes_der
    )
    print(f"Is signature valid (using Wallet 1's COMPRESSED public key)? {is_valid_w1_compressed}")
    assert is_valid_w1_compressed


    # Verify with Wallet 2's public key (should be False)
    wallet2_public_key_hex = wallet2.get_public_key_hex()
    is_valid_w2 = Wallet.verify_signature(
        public_key_bytes_hex=wallet2_public_key_hex,
        data_hash=message_hash,
        signature_der=signature_bytes_der
    )
    print(f"Is signature valid (using Wallet 2's public key)? {is_valid_w2}")
    assert not is_valid_w2

    # Tamper with the message hash (should be False)
    tampered_message_hash = hashlib.sha256(b"Tampered message!").digest()
    is_valid_tampered_hash = Wallet.verify_signature(
        public_key_bytes_hex=wallet1_public_key_hex_uncompressed,
        data_hash=tampered_message_hash,
        signature_der=signature_bytes_der
    )
    print(f"Is signature valid (tampered message hash)? {is_valid_tampered_hash}")
    assert not is_valid_tampered_hash

    # Tamper with the signature (should be False)
    tampered_signature = signature_bytes_der[:-1] + b'X' # Change last byte
    is_valid_tampered_sig = Wallet.verify_signature(
        public_key_bytes_hex=wallet1_public_key_hex_uncompressed,
        data_hash=message_hash,
        signature_der=tampered_signature
    )
    print(f"Is signature valid (tampered signature)? {is_valid_tampered_sig}")
    assert not is_valid_tampered_sig


    print("\nCryptographic Wallet operations demo complete.")
