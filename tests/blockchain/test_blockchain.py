import pytest
import time
from unittest.mock import patch
from empower1.blockchain import constants # Import constants
from empower1.blockchain.blockchain import Blockchain, USER_PUBLIC_KEYS, VALIDATOR_WALLETS
from empower1.blockchain.block import Block
from empower1.blockchain.transaction import Transaction
from empower1.consensus.manager import ValidatorManager
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
    assert genesis_block.proof is not None
    assert genesis_block.proof == {"type": "Genesis", "validator": genesis_block.validator_address, "details": "initial_block_proof_v1"}

    genesis_validator_pub_key = USER_PUBLIC_KEYS.get(genesis_block.validator_address)
    assert genesis_validator_pub_key is not None
    assert genesis_block.verify_block_signature(genesis_validator_pub_key) is True

    assert len(bc.pending_transactions) == 0
    assert isinstance(bc.validator_manager, ValidatorManager)
    assert len(bc.validator_manager.validators) == 1
    genesis_validator_in_manager = bc.validator_manager.get_validator(genesis_block.validator_address)
    assert genesis_validator_in_manager is not None
    assert genesis_validator_in_manager.wallet_address == genesis_block.validator_address
    assert genesis_validator_in_manager.public_key_hex == genesis_validator_pub_key
    assert genesis_validator_in_manager.stake == constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC // 2
    assert genesis_validator_in_manager.is_active is True

    assert bc.total_supply_epc == constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC
    assert bc.balances.get(genesis_block.validator_address) == constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC
    assert sum(bc.balances.values()) == constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC


def test_last_block_property_crypto(blockchain_with_one_validator, alice_wallet, bob_wallet, validator_wallet):
    bc = blockchain_with_one_validator
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    genesis_validator_addr = bc.chain[0].validator_address
    assert bc.balances.get(genesis_validator_addr, 0) > 0
    genesis_val_wallet = VALIDATOR_WALLETS[genesis_validator_addr]

    tx_amount_atomic = constants.to_atomic(1.0)
    tx = Transaction(genesis_validator_addr, bob_wallet.address, tx_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx.sign(genesis_val_wallet)
    assert bc.add_transaction(tx, USER_PUBLIC_KEYS[genesis_validator_addr])

    expected_miner_validator_obj = bc.validator_manager.get_validator(bc.node_wallet.address)
    assert expected_miner_validator_obj is not None
    assert expected_miner_validator_obj.is_active is True

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=expected_miner_validator_obj):
        mined_block = bc.mine_pending_transactions()
        assert mined_block is not None, f"Mining failed. Selected validator by mock: {expected_miner_validator_obj.wallet_address}, bc.node_wallet: {bc.node_wallet.address}"
        assert bc.last_block == mined_block
        assert bc.last_block.index == 1

def test_process_transaction_valid_epc_transfer(empty_blockchain_real_genesis, alice_wallet, bob_wallet):
    bc = empty_blockchain_real_genesis
    initial_alice_balance_atomic = constants.to_atomic(100.0)
    transfer_amount_atomic = constants.to_atomic(50.0)
    bc.balances[alice_wallet.address] = initial_alice_balance_atomic
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()

    tx = Transaction(alice_wallet.address, bob_wallet.address, transfer_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx.sign(alice_wallet)

    assert bc._process_transaction_for_state_changes(tx) is True
    assert bc.balances.get(alice_wallet.address) == initial_alice_balance_atomic - transfer_amount_atomic
    assert bc.balances.get(bob_wallet.address) == transfer_amount_atomic

def test_process_transaction_insufficient_funds(empty_blockchain_real_genesis, alice_wallet, bob_wallet):
    bc = empty_blockchain_real_genesis
    initial_alice_balance_atomic = constants.to_atomic(10.0)
    transfer_amount_atomic = constants.to_atomic(50.0)
    bc.balances[alice_wallet.address] = initial_alice_balance_atomic
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()

    tx = Transaction(alice_wallet.address, bob_wallet.address, transfer_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx.sign(alice_wallet)

    assert bc._process_transaction_for_state_changes(tx) is False
    assert bc.balances.get(alice_wallet.address) == initial_alice_balance_atomic
    assert bc.balances.get(bob_wallet.address, 0) == 0

def test_process_transaction_non_epc_asset(empty_blockchain_real_genesis, alice_wallet, bob_wallet):
    bc = empty_blockchain_real_genesis
    initial_alice_balance_atomic = constants.to_atomic(100.0)
    transfer_amount_atomic = constants.to_atomic(10.0)
    bc.balances[alice_wallet.address] = initial_alice_balance_atomic
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()

    tx = Transaction(alice_wallet.address, bob_wallet.address, transfer_amount_atomic, asset_id="OTHER_COIN")
    tx.sign(alice_wallet)

    assert bc._process_transaction_for_state_changes(tx) is True
    assert bc.balances.get(alice_wallet.address) == initial_alice_balance_atomic
    assert bc.balances.get(bob_wallet.address, 0) == 0

def test_add_transaction_insufficient_funds_precheck(empty_blockchain_real_genesis, alice_wallet, bob_wallet, capsys):
    bc = empty_blockchain_real_genesis
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    transfer_amount_atomic = constants.to_atomic(50.0)
    tx = Transaction(alice_wallet.address, bob_wallet.address, transfer_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx.sign(alice_wallet)

    assert bc.add_transaction(tx, alice_wallet.get_public_key_hex()) is False
    captured = capsys.readouterr()
    assert "insufficient available balance" in captured.out
    assert tx not in bc.pending_transactions

def test_mine_pending_transactions_processes_valid_epc_txs(blockchain_with_one_validator, validator_wallet, alice_wallet, bob_wallet):
    bc = blockchain_with_one_validator

    genesis_validator_addr = bc.chain[0].validator_address
    genesis_validator_wallet = VALIDATOR_WALLETS[genesis_validator_addr]

    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    fund_alice_amount_atomic = constants.to_atomic(200.0)
    fund_alice_tx = Transaction(genesis_validator_addr, alice_wallet.address, fund_alice_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    fund_alice_tx.sign(genesis_validator_wallet)
    assert bc.add_transaction(fund_alice_tx, USER_PUBLIC_KEYS[genesis_validator_addr])

    funding_validator_obj = bc.validator_manager.get_validator(validator_wallet.address)
    assert funding_validator_obj is not None
    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        mined_funding_block = bc.mine_pending_transactions()
    assert mined_funding_block is not None
    assert bc.balances.get(alice_wallet.address) == fund_alice_amount_atomic

    tx_ab_amount_atomic = constants.to_atomic(50.0)
    tx_alice_to_bob = Transaction(alice_wallet.address, bob_wallet.address, tx_ab_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_alice_to_bob.sign(alice_wallet)
    assert bc.add_transaction(tx_alice_to_bob, alice_wallet.get_public_key_hex())

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        mined_block_2 = bc.mine_pending_transactions()

    assert mined_block_2 is not None
    assert len(mined_block_2.transactions) == 1
    assert mined_block_2.transactions[0].transaction_id == tx_alice_to_bob.transaction_id

    # bc.total_supply_epc is INITIAL_TOTAL_SUPPLY_EPC_ATOMIC from genesis
    assert bc.balances.get(genesis_validator_addr) == constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC - fund_alice_amount_atomic
    assert bc.balances.get(alice_wallet.address) == fund_alice_amount_atomic - tx_ab_amount_atomic
    assert bc.balances.get(bob_wallet.address) == tx_ab_amount_atomic
    assert not bc.pending_transactions

def test_mine_pending_transactions_skips_invalid_epc_tx_insufficient_funds(blockchain_with_one_validator, validator_wallet, alice_wallet, bob_wallet):
    bc = blockchain_with_one_validator
    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    genesis_validator_addr = bc.chain[0].validator_address
    genesis_validator_wallet = VALIDATOR_WALLETS[genesis_validator_addr]
    fund_alice_amount_atomic_30 = constants.to_atomic(30.0)
    tx_funding_alice = Transaction(genesis_validator_addr, alice_wallet.address, fund_alice_amount_atomic_30, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_funding_alice.sign(genesis_validator_wallet)
    assert bc.add_transaction(tx_funding_alice, USER_PUBLIC_KEYS[genesis_validator_addr])

    funding_validator_obj = bc.validator_manager.get_validator(validator_wallet.address)
    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        assert bc.mine_pending_transactions() is not None
    assert bc.balances.get(alice_wallet.address) == fund_alice_amount_atomic_30

    tx1_fail_amount_atomic = constants.to_atomic(50.0)
    tx1_fail = Transaction(alice_wallet.address, bob_wallet.address, tx1_fail_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx1_fail.sign(alice_wallet)
    assert bc.add_transaction(tx1_fail, alice_wallet.get_public_key_hex()) is False

    tx2_valid_amount_atomic = constants.to_atomic(20.0)
    tx2_valid = Transaction(alice_wallet.address, bob_wallet.address, tx2_valid_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx2_valid.sign(alice_wallet)
    assert bc.add_transaction(tx2_valid, alice_wallet.get_public_key_hex())

    assert len(bc.pending_transactions) == 1

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=funding_validator_obj):
        mined_block = bc.mine_pending_transactions()

    assert mined_block is not None
    assert len(mined_block.transactions) == 1
    assert mined_block.transactions[0].transaction_id == tx2_valid.transaction_id

    assert bc.balances.get(alice_wallet.address) == fund_alice_amount_atomic_30 - tx2_valid_amount_atomic
    assert bc.balances.get(bob_wallet.address) == tx2_valid_amount_atomic
    assert not bc.pending_transactions

def test_is_chain_valid_crypto_focus(alice_wallet, bob_wallet):
    bc_node_wallet = Wallet()
    bc_for_validation_test = Blockchain(node_wallet=bc_node_wallet)
    val_for_test_stake_atomic = constants.to_atomic(1000.0)
    val_for_test = Wallet()
    bc_for_validation_test.register_validator_wallet(val_for_test, val_for_test_stake_atomic)
    USER_PUBLIC_KEYS[val_for_test.address] = val_for_test.get_public_key_hex()
    VALIDATOR_WALLETS[val_for_test.address] = val_for_test

    gen_val_addr = bc_for_validation_test.chain[0].validator_address
    gen_val_wallet = VALIDATOR_WALLETS[gen_val_addr]

    USER_PUBLIC_KEYS[alice_wallet.address] = alice_wallet.get_public_key_hex()
    USER_PUBLIC_KEYS[bob_wallet.address] = bob_wallet.get_public_key_hex()

    fund_alice_atomic = constants.to_atomic(100.0)
    tx_fund_alice = Transaction(gen_val_addr, alice_wallet.address, fund_alice_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_fund_alice.sign(gen_val_wallet)
    assert bc_for_validation_test.add_transaction(tx_fund_alice, USER_PUBLIC_KEYS[gen_val_addr])

    fund_bob_atomic = constants.to_atomic(100.0)
    tx_fund_bob = Transaction(gen_val_addr, bob_wallet.address, fund_bob_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_fund_bob.sign(gen_val_wallet)
    assert bc_for_validation_test.add_transaction(tx_fund_bob, USER_PUBLIC_KEYS[gen_val_addr])

    expected_miner_obj_block1 = bc_for_validation_test.validator_manager.get_validator(bc_node_wallet.address)
    assert expected_miner_obj_block1 is not None

    with patch.object(bc_for_validation_test.validator_manager, 'select_next_validator', return_value=expected_miner_obj_block1):
        block1 = bc_for_validation_test.mine_pending_transactions()
    assert block1 is not None, "Block1 mining failed"
    assert bc_for_validation_test.is_chain_valid() is True

    tx_ab_amount_atomic = constants.to_atomic(10.0)
    tx_a_to_b = Transaction(alice_wallet.address, bob_wallet.address, tx_ab_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_a_to_b.sign(alice_wallet)
    assert bc_for_validation_test.add_transaction(tx_a_to_b, USER_PUBLIC_KEYS[alice_wallet.address])

    charlie_wallet = Wallet()
    USER_PUBLIC_KEYS[charlie_wallet.address] = charlie_wallet.get_public_key_hex()
    tx_bc_amount_atomic = constants.to_atomic(5.0)
    tx_b_to_c = Transaction(bob_wallet.address, charlie_wallet.address, tx_bc_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_b_to_c.sign(bob_wallet)
    assert bc_for_validation_test.add_transaction(tx_b_to_c, USER_PUBLIC_KEYS[bob_wallet.address])

    expected_miner_obj_block2 = bc_for_validation_test.validator_manager.get_validator(bc_node_wallet.address)
    assert expected_miner_obj_block2 is not None

    with patch.object(bc_for_validation_test.validator_manager, 'select_next_validator', return_value=expected_miner_obj_block2):
        block2 = bc_for_validation_test.mine_pending_transactions()
    assert block2 is not None, "Block2 mining failed"
    assert bc_for_validation_test.is_chain_valid() is True


def test_register_validator_wallet_crypto(empty_blockchain_real_genesis, validator_wallet):
    bc = empty_blockchain_real_genesis
    addr = validator_wallet.address
    stake_atomic = constants.to_atomic(100.0)

    genesis_validator_addr = bc.node_wallet.address
    genesis_validator_wallet = VALIDATOR_WALLETS[genesis_validator_addr]
    if addr != genesis_validator_addr:
        funding_tx_amount = stake_atomic + constants.to_atomic(10.0)
        fund_tx = Transaction(genesis_validator_addr, addr, funding_tx_amount, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
        fund_tx.sign(genesis_validator_wallet)
        assert bc.add_transaction(fund_tx, USER_PUBLIC_KEYS[genesis_validator_addr])

        miner_obj = bc.validator_manager.get_validator(genesis_validator_addr)
        with patch.object(bc.validator_manager, 'select_next_validator', return_value=miner_obj):
            mined_block = bc.mine_pending_transactions()
        assert mined_block is not None, "Funding transaction for staking test failed to mine"
        assert bc.balances.get(addr, 0) >= stake_atomic

    bc.register_validator_wallet(validator_wallet, stake_atomic)
    managed_validator = bc.validator_manager.get_validator(addr)
    assert managed_validator is not None
    assert managed_validator.wallet_address == addr
    assert managed_validator.stake == stake_atomic
    assert managed_validator.is_active == (stake_atomic >= bc.validator_manager.min_stake_active)
    assert addr in VALIDATOR_WALLETS and VALIDATOR_WALLETS[addr] == validator_wallet
    assert addr in USER_PUBLIC_KEYS and USER_PUBLIC_KEYS[addr] == validator_wallet.get_public_key_hex()

def test_blockchain_repr_crypto(blockchain_with_transactions_pending):
    bc = blockchain_with_transactions_pending

    selected_validator_obj = bc.validator_manager.select_next_validator_round_robin()
    assert selected_validator_obj is not None, "No active validator found in fixture setup for mining test txs"

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=selected_validator_obj):
        mined_block = bc.mine_pending_transactions()

    assert mined_block is not None, "Mining of fixture transactions failed"
    assert len(bc.chain) == 3

    repr_str = repr(bc)
    assert "Blockchain State:" in repr_str
    assert "Validators (from Manager):" in repr_str
    assert f"Total Blocks: {len(bc.chain)}" in repr_str
    assert "Block(Index: 0" in repr_str
    assert "Block(Index: 1" in repr_str
    assert "Block(Index: 2" in repr_str


def test_mine_pending_transactions_respects_selected_validator(empty_blockchain_real_genesis, alice_wallet, bob_wallet):
    bc = empty_blockchain_real_genesis
    val_g_addr = bc.node_wallet.address
    val_g_pk = bc.node_wallet.get_public_key_hex()

    assert bc.validator_manager.get_validator(val_g_addr) is not None
    assert bc.validator_manager.get_validator(val_g_addr).is_active is True

    val_2 = Wallet()
    USER_PUBLIC_KEYS[val_2.address] = val_2.get_public_key_hex()
    VALIDATOR_WALLETS[val_2.address] = val_2

    # Fund val_2 before it can stake
    # Ensure val_g (genesis validator) has its public key in USER_PUBLIC_KEYS
    if val_g_addr not in USER_PUBLIC_KEYS: # Should be there from Blockchain init
        USER_PUBLIC_KEYS[val_g_addr] = val_g_pk

    # Determine funding amount needed for val_2 to stake
    stake_for_val2 = bc.validator_manager.min_stake_active + constants.to_atomic(100.0)
    funding_for_val2 = stake_for_val2 + constants.to_atomic(1.0) # Stake + a little extra for fees if any

    tx_fund_val2 = Transaction(val_g_addr, val_2.address, funding_for_val2, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_fund_val2.sign(VALIDATOR_WALLETS[val_g_addr])
    assert bc.add_transaction(tx_fund_val2, val_g_pk), "Failed to add funding tx for val_2"

    # Mine the funding transaction for val_2 (mined by val_g, who is bc.node_wallet)
    with patch.object(bc.validator_manager, 'select_next_validator', return_value=bc.validator_manager.get_validator(val_g_addr)):
        funding_block_for_val2 = bc.mine_pending_transactions()
    assert funding_block_for_val2 is not None, "Failed to mine funding block for val_2"
    assert bc.balances.get(val_2.address, 0) >= stake_for_val2, "val_2 not funded sufficiently"

    # Now register val_2 with its stake
    bc.register_validator_wallet(val_2, stake_amount_atomic=stake_for_val2)
    assert bc.validator_manager.get_validator(val_2.address) is not None, f"val_2 not found in manager after staking. Balance: {bc.balances.get(val_2.address)}"
    assert bc.validator_manager.get_validator(val_2.address).is_active is True

    active_validators = bc.validator_manager._active_validator_addresses_round_robin
    assert len(active_validators) == 2

    if val_g_addr not in USER_PUBLIC_KEYS:
        USER_PUBLIC_KEYS[val_g_addr] = val_g_pk

    tx_amount_alice = constants.to_atomic(10.0)
    tx_fund_alice = Transaction(val_g_addr, alice_wallet.address, tx_amount_alice, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_fund_alice.sign(VALIDATOR_WALLETS[val_g_addr])
    assert bc.add_transaction(tx_fund_alice, val_g_pk)
    assert len(bc.pending_transactions) == 1

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=bc.validator_manager.get_validator(val_2.address)):
        mined_block_by_other = bc.mine_pending_transactions()
        assert mined_block_by_other is None, "Node should not have mined as it was not selected."
        assert len(bc.chain) == 2 # After val_2's funding block, before this scenario's tx_fund_alice
        assert len(bc.pending_transactions) == 1 # tx_fund_alice should still be pending

    with patch.object(bc.validator_manager, 'select_next_validator', return_value=bc.validator_manager.get_validator(val_g_addr)):
        mined_block_by_self = bc.mine_pending_transactions()
        assert mined_block_by_self is not None, "Node should have mined as it was selected."
        assert len(bc.chain) == 3 # After tx_fund_alice is mined
        assert mined_block_by_self.validator_address == val_g_addr
        assert len(bc.pending_transactions) == 0

    val_g_obj = bc.validator_manager.get_validator(val_g_addr)
    val_2_obj = bc.validator_manager.get_validator(val_2.address)
    if val_g_obj: val_g_obj.is_active = False
    if val_2_obj: val_2_obj.is_active = False
    bc.validator_manager._rebuild_active_validator_list_for_round_robin()

    if val_g_addr not in USER_PUBLIC_KEYS:
        USER_PUBLIC_KEYS[val_g_addr] = val_g_pk

    tx_amount_bob = constants.to_atomic(5.0)
    tx_fund_bob = Transaction(val_g_addr, bob_wallet.address, tx_amount_bob, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx_fund_bob.sign(VALIDATOR_WALLETS[val_g_addr])
    assert bc.add_transaction(tx_fund_bob, val_g_pk), "Failed to add second tx for no-active-validator test"

    mined_block_no_active = bc.mine_pending_transactions()
    assert mined_block_no_active is None, "Mining should fail if no active validators can be selected."

    if val_g_obj: val_g_obj.is_active = True
    if val_2_obj: val_2_obj.is_active = True
    bc.validator_manager._rebuild_active_validator_list_for_round_robin()
