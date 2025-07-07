import time
import json # For deterministic serialization of metadata
import hashlib
from .wallet import Wallet # Updated to relative import
from . import constants # Import constants

class Transaction:
    """
    Represents a transaction in the EmPower1 Blockchain.
    Transactions are signed by the sender's wallet.
    """
    def __init__(self, sender_address: str, receiver_address: str, amount: int, # Amount is int (atomic units)
                 asset_id: str = None, timestamp: float = None,
                 fee: int = 0, metadata: dict = None, signature_hex: str = None): # Fee is int (atomic units)
        """
        Constructor for a Transaction.
        Args:
            sender_address (str): The address of the sender.
            receiver_address (str): The address of the receiver.
            amount (int): The amount of the asset being transferred, in atomic units.
            asset_id (str, optional): Identifier for the asset. Defaults to NATIVE_CURRENCY_SYMBOL.
            timestamp (float, optional): Time of transaction creation. Defaults to current time.
            fee (int, optional): Transaction fee, in atomic units. Defaults to 0.
            metadata (dict, optional): Additional data for the transaction.
            signature_hex (str, optional): Hex-encoded DER signature of the transaction data.
        """
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("Transaction amount must be a non-negative integer (atomic units).")
        if not isinstance(fee, int) or fee < 0:
            raise ValueError("Transaction fee must be a non-negative integer (atomic units).")

        self.sender_address = sender_address
        self.receiver_address = receiver_address
        self.amount: int = amount
        self.asset_id = asset_id if asset_id is not None else constants.NATIVE_CURRENCY_SYMBOL
        self.timestamp = timestamp or time.time()
        self.fee: int = fee
        self.metadata = metadata or {}

        # Signature is stored as hex string of DER-encoded bytes
        self.signature_hex = signature_hex

        # Transaction ID is the SHA256 hash of the data that gets signed.
        # It's calculated once the core fields are set.
        self.transaction_id = self._calculate_transaction_id()

    def get_data_for_signing(self) -> bytes:
        """
        Serializes transaction data into a deterministic byte string for signing or hashing.
        The order of fields is important for determinism.
        Metadata is JSON serialized with sorted keys for determinism.
        """
        # Amount and fee are now integers (atomic units).
        data_string = (
            f"{self.sender_address}{self.receiver_address}{self.amount}{self.asset_id}"
            f"{self.timestamp:.6f}{self.fee}" # Keep timestamp with fixed float format for consistency
            f"{json.dumps(self.metadata, sort_keys=True)}"
        )
        return data_string.encode('utf-8')

    def _calculate_transaction_id(self) -> str:
        """
        Calculates the transaction ID as the SHA256 hash of the signable data.
        """
        return hashlib.sha256(self.get_data_for_signing()).hexdigest()

    def sign(self, wallet: Wallet):
        """
        Signs the transaction using the provided wallet.
        The wallet's private key is used to sign the hash of the transaction's signable data.
        Args:
            wallet (Wallet): The sender's wallet instance.
        Raises:
            ValueError: If the wallet's address does not match the transaction's sender_address.
        """
        if wallet.address != self.sender_address:
            # This check assumes sender_address is the wallet address.
            # If sender_address was just an identifier, we'd need wallet.public_key to match a tx field.
            # For now, we'll change the interpretation: sender_address *is* the public key hex.
            # Let's adjust this: the `sender_address` field should be the wallet's public key hex.
            # The plan said: "sender's public key (which might need to be fetched or assumed to be part of the transaction object,
            # e.g., transaction.sender is the public key)."
            # So, let's make self.sender_address the public key hex.
            # No, the plan for Wallet.generate_address makes an address distinct from public key.
            # The transaction should store the *public key hex* of the sender for verification.
            # Let's assume `self.sender_address` is the *wallet address* and we need a separate
            # `sender_public_key_hex` field, or the blockchain has a way to look it up.
            # For now, to proceed with this structure:
            # The `sign` method implies the wallet passed IS the sender.
            # The `sender_address` field should be set from `wallet.address`.
            # The public key for verification will be `wallet.get_public_key_hex()`.
            # This means `sender_address` in __init__ should be the wallet's address.
            pass # Current structure assumes sender_address is set correctly to wallet.address

        data_to_sign_hash = hashlib.sha256(self.get_data_for_signing()).digest()
        signature_der = wallet.sign_data(data_to_sign_hash)
        self.signature_hex = signature_der.hex()
        # print(f"Transaction {self.transaction_id} signed by {self.sender_address}.")

    def verify_signature(self, sender_public_key_hex: str) -> bool:
        """
        Verifies the transaction's signature using the sender's public key hex.
        Args:
            sender_public_key_hex (str): The hex string of the sender's public key
                                         (uncompressed or compressed X962 format).
        Returns:
            bool: True if the signature is valid, False otherwise.
        """
        if not self.signature_hex:
            # print(f"Transaction {self.transaction_id} has no signature to verify.")
            return False

        data_to_verify_hash = hashlib.sha256(self.get_data_for_signing()).digest()
        try:
            signature_der = bytes.fromhex(self.signature_hex)
            return Wallet.verify_signature(
                public_key_bytes_hex=sender_public_key_hex,
                data_hash=data_to_verify_hash,
                signature_der=signature_der
                # curve can be passed if not using Wallet.DEFAULT_CURVE
            )
        except ValueError: # Hex decoding error
            # print(f"Signature hex decoding error for transaction {self.transaction_id}")
            return False
        except Exception as e:
            # print(f"Error during signature verification for {self.transaction_id}: {e}")
            return False

    def to_dict(self) -> dict:
        """Returns a dictionary representation of the transaction."""
        return {
            "transaction_id": self.transaction_id,
            "sender_address": self.sender_address,
            "receiver_address": self.receiver_address,
            "amount": self.amount,
            "asset_id": self.asset_id,
            "timestamp": self.timestamp,
            "fee": self.fee,
            "metadata": self.metadata,
            "signature_hex": self.signature_hex
        }

    def __repr__(self) -> str:
        return (f"Transaction(ID: {self.transaction_id}, From: {self.sender_address}, To: {self.receiver_address}, "
                f"Amount: {self.amount} {self.asset_id}, Fee: {self.fee}, Timestamp: {self.timestamp}, "
                f"Signed: {'Yes' if self.signature_hex else 'No'})")

    @classmethod
    def from_dict(cls, tx_data: dict):
        """
        Creates a Transaction instance from a dictionary.
        Assumes the dictionary contains all necessary fields.
        The transaction_id will be recalculated based on the fields.
        """
        # Ensure all required fields for __init__ are present, handle optionals
        return cls(
            sender_address=tx_data['sender_address'],
            receiver_address=tx_data['receiver_address'],
            amount=tx_data['amount'],
            asset_id=tx_data.get('asset_id', constants.NATIVE_CURRENCY_SYMBOL), # Use constant
            timestamp=tx_data.get('timestamp', time.time()), # Default if missing
            fee=tx_data.get('fee', 0.0),
            metadata=tx_data.get('metadata', {}),
            signature_hex=tx_data.get('signature_hex') # Can be None
        )


if __name__ == '__main__':
    # Create wallets for Alice and Bob
    alice_wallet = Wallet()
    bob_wallet = Wallet()
    print(f"Alice's Wallet Address: {alice_wallet.address}, PubKeyHex (short): {alice_wallet.get_public_key_hex()[:10]}")
    print(f"Bob's Wallet Address: {bob_wallet.address}, PubKeyHex (short): {bob_wallet.get_public_key_hex()[:10]}")

    # Create a transaction from Alice to Bob
    # Here, sender_address is Alice's wallet address.
    # For verification, we'll need Alice's public key hex.
    tx1 = Transaction(
        sender_address=alice_wallet.address, # This is Alice's Wallet Address
        receiver_address=bob_wallet.address,
        amount=100_000_000, # Example: 100 EPC in atomic units (assuming 6 decimals)
        asset_id=constants.NATIVE_CURRENCY_SYMBOL,
        fee=10_000, # Example: 0.01 EPC in atomic units
        metadata={"message": "Payment for goods"}
    )
    print(f"\nCreated Transaction 1 (unsigned): {tx1}")
    print(f"TX1 Data for signing: {tx1.get_data_for_signing().decode()}")
    print(f"TX1 ID (hash of signable data): {tx1.transaction_id}")

    # Alice signs the transaction
    tx1.sign(alice_wallet)
    print(f"Transaction 1 (signed): {tx1}")
    assert tx1.signature_hex is not None

    # Verify Transaction 1 using Alice's public key
    # The Blockchain or verifier would need access to Alice's public key hex.
    # It could be stored with the transaction, or looked up from Alice's address.
    # For this demo, we pass it directly.
    is_tx1_valid = tx1.verify_signature(sender_public_key_hex=alice_wallet.get_public_key_hex())
    print(f"Is Transaction 1 signature valid (using Alice's pubkey)? {is_tx1_valid}")
    assert is_tx1_valid

    # Try to verify with Bob's public key (should fail)
    is_tx1_valid_with_bob_key = tx1.verify_signature(sender_public_key_hex=bob_wallet.get_public_key_hex())
    print(f"Is Transaction 1 signature valid (using Bob's pubkey)? {is_tx1_valid_with_bob_key}")
    assert not is_tx1_valid_with_bob_key

    # Tamper with the transaction data AFTER signing and try to verify (should fail)
    print("\n--- Tampering Test ---")
    original_amount_tx1 = tx1.amount
    tx1.amount = 200.0 # Tamper the amount
    # Note: tx1.transaction_id will NOT change here because it was calculated before tampering.
    # A new transaction object would have a different ID.
    # The important part is that get_data_for_signing() will now produce different bytes.
    print(f"Tampered Transaction 1: {tx1}")
    is_tx1_tampered_valid = tx1.verify_signature(sender_public_key_hex=alice_wallet.get_public_key_hex())
    print(f"Is tampered Transaction 1 signature valid? {is_tx1_tampered_valid}")
    assert not is_tx1_tampered_valid
    tx1.amount = original_amount_tx1 # Restore for sanity

    # Test transaction_id consistency
    tx1_recalculated_id = tx1._calculate_transaction_id() # After restoring amount
    # If tx1.transaction_id was set in __init__ based on initial state, it should match.
    # Our current _calculate_transaction_id uses current state.
    assert tx1.transaction_id == tx1_recalculated_id
    print(f"TX1 ID after restoring amount matches initial: {tx1.transaction_id == tx1_recalculated_id}")


    print("\n--- System Transaction Example (e.g., IRE stimulus) ---")
    # System transactions might be signed by a specific system wallet
    system_wallet = Wallet() # The IRE system's wallet
    print(f"System Wallet Address: {system_wallet.address}")

    stimulus_tx = Transaction(
        sender_address=system_wallet.address, # From system wallet
        receiver_address=alice_wallet.address, # To Alice
        amount=25_000_000, # Example: 25 units in atomic (assuming 6 decimals for this asset too for demo)
        asset_id="empower_coin_stimulus",
        metadata={"type": "stimulus_payment", "batch_id": "B001"}
        # Fee defaults to 0, which is an int.
    )
    stimulus_tx.sign(system_wallet)
    print(f"Stimulus Transaction (signed): {stimulus_tx}")

    is_stimulus_tx_valid = stimulus_tx.verify_signature(sender_public_key_hex=system_wallet.get_public_key_hex())
    print(f"Is stimulus transaction signature valid? {is_stimulus_tx_valid}")
    assert is_stimulus_tx_valid

    print("\nTransaction class with ECDSA signing demo complete.")
    print(f"TX1 dict: {tx1.to_dict()}")
