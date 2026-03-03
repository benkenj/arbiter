"""Unit tests for the Trade pydantic model in polymarket client (03-01)."""
import pytest
from pydantic import ValidationError

from arbiter.clients.polymarket import Trade


class TestTradeModelParsing:
    def test_parses_camel_case_aliases(self):
        data = {
            "proxyWallet": "0xabc123",
            "side": "BUY",
            "size": 10.5,
            "price": 0.65,
            "timestamp": 1700000000,
            "conditionId": "0xcondition1",
            "outcome": "Yes",
        }
        trade = Trade.model_validate(data)
        assert trade.proxy_wallet == "0xabc123"
        assert trade.condition_id == "0xcondition1"

    def test_populate_by_snake_case_name(self):
        # populate_by_name=True allows snake_case field names too
        trade = Trade(
            proxy_wallet="0xdef",
            side="SELL",
            size=5.0,
            price=0.3,
            timestamp=1700000001,
            condition_id="0xcondition2",
        )
        assert trade.proxy_wallet == "0xdef"
        assert trade.condition_id == "0xcondition2"

    def test_outcome_is_optional(self):
        data = {
            "proxyWallet": "0xabc",
            "side": "BUY",
            "size": 1.0,
            "price": 0.5,
            "timestamp": 1700000000,
            "conditionId": "0xcond",
        }
        trade = Trade.model_validate(data)
        assert trade.outcome is None

    def test_outcome_none_explicit(self):
        data = {
            "proxyWallet": "0xabc",
            "side": "BUY",
            "size": 1.0,
            "price": 0.5,
            "timestamp": 1700000000,
            "conditionId": "0xcond",
            "outcome": None,
        }
        trade = Trade.model_validate(data)
        assert trade.outcome is None

    def test_sell_side(self):
        data = {
            "proxyWallet": "0xseller",
            "side": "SELL",
            "size": 20.0,
            "price": 0.8,
            "timestamp": 1700005000,
            "conditionId": "0xcond2",
            "outcome": "No",
        }
        trade = Trade.model_validate(data)
        assert trade.side == "SELL"
        assert trade.outcome == "No"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            Trade.model_validate({"proxyWallet": "0xabc", "side": "BUY"})

    def test_timestamp_is_int(self):
        data = {
            "proxyWallet": "0xabc",
            "side": "BUY",
            "size": 1.0,
            "price": 0.5,
            "timestamp": 1700000000,
            "conditionId": "0xcond",
        }
        trade = Trade.model_validate(data)
        assert isinstance(trade.timestamp, int)
        assert trade.timestamp == 1700000000
