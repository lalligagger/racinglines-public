"""Polymarket order signing (CLOB V2): dry runs only. No order is sent, no network is used.

The signer key is a throwaway test key; POLYMARKET_TRADING_ENABLED is never set here.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from racinglines.markets.polymarket import trade

pytestmark = pytest.mark.quick

KEY = "0x" + "11" * 32                   # a throwaway key, not a wallet anyone funds
TOKEN = "71321045679252212594626385532706912750332728571942532289631379312455583992563"
BOOK = dict(best_bid=0.40, best_ask=0.45, bids=[], asks=[], tick_size=0.01, min_size=5, neg_risk=False,
            last_trade=None)


def cfg(**kw):
    base = dict(private_key=KEY, funder=None, signature_type=0, api_key=None, api_secret=None,
                api_passphrase=None, enabled=False, max_order_usd=25, chain_id=137)
    return trade.TradingConfig(**{**base, **kw})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any HTTP call from the CLOB client fails the test: dry runs must stay on this machine."""
    from py_clob_client_v2.http_helpers import helpers

    def refuse(*a, **kw):
        raise AssertionError(f"network call in a dry run: {a[:2]}")
    monkeypatch.setattr(helpers, "request", refuse)
    monkeypatch.delenv("POLYMARKET_TRADING_ENABLED", raising=False)


def recover(order_json, neg_risk=False):
    """Rebuild the EIP-712 typed data from the posted payload and recover the signer."""
    from py_clob_client_v2.config import get_contract_config
    from py_clob_client_v2.order_utils.model.ctf_exchange_v2_typed_data import CTF_EXCHANGE_V2_ORDER_STRUCT
    from py_clob_client_v2.order_utils.model.ctf_exchange_v1_typed_data import EIP712_DOMAIN

    o = order_json["order"]
    cc = get_contract_config(137)
    typed = {
        "primaryType": "Order",
        "types": {"EIP712Domain": EIP712_DOMAIN, "Order": CTF_EXCHANGE_V2_ORDER_STRUCT},
        "domain": {"name": "Polymarket CTF Exchange", "version": "2", "chainId": 137,
                   "verifyingContract": cc.neg_risk_exchange_v2 if neg_risk else cc.exchange_v2},
        "message": {"salt": int(o["salt"]), "maker": o["maker"], "signer": o["signer"], "tokenId": int(o["tokenId"]),
                    "makerAmount": int(o["makerAmount"]), "takerAmount": int(o["takerAmount"]),
                    "side": 0 if o["side"] == "BUY" else 1, "signatureType": o["signatureType"],
                    "timestamp": int(o["timestamp"]), "metadata": bytes.fromhex(o["metadata"][2:]),
                    "builder": bytes.fromhex(o["builder"][2:])},
    }
    return Account.recover_message(encode_typed_data(full_message=typed), signature=o["signature"])


def test_dry_run_signs_a_v2_order_locally():
    status, oid, resp = trade.place_maker_order(cfg(), TOKEN, "BUY", 0.42, 10, BOOK)
    assert (status, oid) == ("dry_run", None)
    assert resp["order_version"] == 2
    o = resp["signed_order"]
    assert o["postOnly"] is True and o["orderType"] == "GTC"
    assert o["order"]["side"] == "BUY" and o["order"]["tokenId"] == TOKEN
    # BUY 10 @ 0.42: pay 4.2 USDC (6 decimals) for 10 shares
    assert (o["order"]["makerAmount"], o["order"]["takerAmount"]) == ("4200000", "10000000")
    assert "feeRateBps" not in o["order"] and "nonce" not in o["order"]        # V1-only fields
    assert recover(o) == Account.from_key(KEY).address == o["order"]["signer"]


def test_dry_run_sell_on_a_neg_risk_market_uses_the_neg_risk_exchange():
    bk = dict(BOOK, neg_risk=True, tick_size=0.001)
    _, _, resp = trade.place_maker_order(cfg(), TOKEN, "SELL", 0.456, 20, bk)
    o = resp["signed_order"]
    assert (o["order"]["makerAmount"], o["order"]["takerAmount"]) == ("20000000", "9120000")
    assert recover(o, neg_risk=True) == Account.from_key(KEY).address
    assert recover(o, neg_risk=False) != Account.from_key(KEY).address


def test_tick_literal():
    assert [trade._tick(t) for t in (0.1, 0.01, 0.005, 0.001, 0.0001)] == ["0.1", "0.01", "0.005", "0.001", "0.0001"]


@pytest.mark.parametrize("side, price, size, why", [
    ("BUY", 0.45, 10, "cross the best ask"),
    ("SELL", 0.40, 10, "cross the best bid"),
    ("BUY", 0.425, 10, "multiple of the tick"),
    ("BUY", 0.30, 2, "at least 5"),
    ("BUY", 0.30, 100, "exceeds POLYMARKET_MAX_ORDER_USD"),
    ("HOLD", 0.30, 10, "BUY or SELL"),
])
def test_rejected_before_signing(side, price, size, why):
    with pytest.raises(trade.OrderRejected, match=why):
        trade.place_maker_order(cfg(), TOKEN, side, price, size, BOOK)


def test_no_key_no_order():
    with pytest.raises(trade.OrderRejected, match="PRIVATE_KEY"):
        trade.place_maker_order(cfg(private_key=None), TOKEN, "BUY", 0.42, 10, BOOK)


def test_trading_off_by_default(monkeypatch):
    c = trade.TradingConfig.from_env()
    assert c.enabled is False and c.order_version == 2
    assert trade.open_orders(cfg()) == []
    with pytest.raises(trade.OrderRejected, match="not enabled"):
        trade.cancel(cfg(), "0xabc")
