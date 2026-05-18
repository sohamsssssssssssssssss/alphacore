from __future__ import annotations

import pytest

from users.user_manager import SubscriptionTier, UserManager


@pytest.fixture
def mgr(tmp_path):
    db = tmp_path / "users.db"
    return UserManager(db_url=f"sqlite:///{db}")


def test_create_user_returns_account_fields(mgr):
    u = mgr.create_user(id="u1", name="Alice", capital=123456.0)
    assert u.id == "u1"
    assert u.name == "Alice"
    assert u.capital == 123456.0
    assert u.tier == SubscriptionTier.FREE
    assert u.kill_switch is False
    assert u.risk_limits["max_position"] == 50000


def test_duplicate_user_id_raises_value_error(mgr):
    mgr.create_user(id="u1", name="Alice", capital=100000)
    with pytest.raises(ValueError):
        mgr.create_user(id="u1", name="Bob", capital=200000)


def test_get_user_raises_key_error_for_unknown(mgr):
    with pytest.raises(KeyError):
        mgr.get_user("missing")


def test_set_kill_switch_flips_flag(mgr):
    mgr.create_user(id="u1", name="Alice", capital=100000)
    mgr.set_kill_switch("u1", True)
    assert mgr.get_user("u1").kill_switch is True
    mgr.set_kill_switch("u1", False)
    assert mgr.get_user("u1").kill_switch is False


def test_kill_switch_blocks_factories(mgr):
    mgr.create_user(id="u1", name="Alice", capital=100000)
    mgr.set_kill_switch("u1", True)
    with pytest.raises(RuntimeError):
        mgr.get_risk_gate("u1")
    with pytest.raises(RuntimeError):
        mgr.get_paper_engine("u1")


def test_two_users_have_independent_risk_gates(mgr):
    mgr.create_user(id="u1", name="A", capital=100000, risk_limits={"max_position": 50000})
    mgr.create_user(id="u2", name="B", capital=200000, risk_limits={"max_position": 75000, "daily_loss": 9000})

    g1 = mgr.get_risk_gate("u1")
    g2 = mgr.get_risk_gate("u2")

    assert g1 is not g2
    assert g1.starting_capital == 100000
    assert g2.starting_capital == 200000
    assert g1.max_position_inr == 50000
    assert g2.max_position_inr == 75000
    assert g1.max_daily_loss != g2.max_daily_loss


def test_check_subscription_for_tiers(mgr):
    mgr.create_user(id="u_free", name="F", capital=100000, tier=SubscriptionTier.FREE)
    mgr.create_user(id="u_pro", name="P", capital=100000, tier=SubscriptionTier.PRO)
    mgr.create_user(id="u_ent", name="E", capital=100000, tier=SubscriptionTier.ENTERPRISE)

    assert mgr.check_subscription("u_free") is False
    assert mgr.check_subscription("u_pro") is True
    assert mgr.check_subscription("u_ent") is True


def test_list_users_returns_all_created(mgr):
    mgr.create_user(id="u1", name="A", capital=1)
    mgr.create_user(id="u2", name="B", capital=2)
    ids = [u.id for u in mgr.list_users()]
    assert set(ids) == {"u1", "u2"}
