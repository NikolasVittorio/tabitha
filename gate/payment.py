import re
from decimal import Decimal
from typing import Callable, NamedTuple

DENOM = "afet"  # real FET on Fetch mainnet
MSG_SEND = "/cosmos.bank.v1beta1.MsgSend"


class FetSettings(NamedTuple):
    pay_to: str
    price: str  # as shown to the buyer, like "0.5"
    afet: int
    refund_contact: str


def fet_settings(env) -> FetSettings | None:
    """None when FET payments are not configured. ValueError when only partly or wrongly configured, so a typo
    can never take real money with no way to claim a refund. Pays the owner's wallet, not the agent's: the
    server renders untrusted pages and should hold no real funds."""
    pay_to, price, contact = (env.get(k, "").strip() for k in ("FET_PAY_TO", "FET_PRICE", "FET_REFUND_CONTACT"))
    if not (pay_to or price or contact):
        return None
    if not re.fullmatch(r"fetch1[0-9a-z]{38}", pay_to):
        raise ValueError("FET_PAY_TO must be a fetch1 address")
    if not re.fullmatch(r"\d+(\.\d{1,18})?", price) or Decimal(price) <= 0:
        raise ValueError("FET_PRICE must be a positive number like 0.5")
    if not contact:
        raise ValueError("FET_REFUND_CONTACT is required")
    return FetSettings(pay_to, price, int(Decimal(price) * 10**18), contact)


def verify_fet_payment(tx_hash: str, to_address: str, min_afet: int,
                       get_tx: Callable[[str], dict | None], used: set[str], expected_memo: str) -> bool:
    """True once per hash: a successful tx paying >= min_afet afet to to_address whose memo is
    expected_memo (the job id), so a tx can't be claimed by another job or buyer.
    Synchronous on purpose: the `used` check and add can't interleave with another job."""
    if tx_hash in used:
        return False
    tx = get_tx(tx_hash)
    if not tx or tx.get("code", 0) != 0 or not expected_memo or tx.get("memo") != expected_memo:
        return False
    paid = sum(int(c["amount"]) for m in tx.get("messages", [])
               if m.get("@type") == MSG_SEND and m.get("to_address") == to_address
               for c in m.get("amount", []) if c.get("denom") == DENOM)
    if paid < min_afet:
        return False
    used.add(tx_hash)
    return True


def fetch_get_tx(tx_hash: str) -> dict | None:
    """Blocking Fetch mainnet query -> {"code", "memo", "messages"}. None means not found or chain unreachable
    (retryable); anything else raises."""
    import grpc
    from cosmpy.aerial.client import LedgerClient, NetworkConfig
    from cosmpy.protos.cosmos.bank.v1beta1 import tx_pb2  # noqa: F401 (registers MsgSend for Any decoding)
    from cosmpy.protos.cosmos.tx.v1beta1.service_pb2 import GetTxRequest
    from google.protobuf.json_format import MessageToDict
    try:
        # ponytail: new client per query; cache one if payment volume ever matters
        resp = LedgerClient(NetworkConfig.fetchai_mainnet()).txs.GetTx(GetTxRequest(hash=tx_hash))
    except grpc.RpcError:  # NOT_FOUND (not indexed yet) or UNAVAILABLE
        return None
    d = MessageToDict(resp, preserving_proto_field_name=True)
    body = d.get("tx", {}).get("body", {})
    return {"code": int(d.get("tx_response", {}).get("code", 0)),
            "memo": body.get("memo", ""), "messages": body.get("messages", [])}
