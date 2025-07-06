import pytest
import time
from unittest.mock import patch
from empower1.blockchain.blockchain import Blockchain, USER_PUBLIC_KEYS, VALIDATOR_WALLETS
from empower1.blockchain.block import Block
from empower1.blockchain.transaction import Transaction
from empower1.consensus.manager import ValidatorManager # This should be correct
from empower1.blockchain.wallet import Wallet

# Test Blockchain initialization with crypto-signed Genesis
def test_blockchain_initialization_crypto(empty_blockchain_real_genesis):
    bc = empty_blockchain_real_genesis
    assert len(bc.chain) == 1
    genesis_block = bc.chain[0]
    assert genesis_block.index == 0
    assert genesis_block.previous_hash == "0"
    assert genesis_block.validator_address is not None
    assert genesis_block.signature_hex is not None
    assert genesis_block.proof is not None # Check that proof exists
    assert genesis_block.proof == {"type": "Genesis", "validator": genesis_block.validator_address, "details": "initial_block_proof_v1"} # Check specific genesis proof

    genesis_validator_pub_key = USER_PUBLIC_KEYS.get(genesis_block.validator_address)
    assert genesis_validator_pub_key is not None
    assert genesis_block.verify_block_signature(genesis_validator_pub_key) is True

    assert len(bc.pending_transactions) == 0
    assert isinstance(bc.validator_manager, ValidatorManager)
    assert len(bc.validator_manager.validators) == 0

    assert bc.total_supply_epc == 1_000_000.0
    assert bc.balances.get(genesis_block.validator_address) == 1_000_000.0
    assert sum(bc.balances.values()) == bc.total_supply_epc


def test_last_block_property_crypto(blockchain_with_one_validator, alice_wallet, bob_wallet, validator_wallet):
    bc = blockchain_with_one_validator
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    genesis_validator_addr = bc.chain[0].validator_address
    # Ensure genesis validator has funds to send (it does by default)
    assert bc.balances.get(genesis_validator_addr, 0.0) > 0
    genesis_val_wallet = VALIDATOR_WALLETS[genesis_validator_addr]

    tx = Transaction(genesis_validator_addr, bob_wallet.address, 1.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx.sign(genesis_val_wallet)
    assert bc.add_transaction(tx, USER_PUBLIC_KEYS[genesis_validator_addr])

    validator_obj = bc.validator_manager.get_validator(validator_wallet.address)
    assert validator_obj is not None

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=validator_obj):
        mined_block = bc.mine_pending_transactions()
        assert mined_block is not None
        assert bc.last_block == mined_block
        assert bc.last_block.index == 1

# --- Tests for _process_transaction_for_state_changes ---
def test_process_transaction_valid_epc_transfer(empty_blockchain_real_genesis, alice_wallet, bob_wallet):
    bc = empty_blockchain_real_genesis
    bc.balances[alice_wallet.address] = 100.0
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()

    tx = Transaction(alice_wallet.address, bob_wallet.address, 50.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx.sign(alice_wallet)

    assert bc._process_transaction_for_state_changes(tx) is True
    assert bc.balances.get(alice_wallet.address) == 50.0
    assert bc.balances.get(bob_wallet.address) == 50.0

def test_process_transaction_insufficient_funds(empty_blockchain_real_genesis, alice_wallet, bob_wallet):
    bc = empty_blockchain_real_genesis
    bc.balances[alice_wallet.address] = 10.0
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()

    tx = Transaction(alice_wallet.address, bob_wallet.address, 50.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx.sign(alice_wallet)

    assert bc._process_transaction_for_state_changes(tx) is False
    assert bc.balances.get(alice_wallet.address) == 10.0
    assert bc.balances.get(bob_wallet.address, 0.0) == 0.0

def test_process_transaction_non_epc_asset(empty_blockchain_real_genesis, alice_wallet, bob_wallet):
    bc = empty_blockchain_real_genesis
    bc.balances[alice_wallet.address] = 100.0
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()

    tx = Transaction(alice_wallet.address, bob_wallet.address, 10.0, asset_id="OTHER_COIN")
    tx.sign(alice_wallet)

    assert bc._process_transaction_for_state_changes(tx) is True
    assert bc.balances.get(alice_wallet.address) == 100.0
    assert bc.balances.get(bob_wallet.address, 0.0) == 0.0


# --- Test add_transaction with balance pre-check ---
def test_add_transaction_insufficient_funds_precheck(empty_blockchain_real_genesis, alice_wallet, bob_wallet, capsys):
    bc = empty_blockchain_real_genesis
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    # Alice has 0 confirmed balance in this fresh bc.
    tx = Transaction(alice_wallet.address, bob_wallet.address, 50.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx.sign(alice_wallet)

    assert bc.add_transaction(tx, alice_wallet.get_public_key_hex()) is False
    captured = capsys.readouterr()
    assert "insufficient available balance" in captured.out
    assert tx not in bc.pending_transactions

# --- Test mine_pending_transactions with balance processing ---
def test_mine_pending_transactions_processes_valid_epc_txs(blockchain_with_one_validator, validator_wallet, alice_wallet, bob_wallet):
    bc = blockchain_with_one_validator

    genesis_validator_addr = bc.chain[0].validator_address
    genesis_validator_wallet = VALIDATOR_WALLETS[genesis_validator_addr]

    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    # Fund Alice from Genesis Validator and mine that block first
    fund_alice_tx = Transaction(genesis_validator_addr, alice_wallet.address, 200.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    fund_alice_tx.sign(genesis_validator_wallet)
    assert bc.add_transaction(fund_alice_tx, USER_PUBLIC_KEYS[genesis_validator_addr])

    funding_validator_obj = bc.validator_manager.get_validator(validator_wallet.address) # The one registered by fixture
    assert funding_validator_obj is not None
    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        mined_funding_block = bc.mine_pending_transactions()
    assert mined_funding_block is not None
    assert bc.balances.get(alice_wallet.address) == 200.0 # Alice has confirmed balance

    # Now Alice sends to Bob
    tx_alice_to_bob = Transaction(alice_wallet.address, bob_wallet.address, 50.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx_alice_to_bob.sign(alice_wallet)
    assert bc.add_transaction(tx_alice_to_bob, alice_wallet.get_public_key_hex()) # This should now pass pre-check

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        mined_block_2 = bc.mine_pending_transactions()

    assert mined_block_2 is not None
    assert len(mined_block_2.transactions) == 1
    assert mined_block_2.transactions[0].transaction_id == tx_alice_to_bob.transaction_id

    assert bc.balances.get(genesis_validator_addr) == bc.total_supply_epc - 200.0
    assert bc.balances.get(alice_wallet.address) == 200.0 - 50.0
    assert bc.balances.get(bob_wallet.address) == 50.0
    assert not bc.pending_transactions

def test_mine_pending_transactions_skips_invalid_epc_tx_insufficient_funds(blockchain_with_one_validator, validator_wallet, alice_wallet, bob_wallet):
    bc = blockchain_with_one_validator
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    # Fund Alice with 30 EPC and mine it
    genesis_validator_addr = bc.chain[0].validator_address
    genesis_validator_wallet = VALIDATOR_WALLETS[genesis_validator_addr]
    tx_funding_alice = Transaction(genesis_validator_addr, alice_wallet.address, 30.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx_funding_alice.sign(genesis_validator_wallet)
    assert bc.add_transaction(tx_funding_alice, USER_PUBLIC_KEYS[genesis_validator_addr])

    funding_validator_obj = bc.validator_manager.get_validator(validator_wallet.address)
    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        assert bc.mine_pending_transactions() is not None # Mine funding block
    assert bc.balances.get(alice_wallet.address) == 30.0

    # Tx1: Alice tries to send 50 EPC (will fail pre-check as she only has 30 confirmed)
    tx1_fail = Transaction(alice_wallet.address, bob_wallet.address, 50.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx1_fail.sign(alice_wallet)
    assert bc.add_transaction(tx1_fail, alice_wallet.get_public_key_hex()) is False

    # Tx2: Alice sends valid 20 EPC
    tx2_valid = Transaction(alice_wallet.address, bob_wallet.address, 20.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx2_valid.sign(alice_wallet)
    assert bc.add_transaction(tx2_valid, alice_wallet.get_public_key_hex()) # Should pass pre-check

    assert len(bc.pending_transactions) == 1 # Only tx2_valid

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        mined_block = bc.mine_pending_transactions()

    assert mined_block is not None
    assert len(mined_block.transactions) == 1
    assert mined_block.transactions[0].transaction_id == tx2_valid.transaction_id

    assert bc.balances.get(alice_wallet.address) == 30.0 - 20.0 # 10 EPC
    assert bc.balances.get(bob_wallet.address) == 20.0
    assert not bc.pending_transactions

def test_is_chain_valid_crypto_focus(alice_wallet, bob_wallet):
    # Create a wallet to be used by this specific blockchain instance for its genesis
    bc_node_wallet = Wallet()
    bc_for_validation_test = Blockchain(node_wallet=bc_node_wallet)
    val_for_test = Wallet()
    bc_for_validation_test.register_validator_wallet(val_for_test, 1000.0)
    USER_PUBLIC_KEYS[val_for_test.address] = val_for_test.get_public_key_hex()
    VALIDATOR_WALLETS[val_for_test.address] = val_for_test

    gen_val_addr = bc_for_validation_test.chain[0].validator_address
    gen_val_wallet = VALIDATOR_WALLETS[gen_val_addr]

    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    tx_fund_alice = Transaction(gen_val_addr, alice_wallet.address, 100.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx_fund_alice.sign(gen_val_wallet)
    assert bc_for_validation_test.add_transaction(tx_fund_alice, USER_PUBLIC_KEYS[gen_val_addr])

    tx_fund_bob = Transaction(gen_val_addr, bob_wallet.address, 100.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx_fund_bob.sign(gen_val_wallet)
    assert bc_for_validation_test.add_transaction(tx_fund_bob, USER_PUBLIC_KEYS[gen_val_addr])

    validator_obj = bc_for_validation_test.validator_manager.get_validator(val_for_test.address)
    with patch.object(bc_for_validation_test.validator_manager, 'select_next_validator', return_value=validator_obj):
        block1 = bc_for_validation_test.mine_pending_transactions()
    assert block1 is not None
    assert bc_for_validation_test.is_chain_valid() is True

    tx_a_to_b = Transaction(alice_wallet.address, bob_wallet.address, 10.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx_a_to_b.sign(alice_wallet)
    assert bc_for_validation_test.add_transaction(tx_a_to_b, USER_PUBLIC_KEYS[alice_wallet.address])

    charlie_wallet = Wallet()
    USER_PUBLIC_KEYS[charlie_wallet.address] = charlie_wallet.get_public_key_hex()
    tx_b_to_c = Transaction(bob_wallet.address, charlie_wallet.address, 5.0, asset_id=Blockchain.NATIVE_CURRENCY_SYMBOL)
    tx_b_to_c.sign(bob_wallet)
    assert bc_for_validation_test.add_transaction(tx_b_to_c, USER_PUBLIC_KEYS[bob_wallet.address])

    with patch.object(bc_for_validation_test.validator_manager, 'select_next_validator', return_value=validator_obj):
        block2 = bc_for_validation_test.mine_pending_transactions()
    assert block2 is not None
    assert bc_for_validation_test.is_chain_valid() is True


def test_register_validator_wallet_crypto(empty_blockchain_real_genesis, validator_wallet):
    bc = empty_blockchain_real_genesis
    addr = validator_wallet.address
    stake = 100.0
    bc.register_validator_wallet(validator_wallet, stake)
    managed_validator = bc.validator_manager.get_validator(addr)
    assert managed_validator is not None
    assert managed_validator.wallet_address == addr
    assert managed_validator.stake == stake
    assert managed_validator.is_active == (stake >= bc.validator_manager.min_stake_active)
    assert addr in VALIDATOR_WALLETS and VALIDATOR_WALLETS[addr] == validator_wallet
    assert addr in USER_PUBLIC_KEYS and USER_PUBLIC_KEYS[addr] == validator_wallet.get_public_key_hex()

def test_blockchain_repr_crypto(blockchain_with_transactions_pending): # Uses the fixed fixture
    bc = blockchain_with_transactions_pending # Fixture now ensures funding block is mined.

    # Mine the actual test transactions that were added by the fixture
    selected_validator_obj = bc.validator_manager.select_next_validator_round_robin()
    assert selected_validator_obj is not None, "No active validator found in fixture setup for mining test txs"

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=selected_validator_obj):
        mined_block = bc.mine_pending_transactions() # This should mine tx1 and tx2 from the fixture

    assert mined_block is not None, "Mining of fixture transactions failed"
    assert len(bc.chain) == 3 # Genesis + Funding Block + Mined Fixture Txs Block

    repr_str = repr(bc)
    assert "Blockchain State:" in repr_str
    assert "Validators (from Manager):" in repr_str
    assert f"Total Blocks: {len(bc.chain)}" in repr_str
    assert "Block(Index: 0" in repr_str
    assert "Block(Index: 1" in repr_str
    assert "Block(Index: 2" in repr_str
