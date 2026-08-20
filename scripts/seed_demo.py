"""
Drives the full scenario against running connectors — the same story as the
browser demo, but through the real services.

  make run          # in one terminal
  python scripts/seed_demo.py
"""
from __future__ import annotations

import json
import sys
import time

import httpx

CONNECTORS = {
    "Al Maha Bank": "http://localhost:8101",
    "Gulf Securities": "http://localhost:8102",
    "Emirates Capital": "http://localhost:8103",
}

INCIDENTS = {
    "Al Maha Bank": {
        "narrative": "Finance staff received a credential-harvesting email impersonating the internal SSO portal.",
        "analyst_notes": "Two users submitted credentials before the page was blocked.",
        "indicators": [
            {"type": "DOMAIN", "value": "sso-almaha-verify[.]com"},
            {"type": "IP", "value": "185.220.101.44"},
            {"type": "IBAN", "value": "AE07 0331 2345 6789 0123 456"},
        ],
        "techniques": ["T1566.002", "T1078", "T1114", "T1567"],
        "severity": "HIGH",
    },
    # same attacker IP -> exact correlation
    "Gulf Securities": {
        "narrative": "Client-services mailbox compromised; forwarding rule created to an external address.",
        "indicators": [
            {"type": "DOMAIN", "value": "gulfsec-clientlogin.net"},
            {"type": "IP", "value": "185.220.101.44"},
        ],
        "techniques": ["T1566.002", "T1078", "T1114", "T1565"],
        "severity": "HIGH",
    },
    # entirely different infrastructure, same tradecraft -> similarity only
    "Emirates Capital": {
        "narrative": "Portfolio team targeted by a lookalike login page on unrelated infrastructure.",
        "indicators": [
            {"type": "DOMAIN", "value": "emcap-portal-secure.io"},
            {"type": "IP", "value": "91.219.238.12"},
        ],
        "techniques": ["T1566.002", "T1078", "T1114", "T1567"],
        "severity": "MEDIUM",
    },
}


def main() -> int:
    with httpx.Client(timeout=15) as c:
        try:
            c.get("http://localhost:8000/health").raise_for_status()
        except httpx.HTTPError:
            print("core is not reachable on :8000 — run `make run` first")
            return 1

        for name, base in CONNECTORS.items():
            inc = INCIDENTS[name]
            iid = c.post(f"{base}/v1/incidents", json=inc).json()["incident_id"]
            print(f"\n=== {name} ===")
            print("stored locally (plaintext stays here)")

            preview = c.post(f"{base}/v1/incidents/{iid}/preview").json()
            print("payload that will cross the boundary:")
            print(json.dumps(preview, indent=2)[:900])

            res = c.post(f"{base}/v1/incidents/{iid}/submit").json()
            for corr in res["core_response"]["correlations"]:
                print(f"  >> CORRELATION {corr['kind']} "
                      f"peers={corr['peer_count']} "
                      f"similarity={corr['similarity']} "
                      f"aggregate_publishable={corr['publishable_as_aggregate']}")
            time.sleep(0.4)

        print("\n=== all correlations held by core ===")
        print(json.dumps(c.get("http://localhost:8000/v1/correlations").json(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
