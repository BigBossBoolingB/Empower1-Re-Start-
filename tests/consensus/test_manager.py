import pytest
import time
from empower1.consensus.manager import ValidatorManager, MIN_STAKE_TO_BE_ACTIVE_ATOMIC
from empower1.consensus.validator import Validator

# Sample validator data
VALIDATOR_1_ADDR = "Emp1_ValAddr_001_ManagerTest"
VALIDATOR_1_PK = "04_pk1_" + "a" * 122
VALIDATOR_2_ADDR = "Emp1_ValAddr_002_ManagerTest"
VALIDATOR_2_PK = "04_pk2_" + "b" * 122
VALIDATOR_3_ADDR = "Emp1_ValAddr_003_ManagerTest"
VALIDATOR_3_PK = "04_pk3_" + "c" * 122

from empower1.blockchain import constants as test_constants # For DECIMALS

DECIMALS_FOR_TEST = 6 # Assuming 6 for tests, align with constants.py if possible or define here
def to_atomic_test(val_float): return int(val_float * (10**DECIMALS_FOR_TEST))

@pytest.fixture
def manager():
    """Returns a new ValidatorManager instance for each test, using atomic units for min_stake."""
    # MIN_STAKE_TO_BE_ACTIVE_ATOMIC is imported from manager module
    return ValidatorManager(min_stake_active=MIN_STAKE_TO_BE_ACTIVE_ATOMIC)

def test_manager_initialization(manager):
    assert isinstance(manager.validators, dict)
    assert len(manager.validators) == 0
    assert manager.min_stake_active == MIN_STAKE_TO_BE_ACTIVE_ATOMIC
    assert len(manager._active_validator_addresses_round_robin) == 0

def test_add_new_validator_sufficient_stake(manager):
    stake_atomic = to_atomic_test(150.0)
    val = manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake_atomic)
    assert val is not None
    assert val.wallet_address == VALIDATOR_1_ADDR
    assert val.public_key_hex == VALIDATOR_1_PK
    assert val.stake == stake_atomic
    assert val.is_active is True
    assert VALIDATOR_1_ADDR in manager.validators
    assert VALIDATOR_1_ADDR in manager._active_validator_addresses_round_robin

def test_add_new_validator_insufficient_stake(manager):
    stake_atomic = to_atomic_test(50.0)
    val = manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake_atomic)
    assert val is not None
    assert val.stake == stake_atomic
    assert val.is_active is False
    assert VALIDATOR_1_ADDR not in manager._active_validator_addresses_round_robin

def test_add_new_validator_negative_initial_stake(manager):
    stake_atomic = to_atomic_test(-50.0) # This will become negative int
    val = manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake_atomic)
    assert val is None
    assert VALIDATOR_1_ADDR not in manager.validators

def test_update_validator_stake_increase_to_active(manager):
    initial_stake_atomic = to_atomic_test(50.0)
    additional_stake_atomic = to_atomic_test(75.0)
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, initial_stake_atomic)
    assert manager.validators[VALIDATOR_1_ADDR].is_active is False

    val = manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, additional_stake_atomic)
    assert val.stake == initial_stake_atomic + additional_stake_atomic
    assert val.is_active is True
    assert VALIDATOR_1_ADDR in manager._active_validator_addresses_round_robin

def test_update_validator_stake_decrease_to_inactive(manager):
    initial_stake_atomic = to_atomic_test(150.0)
    reduction_atomic = to_atomic_test(-100.0) # Negative, as it's a change
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, initial_stake_atomic)
    assert manager.validators[VALIDATOR_1_ADDR].is_active is True

    val = manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, reduction_atomic)
    assert val.stake == initial_stake_atomic + reduction_atomic
    assert val.is_active is False
    assert VALIDATOR_1_ADDR not in manager._active_validator_addresses_round_robin

def test_update_validator_stake_cannot_go_negative(manager):
    initial_stake_atomic = to_atomic_test(20.0)
    reduction_atomic = to_atomic_test(-50.0)
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, initial_stake_atomic)
    # Validator.update_stake ensures stake doesn't go below 0 if reduction is too large
    # ValidatorManager.add_or_update_validator_stake calls validator.update_stake
    val = manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, reduction_atomic)
    assert val is not None # Update itself should succeed
    assert manager.validators[VALIDATOR_1_ADDR].stake == 0 # Stake should be 0
    assert val.stake == 0

def test_get_validator(manager):
    stake_atomic = to_atomic_test(100.0)
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake_atomic)
    retrieved_val = manager.get_validator(VALIDATOR_1_ADDR)
    assert retrieved_val is not None
    assert retrieved_val.wallet_address == VALIDATOR_1_ADDR
    assert manager.get_validator("NON_EXISTENT_ADDR") is None

def test_get_active_validators(manager):
    stake1_atomic = to_atomic_test(150.0)
    stake2_atomic = to_atomic_test(50.0)
    stake3_atomic = to_atomic_test(200.0)
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake1_atomic)
    manager.add_or_update_validator_stake(VALIDATOR_2_ADDR, VALIDATOR_2_PK, stake2_atomic)
    manager.add_or_update_validator_stake(VALIDATOR_3_ADDR, VALIDATOR_3_PK, stake3_atomic)

    active_validators = manager.get_active_validators()
    assert len(active_validators) == 2 # Assuming MIN_STAKE_TO_BE_ACTIVE_ATOMIC is 100_000_000
    active_addrs = [v.wallet_address for v in active_validators]
    assert VALIDATOR_1_ADDR in active_addrs
    assert VALIDATOR_3_ADDR in active_addrs
    assert VALIDATOR_2_ADDR not in active_addrs

def test_select_next_validator_round_robin_no_active(manager):
    assert manager.select_next_validator_round_robin() is None

def test_select_next_validator_round_robin_cycling(manager):
    stake_atomic = to_atomic_test(100.0) # Must be >= MIN_STAKE_TO_BE_ACTIVE_ATOMIC
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake_atomic)
    manager.add_or_update_validator_stake(VALIDATOR_2_ADDR, VALIDATOR_2_PK, stake_atomic)
    # Active list should be sorted by address: [VALIDATOR_1_ADDR, VALIDATOR_2_ADDR] if sort order is as expected
    # Forcing a known order for test predictability
    manager._active_validator_addresses_round_robin = sorted([VALIDATOR_1_ADDR, VALIDATOR_2_ADDR])
    manager._last_selected_validator_index_rr = -1


    selected1 = manager.select_next_validator_round_robin()
    assert selected1.wallet_address == manager._active_validator_addresses_round_robin[0]

    selected2 = manager.select_next_validator_round_robin()
    assert selected2.wallet_address == manager._active_validator_addresses_round_robin[1]

    selected3 = manager.select_next_validator_round_robin() # Cycle back
    assert selected3.wallet_address == manager._active_validator_addresses_round_robin[0]

    # Check last_block_produced_timestamp updated
    assert selected1.last_block_produced_timestamp > 0
    original_ts1 = selected1.last_block_produced_timestamp
    time.sleep(0.01)
    selected1_again = manager.select_next_validator_round_robin() # V2
    selected1_again = manager.select_next_validator_round_robin() # V1 again
    assert selected1_again.wallet_address == selected1.wallet_address
    assert selected1_again.last_block_produced_timestamp > original_ts1


def test_select_next_validator_round_robin_skips_inactive(manager):
    stake_active_atomic = to_atomic_test(100.0)
    stake_inactive_atomic = to_atomic_test(50.0)
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake_active_atomic)
    manager.add_or_update_validator_stake(VALIDATOR_2_ADDR, VALIDATOR_2_PK, stake_inactive_atomic)
    manager.add_or_update_validator_stake(VALIDATOR_3_ADDR, VALIDATOR_3_PK, stake_active_atomic)

    # Active list should be [VALIDATOR_1_ADDR, VALIDATOR_3_ADDR] (sorted)
    manager._last_selected_validator_index_rr = -1


    for i in range(4): # Should cycle between V1 and V3
        selected = manager.select_next_validator_round_robin()
        assert selected.is_active is True
        assert selected.wallet_address in [VALIDATOR_1_ADDR, VALIDATOR_3_ADDR]

def test_set_minimum_stake_updates_active_validators(manager):
    stake1_atomic = to_atomic_test(150.0)
    stake2_atomic = to_atomic_test(80.0)
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake1_atomic)
    manager.add_or_update_validator_stake(VALIDATOR_2_ADDR, VALIDATOR_2_PK, stake2_atomic)

    assert manager.validators[VALIDATOR_1_ADDR].is_active is True
    assert manager.validators[VALIDATOR_2_ADDR].is_active is False
    assert len(manager.get_active_validators()) == 1

    new_min_stake1_atomic = to_atomic_test(50.0)
    manager.set_minimum_stake(new_min_stake1_atomic)
    assert manager.validators[VALIDATOR_1_ADDR].is_active is True
    assert manager.validators[VALIDATOR_2_ADDR].is_active is True
    assert len(manager.get_active_validators()) == 2
    assert len(manager._active_validator_addresses_round_robin) == 2

    new_min_stake2_atomic = to_atomic_test(200.0)
    manager.set_minimum_stake(new_min_stake2_atomic)
    assert manager.validators[VALIDATOR_1_ADDR].is_active is False
    assert manager.validators[VALIDATOR_2_ADDR].is_active is False
    assert len(manager.get_active_validators()) == 0

def test_validator_address_pk_consistency_check(manager, capsys):
    stake1_atomic = to_atomic_test(100.0)
    stake2_atomic = to_atomic_test(50.0)
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, VALIDATOR_1_PK, stake1_atomic)
    # Try to update with same address but different PK
    manager.add_or_update_validator_stake(VALIDATOR_1_ADDR, "04_DIFFERENT_PK" + "d"*116, stake2_atomic)
    captured = capsys.readouterr()
    assert "Warning: Public key for existing validator" in captured.out
    assert manager.validators[VALIDATOR_1_ADDR].public_key_hex == VALIDATOR_1_PK
    assert manager.validators[VALIDATOR_1_ADDR].stake == stake1_atomic + stake2_atomic
