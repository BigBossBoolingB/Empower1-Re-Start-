import time
import json # For deterministic serialization of transactions list
import hashlib
from .transaction import Transaction # Updated to relative import
from .wallet import Wallet # Updated to relative import

class Block:
    """
    Represents a block in the EmPower1 Blockchain.
    A block contains a list of transactions and is signed by its validator.
    """
    def __init__(self, index: int, transactions: list[Transaction], timestamp: float,
                 previous_hash: str, validator_address: str, proof: any, signature_hex: str = None):
        """
        Constructor for a Block.
        Args:
            index (int): The block's index in the chain.
            transactions (list[Transaction]): A list of Transaction objects included in the block.
            timestamp (float): The time the block was created.
            previous_hash (str): The hash of the preceding block.
            validator_address (str): The address of the validator who created/validated this block.
            proof (any): The proof associated with the consensus mechanism (e.g., PoS proof).
                         This field is included in the block's hash.
            signature_hex (str, optional): Hex-encoded DER signature of the block's hash by the validator.
        """
        self.index = index
        self.timestamp = timestamp # Ensure this is set before transactions for consistent __dict__ order if not sorted
        self.transactions = transactions # List of Transaction objects
        self.proof = proof
        self.previous_hash = previous_hash
        self.validator_address = validator_address

        # Signature is for the block's hash, set after hash calculation and signing
        self.signature_hex = signature_hex

        # Calculate block hash. It depends on all above fields (excluding signature_hex and hash itself).
        self.hash = self.calculate_hash()


    def calculate_hash(self) -> str:
        """
        Calculates the SHA256 hash of the block's content using json.dumps on a dictionary
        of its attributes (index, timestamp, transactions, proof, previous_hash, validator_address),
        ensuring deterministic hashing.
        The block's own `hash` and `signature_hex` attributes are NOT included in this calculation.
        Transactions are serialized to their dictionary representation.
        """
        # Create a dictionary of attributes to be included in the hash
        block_dict_for_hashing = {
            "index": self.index,
            "timestamp": self.timestamp,
            # Serialize transactions to ensure deterministic representation
            "transactions": [tx.to_dict() for tx in self.transactions],
            "proof": self.proof,
            "previous_hash": self.previous_hash,
            "validator_address": self.validator_address
            # self.hash and self.signature_hex are NOT included here
        }

        # Use json.dumps with sort_keys=True for a deterministic string representation
        block_string = json.dumps(block_dict_for_hashing, sort_keys=True).encode('utf-8')
        return hashlib.sha256(block_string).hexdigest()

    # For block signing by validator:
    # The data to be signed by the validator is typically the block's own hash.
    def get_data_for_block_signing(self) -> bytes:
        """
        Returns the data that the validator should sign. This is the block's own hash.
        """
        if not self.hash: # Should not happen if constructor is called correctly
            raise ValueError("Block hash not calculated yet. Cannot get data for signing.")
        return self.hash.encode('utf-8') # Sign the hex representation of the hash as bytes

    def sign_block(self, validator_wallet: Wallet):
        """
        Signs the block's hash using the validator's wallet.
        Args:
            validator_wallet (Wallet): The wallet of the validator.
        Raises:
            ValueError: If validator's address doesn't match block's validator_address
                        or if block hash is not available.
        """
        # This check depends on whether validator_address is the wallet address or public key hex.
        # Let's assume validator_address stored in block is the wallet address.
        if validator_wallet.address != self.validator_address:
             raise ValueError("Validator wallet does not match block's validator_address.")
        if not self.hash:
            raise ValueError("Block hash must be calculated before signing.")

        data_to_sign_hash = hashlib.sha256(self.get_data_for_block_signing()).digest() # Hash the block's hash string
        signature_der = validator_wallet.sign_data(data_to_sign_hash)
        self.signature_hex = signature_der.hex()

    def verify_block_signature(self, validator_public_key_hex: str) -> bool:
        """
        Verifies the block's signature using the validator's public key.
        Args:
            validator_public_key_hex (str): The hex string of the validator's public key.
        Returns:
            bool: True if the signature is valid, False otherwise.
        """
        if not self.signature_hex or not self.hash:
            return False

        data_to_verify_hash = hashlib.sha256(self.get_data_for_block_signing()).digest() # Hash of the block's hash string
        try:
            signature_der = bytes.fromhex(self.signature_hex)
            return Wallet.verify_signature(
                public_key_bytes_hex=validator_public_key_hex,
                data_hash=data_to_verify_hash,
                signature_der=signature_der
            )
        except ValueError: # Hex decoding error
            return False
        except Exception:
            return False

    def __repr__(self):
        return (f"Block(Index: {self.index}, Transactions: {len(self.transactions)}, Proof: {self.proof}, "
                f"Timestamp: {self.timestamp}, Hash: {self.hash[:10]}..., Prev_Hash: {self.previous_hash[:10] if self.previous_hash else 'None'}..., "
                f"Validator: {self.validator_address}, Signed: {'Yes' if self.signature_hex else 'No'})")

    def to_dict(self) -> dict:
        """
        Returns a dictionary representation of the block, including the proof field.
        """
        return {
            "index": self.index,
            "transactions": [tx.to_dict() for tx in self.transactions], # Convert transactions to dicts
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "validator_address": self.validator_address,
            "proof": self.proof, # Added proof
            "signature_hex": self.signature_hex,
            "hash": self.hash
        }

    @classmethod
    def from_dict(cls, block_data: dict):
        """
        Creates a Block instance from a dictionary.
        Assumes transaction data within block_data['transactions'] are also dicts
        that can be converted by Transaction.from_dict().
        The 'proof' field is expected in block_data.
        The block's hash will be recalculated based on its content by __init__.
        """
        # Deserialize transactions first
        transactions_from_data = []
        if 'transactions' in block_data and isinstance(block_data['transactions'], list):
            for tx_data in block_data['transactions']:
                try:
                    transactions_from_data.append(Transaction.from_dict(tx_data))
                except Exception as e:
                    # Handle error in transaction deserialization, e.g., log or raise
                    print(f"Error deserializing transaction in block: {e}, data: {tx_data}")
                    # Decide if this is fatal for block creation or if block can be created with partial/no txs
                    raise ValueError(f"Invalid transaction data in block: {e}") from e

        return cls(
            index=block_data['index'],
            transactions=transactions_from_data,
            timestamp=block_data['timestamp'],
            previous_hash=block_data['previous_hash'],
            validator_address=block_data['validator_address'],
            proof=block_data.get('proof'), # Added proof, use .get for backward compatibility if proof is optional
            signature_hex=block_data.get('signature_hex') # Signature can be None if block is not yet signed
        )

if __name__ == '__main__':
    # Create Wallets for Alice (user) and ValidatorX
    alice_wallet = Wallet()
    validator_x_wallet = Wallet()
    print(f"Alice's Wallet Address: {alice_wallet.address}")
    print(f"ValidatorX Wallet Address: {validator_x_wallet.address}, PubKeyHex: {validator_x_wallet.get_public_key_hex()[:10]}...")

    # Create some transactions (signed by Alice)
    tx1 = Transaction(
        sender_address=alice_wallet.address,
        receiver_address="Bob_Wallet_Addr",
        amount=10.0,
        metadata={"msg": "tx1 for block"}
    )
    tx1.sign(alice_wallet)

    tx2 = Transaction(
        sender_address=alice_wallet.address,
        receiver_address="Charlie_Wallet_Addr",
        amount=5.0,
        metadata={"msg": "tx2 for block"}
    )
    tx2.sign(alice_wallet)
    print(f"\nTransaction 1 ID: {tx1.transaction_id}")
    print(f"Transaction 2 ID: {tx2.transaction_id}")

    # Create a genesis block (usually simpler, without transactions and special validator)
    genesis_block_validator_wallet = Wallet() # A conceptual genesis validator
    genesis_block = Block(
        index=0,
        transactions=[],
        timestamp=time.time(),
        previous_hash="0", # Genesis block has no previous hash
        validator_address=genesis_block_validator_wallet.address, # Genesis validator address
        proof="genesis_proof_main"
    )
    # Genesis block might be pre-signed or have a known signature/no signature
    # For this demo, let's sign it.
    genesis_block.sign_block(genesis_block_validator_wallet)
    print(f"\nGenesis Block: {genesis_block}")
    is_genesis_sig_valid = genesis_block.verify_block_signature(genesis_block_validator_wallet.get_public_key_hex())
    print(f"Is Genesis Block signature valid? {is_genesis_sig_valid}")


    # Create a second block, validated by ValidatorX
    block2_timestamp = time.time() + 60
    block2 = Block(
        index=1,
        transactions=[tx1, tx2], # List of signed Transaction objects
        timestamp=block2_timestamp,
        previous_hash=genesis_block.hash,
        validator_address=validator_x_wallet.address, # ValidatorX's address
        proof="block2_proof_main"
    )
    print(f"\nBlock 2 (unsigned): {block2}")
    print(f"Block 2 Hash: {block2.hash}")
    print(f"Block 2 Data for signing (block's hash): {block2.get_data_for_block_signing().decode()}")


    # ValidatorX signs Block 2
    block2.sign_block(validator_x_wallet)
    print(f"Block 2 (signed): {block2}")
    assert block2.signature_hex is not None

    # Verify Block 2's signature
    is_block2_sig_valid = block2.verify_block_signature(
        validator_public_key_hex=validator_x_wallet.get_public_key_hex()
    )
    print(f"Is Block 2 signature valid (using ValidatorX's pubkey)? {is_block2_sig_valid}")
    assert is_block2_sig_valid

    # Tamper with block2's transaction (after block hash calculation and signing)
    # This should NOT invalidate block2.signature_hex against block2.hash,
    # but it WOULD make block2.hash different if recalculated.
    # The Blockchain's is_chain_valid will catch this by re-calculating block hash.
    if block2.transactions:
        block2.transactions[0].amount = 999.0 # Tamper

    # After tampering, a new call to calculate_hash() on the *current state* of block2 will yield a different hash
    recalculated_hash_after_tamper = block2.calculate_hash()
    print(f"\nBlock 2 original hash: {block2.hash}") # This is the hash stored from __init__
    print(f"Block 2 recalculated hash after tampering tx: {recalculated_hash_after_tamper}")
    assert block2.hash != recalculated_hash_after_tamper

    # The signature is for the ORIGINAL block hash, so it should still be valid against that original hash.
    is_block2_sig_still_valid_for_original_hash = block2.verify_block_signature(
         validator_x_wallet.get_public_key_hex()
    )
    print(f"Is Block 2 signature still valid for its STORED hash (even after tx tamper)? {is_block2_sig_still_valid_for_original_hash}")
    assert is_block2_sig_still_valid_for_original_hash

    print("\nBlock class with ECDSA signing demo complete.")
