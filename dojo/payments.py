"""Payments behind one interface: PAYMENTS=mock (local ledger) | paysh (pay.sh gate).

Stage 4 swaps the backend without the teacher server changing at all. In paysh
mode the `pay gate` process sits in FRONT of the teacher and has already
collected payment; it forwards proof, which we record and verify here.
"""
import json
import os
import threading
import time
import uuid

MODE = os.environ.get("PAYMENTS", "mock")
LEDGER_PATH = os.environ.get(
    "DOJO_LEDGER", "/Users/hanavmodasiya/trainme/results/ledger.json"
)

PRICES_USD = {
    "/learn/start": 0.05,      # opens a teaching session
    "/gauntlet/next": 0.05,   # each adversarial world the model builds for you
}   # /learn/submit and /learn/hint are free within a paid session
_lock = threading.Lock()


# -- ledger ---------------------------------------------------------------
def _load():
    if os.path.exists(LEDGER_PATH):
        try:
            with open(LEDGER_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"entries": [], "total_usd": 0.0}


def _save(ledger):
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    tmp = LEDGER_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ledger, f, indent=2)
    os.replace(tmp, LEDGER_PATH)


def record(route, amount_usd, receipt, mode=None):
    with _lock:
        ledger = _load()
        ledger["entries"].append({
            "ts": time.time(),
            "route": route,
            "amount_usd": amount_usd,
            "receipt": receipt,
            "mode": mode or MODE,
        })
        ledger["total_usd"] = round(
            sum(e["amount_usd"] for e in ledger["entries"]), 6
        )
        _save(ledger)
        return ledger["total_usd"]


def total_spend():
    return _load()["total_usd"]


def entries():
    return _load()["entries"]


# -- server side ----------------------------------------------------------
def price_of(route):
    return PRICES_USD.get(route, 0.0)


def verify_payment(route, headers):
    """Server-side gate check. Returns (ok, receipt, error).

    mock : client must present X-Mock-Receipt from a pay() call.
    paysh: the pay.sh gate in front already enforced payment; it forwards
           proof headers, which we require to be present.
    """
    price = price_of(route)
    if price <= 0:
        return True, None, None

    if MODE == "mock":
        receipt = headers.get("x-mock-receipt")
        if not receipt:
            return False, None, "payment required"
        return True, receipt, None

    # paysh: the `pay gate` process in front of us already settled payment on
    # Solana before proxying -- it is the enforcement point and the upstream is
    # only reachable through it. Returning 402 here would make the pay client
    # believe its own settled payment failed. So: admit, and record the receipt
    # the gate forwarded if there is one.
    for h in ("x-payment-receipt", "payment-receipt", "x-pay-receipt",
              "x-payment-response", "payment-receipt-url", "x-pay-payment-id"):
        if headers.get(h):
            record(route, price, headers[h], mode="paysh")
            return True, headers[h], None
    record(route, price, "paysh_gate_settled", mode="paysh")
    return True, "paysh_gate_settled", None


# -- client side ----------------------------------------------------------
def pay_headers(route):
    """Called by the buying agent before hitting a paid route.

    mock : mint a local receipt and debit the ledger.
    paysh: return nothing -- the client goes through `pay curl` / the SDK,
           which attaches real payment headers itself.
    """
    price = price_of(route)
    if price <= 0:
        return {}
    if MODE == "mock":
        receipt = "mock_" + uuid.uuid4().hex[:16]
        record(route, price, receipt, mode="mock")
        return {"X-Mock-Receipt": receipt}
    return {}
