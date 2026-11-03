from typing import Callable

PRICE_AFET = 500000000000000000  # 0.5 TEST FET
DENOM = "atestfet"
MSG_SEND = "/cosmos.bank.v1beta1.MsgSend"


def verify_fet_payment(tx_hash: str, to_address: str, min_afet: int,
                       get_tx: Callable[[str], dict | None], used: set[str]) -> bool:
    """True once per hash: a successful tx paying >= min_afet atestfet to to_address.
    Synchronous on purpose: the `used` check and add can't interleave with another job."""
    if tx_hash in used:
        return False
    tx = get_tx(tx_hash)
    if not tx or tx.get("code", 0) != 0:
        return False
    paid = sum(int(c["amount"]) for m in tx.get("messages", [])
               if m.get("@type") == MSG_SEND and m.get("to_address") == to_address
               for c in m.get("amount", []) if c.get("denom") == DENOM)
    if paid < min_afet:
        return False
    used.add(tx_hash)
    return True


def dorado_get_tx(tx_hash: str) -> dict | None:
    """Blocking Dorado query -> {"code", "messages"}; None if missing or unreachable."""
    from cosmpy.aerial.client import LedgerClient, NetworkConfig
    from cosmpy.protos.cosmos.bank.v1beta1 import tx_pb2  # noqa: F401 (registers MsgSend for Any decoding)
    from cosmpy.protos.cosmos.tx.v1beta1.service_pb2 import GetTxRequest
    from google.protobuf.json_format import MessageToDict
    try:
        # ponytail: new client per query; cache one if payment volume ever matters
        resp = LedgerClient(NetworkConfig.fetchai_stable_testnet()).txs.GetTx(GetTxRequest(hash=tx_hash))
        d = MessageToDict(resp, preserving_proto_field_name=True)
    except Exception:  # not found, network, decode: all mean "not verified"
        return None
    return {"code": int(d.get("tx_response", {}).get("code", 0)),
            "messages": d.get("tx", {}).get("body", {}).get("messages", [])}
