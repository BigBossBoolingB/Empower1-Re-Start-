import pytest
import time
from empower1.consensus.validator import Validator

VALID_ADDR = "Emp1_TestAddrForValidator"
VALID_PK_HEX = "04" + "a" * 130 # Valid uncompressed public key hex (65 bytes * 2 = 130 hex chars + '04')

def test_validator_creation_valid():
    """Test valid Validator creation."""
    v = Validator(VALID_ADDR, VALID_PK_HEX, 100.0)
    assert v.wallet_address == VALID_ADDR
    assert v.public_key_hex == VALID_PK_HEX
    assert v.stake == 100.0
    assert v.is_active is False # Default
    assert v.last_block_produced_timestamp == 0.0
    assert v.joined_timestamp <= time.time()

def test_validator_creation_default_stake():
    v = Validator(VALID_ADDR, VALID_PK_HEX)
    assert v.stake == 0.0

@pytest.mark.parametrize("addr, pk, stake, expected_error", [
    ("", VALID_PK_HEX, 100.0, ValueError),             # Empty address
    (None, VALID_PK_HEX, 100.0, ValueError),           # None address
    (VALID_ADDR, "", 100.0, ValueError),               # Empty PK
    (VALID_ADDR, None, 100.0, ValueError),             # None PK
    (VALID_ADDR, VALID_PK_HEX, -10.0, ValueError),     # Negative stake
    (VALID_ADDR, VALID_PK_HEX, "invalid", ValueError), # Invalid stake type
])
def test_validator_creation_invalid_inputs(addr, pk, stake, expected_error):
    """Test Validator creation with various invalid inputs."""
    with pytest.raises(expected_error):
        Validator(addr, pk, stake)

def test_update_stake_add():
    v = Validator(VALID_ADDR, VALID_PK_HEX, 100.0)
    v.update_stake(additional_stake=50.0)
    assert v.stake == 150.0
    v.update_stake(additional_stake=-25.0)
    assert v.stake == 125.0
    v.update_stake(additional_stake=-200.0) # Should go to 0
    assert v.stake == 0.0

def test_update_stake_set_total():
    v = Validator(VALID_ADDR, VALID_PK_HEX, 100.0)
    v.update_stake(new_total_stake=500.0)
    assert v.stake == 500.0
    v.update_stake(new_total_stake=0.0)
    assert v.stake == 0.0

def test_update_stake_set_total_negative_ignored_if_also_additional():
    v = Validator(VALID_ADDR, VALID_PK_HEX, 100.0)
    # If new_total_stake is >= 0, additional_stake is ignored.
    v.update_stake(new_total_stake=50.0, additional_stake=1000.0)
    assert v.stake == 50.0

def test_update_stake_invalid_type():
    v = Validator(VALID_ADDR, VALID_PK_HEX, 100.0)
    with pytest.raises(ValueError):
        v.update_stake(additional_stake="invalid")
    with pytest.raises(ValueError):
        v.update_stake(new_total_stake="invalid")

def test_record_block_production():
    v = Validator(VALID_ADDR, VALID_PK_HEX, 100.0)
    initial_ts = v.last_block_produced_timestamp
    assert initial_ts == 0.0

    time.sleep(0.01) # ensure time progresses
    current_time = time.time()
    v.record_block_production(timestamp=current_time)
    assert v.last_block_produced_timestamp == current_time

    time.sleep(0.01)
    v.record_block_production() # Uses current time
    assert v.last_block_produced_timestamp > current_time


def test_validator_equality_and_hash():
    v1a = Validator(VALID_ADDR, VALID_PK_HEX, 100.0)
    v1b = Validator(VALID_ADDR, "another_pk_hex", 200.0) # Same address, different pk/stake
    v2 = Validator("OtherAddress", VALID_PK_HEX, 100.0)

    assert v1a == v1b # Equality is based on wallet_address
    assert v1a != v2
    assert v1a != "not_a_validator_object"

    assert hash(v1a) == hash(v1b)
    assert hash(v1a) != hash(v2)

    validator_set = {v1a, v1b, v2}
    assert len(validator_set) == 2 # v1a and v1b are treated as same due to hash on wallet_address

def test_validator_repr():
    v = Validator(VALID_ADDR, VALID_PK_HEX, stake=123.45)
    v.is_active = True
    v.last_block_produced_timestamp = 1678886400.0 # A fixed past timestamp

    repr_str = repr(v)
    assert VALID_ADDR[:10] in repr_str
    assert VALID_PK_HEX[:10] in repr_str
    assert "Stake: 123.45" in repr_str
    assert "Active: True" in repr_str
    assert "LastProdTS: 1678886400" in repr_str # .0f format

def test_validator_to_dict_from_dict():
    """Test serialization to dict and deserialization from dict."""
    original_ts = time.time()
    v_orig = Validator(VALID_ADDR, VALID_PK_HEX, 150.5)
    v_orig.is_active = True
    v_orig.last_block_produced_timestamp = original_ts - 1000 # A past time
    # joined_timestamp is set on init

    v_dict = v_orig.to_dict()
    expected_keys = ["wallet_address", "public_key_hex", "stake",
                     "last_block_produced_timestamp", "is_active", "joined_timestamp"]
    assert all(key in v_dict for key in expected_keys)
    assert v_dict["wallet_address"] == v_orig.wallet_address
    assert v_dict["public_key_hex"] == v_orig.public_key_hex
    assert v_dict["stake"] == v_orig.stake
    assert v_dict["is_active"] == v_orig.is_active
    assert v_dict["last_block_produced_timestamp"] == v_orig.last_block_produced_timestamp
    assert v_dict["joined_timestamp"] == v_orig.joined_timestamp

    v_new = Validator.from_dict(v_dict)
    assert v_new.wallet_address == v_orig.wallet_address
    assert v_new.public_key_hex == v_orig.public_key_hex
    assert v_new.stake == v_orig.stake
    assert v_new.is_active == v_orig.is_active
    assert v_new.last_block_produced_timestamp == v_orig.last_block_produced_timestamp
    assert v_new.joined_timestamp == v_orig.joined_timestamp # Ensure joined_timestamp is also handled

    # Test from_dict with minimal data (relying on defaults in from_dict)
    minimal_data = {
        "wallet_address": "MinAddr",
        "public_key_hex": "MinPK"
        # stake, last_block_produced_timestamp, is_active, joined_timestamp use defaults
    }
    v_minimal = Validator.from_dict(minimal_data)
    assert v_minimal.wallet_address == "MinAddr"
    assert v_minimal.public_key_hex == "MinPK"
    assert v_minimal.stake == 0.0
    assert v_minimal.is_active is False
    assert v_minimal.last_block_produced_timestamp == 0.0
    assert isinstance(v_minimal.joined_timestamp, float) # Should default to current time
