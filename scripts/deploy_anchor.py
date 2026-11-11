#!/usr/bin/env python3
"""Deploy ReceiptAnchor to the test ledger, and print its address. Safe to run twice."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
RPC = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8545"
#: The same DEV-ONLY operator key as docker-compose.ledger.yml.
DEV_KEY = "0x7d1f0f3c6d6a4e7ba13c5a0ad1f1b6c0b4a1a3c9f6e24f7e8d5b9c1a2e3f4a5b"


def main() -> None:
    artifact = json.loads((ROOT / "contracts" / "ReceiptAnchor.json").read_text())
    web3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 10}))
    for _ in range(60):
        if web3.is_connected() and web3.eth.block_number > 0:
            break
        time.sleep(2)
    else:
        sys.exit(f"the ledger at {RPC} is not producing blocks")

    account = web3.eth.account.from_key(DEV_KEY)
    if web3.eth.get_transaction_count(account.address) > 0:
        address = web3.to_checksum_address(
            web3.keccak(b"\xd6\x94" + bytes.fromhex(account.address[2:]) + b"\x80")[12:].hex()
        )
        print(address)
        return

    contract = web3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    transaction = contract.constructor().build_transaction({
        "from": account.address, "gasPrice": 0, "gas": 1_000_000,
        "nonce": 0, "chainId": web3.eth.chain_id,
    })
    sent = web3.eth.send_raw_transaction(account.sign_transaction(transaction).raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(sent, timeout=60)
    if receipt["status"] != 1:
        sys.exit("contract deployment reverted")
    print(receipt["contractAddress"])


if __name__ == "__main__":
    main()
