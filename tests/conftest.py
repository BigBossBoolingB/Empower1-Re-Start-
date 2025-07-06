import pytest
import time
import random
from unittest.mock import patch # Added

from empower1.blockchain.wallet import Wallet
from empower1.blockchain.transaction import Transaction
from empower1.blockchain.block import Block
from empower1.blockchain.blockchain import Blockchain, USER_PUBLIC_KEYS, VALIDATOR_WALLETS

# This file (conftest.py) is used by pytest to share fixtures across multiple test files.

# --- Wallet Fixtures ---
@pytest.fixture(scope="function") # Recreate for each test to ensure isolation
def alice_wallet():
    w = Wallet()
    # For tests involving Blockchain, USER_PUBLIC_KEYS needs to be populated.
    # This can be done here or in specific test setups if a Blockchain instance is used.
    # For Wallet tests themselves, this isn't strictly needed.
    return w

@pytest.fixture(scope="function")
def bob_wallet():
    return Wallet()

@pytest.fixture(scope="function")
def charlie_wallet():
    return Wallet()

@pytest.fixture(scope="function")
def validator_wallet():
    """A generic validator wallet."""
    return Wallet()

# --- Transaction Fixtures ---
@pytest.fixture
def sample_transaction_signed(alice_wallet, bob_wallet):
    """Returns a signed Transaction instance from Alice to Bob."""
    tx = Transaction(
        sender_address=alice_wallet.address,
        receiver_address=bob_wallet.address,
        amount=10.0,
        asset_id="EMP_Test_Coin",
        fee=0.1,
        metadata={"purpose": "Test payment from Alice to Bob"}
    )
    tx.sign(alice_wallet)
    return tx

@pytest.fixture
def another_sample_transaction_signed(charlie_wallet, alice_wallet):
    """Returns another signed Transaction instance from Charlie to Alice."""
    tx = Transaction(
        sender_address=charlie_wallet.address,
        receiver_address=alice_wallet.address,
        amount=25.0,
        asset_id="EMP_Test_TokenB",
        fee=0.05,
        metadata={"project": "TestProjectX from Charlie to Alice"}
    )
    tx.sign(charlie_wallet)
    return tx

# --- Block Fixtures ---
@pytest.fixture
def genesis_block_from_blockchain(empty_blockchain_real_genesis):
    """Returns the actual genesis block from a new Blockchain instance."""
    return empty_blockchain_real_genesis.chain[0]

@pytest.fixture
def sample_block_signed(genesis_block_from_blockchain, sample_transaction_signed, another_sample_transaction_signed, validator_wallet):
    """
    Returns a signed sample Block.
    This block is created and signed by validator_wallet.
    The blockchain needs to know about this validator's public key.
    """
    # Ensure validator_wallet's public key is known for block verification later if needed
    # This is typically handled by blockchain's validator registration.
    # For creating a standalone block, we pass validator_address.
    # The signature will be added after creation.

    block = Block(
        index=genesis_block_from_blockchain.index + 1,
        transactions=[sample_transaction_signed, another_sample_transaction_signed],
        timestamp=time.time() + 10, # Ensure later than genesis
        previous_hash=genesis_block_from_blockchain.hash,
        validator_address=validator_wallet.address, # Validator's wallet address
        proof="sample_proof_from_conftest" # Added proof argument
    )
    block.sign_block(validator_wallet) # Validator signs the block
    return block


# --- Blockchain Fixtures ---
@pytest.fixture
def empty_blockchain_real_genesis():
    """
    Returns a new Blockchain instance. This instance will have its own
    cryptographically signed genesis block created by its internal genesis validator.
    The USER_PUBLIC_KEYS and VALIDATOR_WALLETS will be populated for this genesis validator.
    """
    # Clear global dicts for test isolation if they are modified by Blockchain instantiation
    # or tests. This is important if Blockchain constructor modifies these globals.
    # It appears Blockchain() constructor does populate these for its genesis validator.
    USER_PUBLIC_KEYS.clear()
    VALIDATOR_WALLETS.clear()
    # Blockchain() constructor now requires a node_wallet.
    fixture_genesis_wallet = Wallet()
    # The Blockchain constructor will handle populating USER_PUBLIC_KEYS/VALIDATOR_WALLETS for this wallet.
    return Blockchain(node_wallet=fixture_genesis_wallet)

@pytest.fixture
def blockchain_with_one_validator(empty_blockchain_real_genesis, validator_wallet):
    """
    Returns a Blockchain with the genesis block and one registered validator.
    """
    bc = empty_blockchain_real_genesis
    # Register the validator_wallet. This also populates USER_PUBLIC_KEYS and VALIDATOR_WALLETS
    # for this validator within the Blockchain instance's context (if it uses these globals).
    bc.register_validator_wallet(validator_wallet, stake_amount=1000)
    return bc


@pytest.fixture
def blockchain_with_transactions_pending(blockchain_with_one_validator, alice_wallet, bob_wallet, charlie_wallet, validator_wallet): # Added validator_wallet
    """
    Returns a Blockchain with a registered validator and some pending transactions.
    Requires alice_wallet, bob_wallet, charlie_wallet to have their public keys in USER_PUBLIC_KEYS
    for add_transaction to succeed.
    """
    bc = blockchain_with_one_validator # Already has a validator registered

    # Ensure user wallets' public keys are known to the blockchain context for add_transaction
    # The Blockchain class uses global USER_PUBLIC_KEYS, so we populate it.
    if alice_wallet.address not in USER_PUBLIC_KEYS:
        USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    if bob_wallet.address not in USER_PUBLIC_KEYS:
        USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()
    if charlie_wallet.address not in USER_PUBLIC_KEYS:
        USER_PUBLIC_KEYS[charlie_wallet.address] = charlie_wallet.get_public_key_hex()

    tx1 = Transaction(
        sender_address=alice_wallet.address, receiver_address=bob_wallet.address,
        amount=10.0, metadata={"fixture_tx": "tx1_pending"}
    )
    tx1.sign(alice_wallet)
    # bc.add_transaction(tx1, alice_wallet.get_public_key_hex()) # Original problematic line

    tx2 = Transaction(
        sender_address=bob_wallet.address, receiver_address=charlie_wallet.address,
        amount=5.0, metadata={"fixture_tx": "tx2_pending"}, asset_id="EMP_Test_TokenB"
    )
    tx2.sign(bob_wallet)
    # bc.add_transaction(tx2, bob_wallet.get_public_key_hex()) # Original problematic line

    # To ensure Alice and Bob have funds for their transactions to pass add_transaction pre-check:
    # 1. Fund Alice and Bob from genesis validator in a preliminary block.
    genesis_validator_addr = bc.chain[0].validator_address
    genesis_validator_wallet = VALIDATOR_WALLETS[genesis_validator_addr]

    fund_alice_tx = Transaction(genesis_validator_addr, alice_wallet.address, 100.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    fund_alice_tx.sign(genesis_validator_wallet)
    assert bc.add_transaction(fund_alice_tx, USER_PUBLIC_KEYS[genesis_validator_addr]), "Failed to add funding tx for Alice"

    fund_bob_tx = Transaction(genesis_validator_addr, bob_wallet.address, 100.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    fund_bob_tx.sign(genesis_validator_wallet)
    assert bc.add_transaction(fund_bob_tx, USER_PUBLIC_KEYS[genesis_validator_addr]), "Failed to add funding tx for Bob"

    # Mine this funding block
    # The validator for this block is already registered in blockchain_with_one_validator fixture
    funding_validator_obj = bc.validator_manager.get_validator(validator_wallet.address) # validator_wallet from outer scope
    assert funding_validator_obj is not None
    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        mined_funding_block = bc.mine_pending_transactions()
    assert mined_funding_block is not None, "Funding block failed to mine"
    assert len(bc.chain) == 2 # Genesis + funding block
    assert bc.balances.get(alice_wallet.address) == 100.0
    assert bc.balances.get(bob_wallet.address) == 100.0

    # Now add the original transactions from Alice and Bob, they should pass balance checks
    assert bc.add_transaction(tx1, alice_wallet.get_public_key_hex()), "Failed to add tx1 from Alice"
    assert bc.add_transaction(tx2, bob_wallet.get_public_key_hex()), "Failed to add tx2 from Bob"

    return bc


# --- Fixtures for IRE components (can remain as they are if not directly using crypto yet) ---
@pytest.fixture
def mock_ire_ai_model():
    from empower1.ire.ai_model import IREDecisionModel
    return IREDecisionModel()

@pytest.fixture
def redistribution_engine(mock_ire_ai_model):
    from empower1.ire.redistribution import RedistributionEngine
    return RedistributionEngine(ai_decision_model=mock_ire_ai_model, blockchain_interface=None)

# --- Fixtures for Smart Contract components (can remain as they are) ---
@pytest.fixture
def contract_owner_address():
    # For smart contracts, the owner might be a wallet address
    return Wallet().address # Generate a new wallet address for contract owner

@pytest.fixture
def base_contract_address():
    return "SC_Base_TestAddr_Conftest_001" # Example static address

@pytest.fixture
def mock_blockchain_interface():
    class MockBlockchainInterface:
        def __init__(self):
            self.events_logged = []
            self.balances = {}
        def get_current_timestamp(self): return time.time()
        def log_event(self, contract_address, event_name, event_data):
            self.events_logged.append({"contract_address": contract_address, "event_name": event_name, "event_data": event_data})
        def get_balance(self, address, asset_id): return self.balances.get((address, asset_id), 0.0)
        def set_balance(self, address, asset_id, amount): self.balances[(address, asset_id)] = amount
        def create_transfer_transaction(self, from_address, to_address, amount, asset_id):
            # Simplified mock transfer logic
            if self.get_balance(from_address, asset_id) >= amount:
                self.set_balance(from_address, asset_id, self.get_balance(from_address, asset_id) - amount)
                self.set_balance(to_address, asset_id, self.get_balance(to_address, asset_id) + amount)
                return True
            return False
    return MockBlockchainInterface()

@pytest.fixture
def base_smart_contract(base_contract_address, contract_owner_address, mock_blockchain_interface):
    from empower1.smart_contracts.base_contract import BaseContract
    return BaseContract(contract_address=base_contract_address, owner_address=contract_owner_address, blockchain_interface=mock_blockchain_interface)

@pytest.fixture
def stimulus_contract_address():
    return "SC_Stimulus_TestAddr_Conftest_001"

@pytest.fixture
def stimulus_contract(stimulus_contract_address, contract_owner_address, mock_blockchain_interface):
    from empower1.smart_contracts.stimulus_contract import StimulusContract
    mock_blockchain_interface.set_balance(stimulus_contract_address, "empower_coin_stimulus", 0)
    return StimulusContract(contract_address=stimulus_contract_address, owner_address=contract_owner_address, blockchain_interface=mock_blockchain_interface)

@pytest.fixture
def tax_contract_address():
    return "SC_Tax_TestAddr_Conftest_001"

@pytest.fixture
def tax_contract(tax_contract_address, contract_owner_address, mock_blockchain_interface):
    from empower1.smart_contracts.tax_contract import TaxContract
    return TaxContract(contract_address=tax_contract_address, owner_address=contract_owner_address, blockchain_interface=mock_blockchain_interface)


print("conftest.py loaded: Shared pytest fixtures (crypto-updated) are available.")
