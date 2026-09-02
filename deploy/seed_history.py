#!/usr/bin/env python3
"""
Give the public demo a history, so it has something to show the moment it opens.

An empty dashboard is a worse demo than no dashboard: a reviewer opens it, sees zero
correlations, and cannot tell an empty system from a broken one. This seeds three
institutions with synthetic incidents spread over the past weeks, including two
genuine cross-firm campaigns, so the first screen shows the product working.

Everything here is SYNTHETIC. No UAE open dataset publishes cyber incidents broken
down by financial-sector entity — that absence is the gap MARSAD exists to fill — and
inventing plausible-looking real incidents would be worse than admitting it. The
indicators are RFC 5737 / RFC 3849 documentation ranges and .example domains, so
nothing here can be mistaken for a real observable or accidentally block real traffic.

Run it against the deployed connectors, not the core: incidents enter through an
institution, get extracted, confirmed and redacted, and only then cross. Seeding the
core directly would bypass the boundary and produce a history the architecture could
not have generated.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

# Documentation-range indicators only. TEST-NET-1/2/3 and .example are reserved and
# unroutable, so a copied token can never correspond to a real host.
#
# Every narrative carries at least one IP from those ranges, deliberately. The
# extractor's domain vocabulary is a closed list of real TLDs and does not include the
# reserved `.example`, so a narrative whose only indicator is an .example domain
# produces no token — and A3 then refuses the submission outright, because a payload
# carrying only coarse metadata about an institution would leak posture while adding
# nothing. That refusal is correct and is left alone; the seeder supplies an
# extractable indicator instead of widening production's vocabulary to suit a demo.
CAMPAIGN_SSO = {
    "domain": "sso-verify-portal.example",
    "ip": "198.51.100.44",          # TEST-NET-2
}
CAMPAIGN_INVOICE = {
    "domain": "invoice-settlement.example",
    "ip": "203.0.113.77",           # TEST-NET-3
}

INSTITUTIONS = {
    "almaha": {"port": 8101, "jurisdictions": ["ADGM_FSRA", "CBUAE"]},
    "gulfsec": {"port": 8102, "jurisdictions": ["DFSA", "CMA"]},
    "emcap": {"port": 8103, "jurisdictions": ["CBUAE", "CMA"]},
}

#: (institution, days ago, narrative). Two campaigns are shared across firms on
#: purpose: without a shared indicator or shared tradecraft there is no correlation to
#: show, and a demo of a correlation engine with nothing correlated is not a demo.
HISTORY: list[tuple[str, int, str]] = [
    # --- campaign 1: one attacker, three firms, shared infrastructure -----------
    ("almaha", 21,
     f"Finance staff received a credential-harvesting email impersonating the internal "
     f"SSO portal at {{ts}}. Two users submitted credentials at "
     f"https://{CAMPAIGN_SSO['domain']}/portal hosted on {CAMPAIGN_SSO['ip']}. The "
     f"online banking service was unavailable for 40 minutes. Severity: HIGH."),
    ("gulfsec", 20,
     f"Client services mailbox compromised after a phishing message referencing "
     f"{CAMPAIGN_SSO['domain']}. Source address {CAMPAIGN_SSO['ip']}. A forwarding rule "
     f"was created on the affected mailbox. Detected at {{ts}}. Severity: HIGH."),
    ("emcap", 19,
     f"Portfolio team targeted by a lookalike login page at "
     f"https://{CAMPAIGN_SSO['domain']}/login, detected {{ts}}. Credentials were "
     f"submitted by one user before the page was blocked. The client portal was "
     f"unaffected. Severity: MEDIUM."),

    # --- campaign 2: rotated infrastructure, same tradecraft -------------------
    ("gulfsec", 12,
     f"Business email compromise: a supplier invoice was redirected after a phishing "
     f"message from {CAMPAIGN_INVOICE['domain']} at {{ts}}, sent from "
     f"{CAMPAIGN_INVOICE['ip']}. Mailbox forwarding rules were created on the finance "
     f"mailbox. The payment gateway was frozen. Severity: CRITICAL."),
    ("emcap", 11,
     f"Invoice fraud attempt detected {{ts}}. Attacker used {CAMPAIGN_INVOICE['ip']} and "
     f"created a forwarding rule on a finance mailbox. No funds were transferred. "
     f"Severity: HIGH."),

    # --- unrelated single-firm incidents, so not everything correlates ---------
    ("almaha", 8,
     "A volumetric denial-of-service attack hit the trading platform at {ts}, "
     "saturating the link for 25 minutes. Source traffic came largely from "
     "192.0.2.101. No data was lost and the incident was contained quickly. "
     "Severity: MEDIUM."),
    ("emcap", 5,
     "رصد فريق الأمن رسالة تصيد استهدفت منصة التداول في {ts} من العنوان "
     "192.0.2.202. تم إرسال البيانات إلى phish-ar.example. الأثر: عالي."),
    ("gulfsec", 3,
     "A departing employee copied client records to a personal drive at {ts}, "
     "transferred via 192.0.2.55. Data was copied from the custody platform. "
     "Contained immediately; low impact confirmed. Severity: LOW."),
]


def seed(base_url_for, analyst: str, dry_run: bool) -> int:
    submitted = 0
    now = datetime.now(timezone.utc)

    for institution, days_ago, template in HISTORY:
        detected = (now - timedelta(days=days_ago)).replace(minute=0, second=0, microsecond=0)
        narrative = template.format(ts=detected.strftime("%Y-%m-%d %H:%M UTC"))
        base = base_url_for(institution)

        if dry_run:
            print(f"[dry-run] {institution:8} {days_ago:>2}d ago  {narrative[:70]}…")
            continue

        with httpx.Client(base_url=base, timeout=120) as client:
            extracted = client.post("/v1/intake/extract", json={"narrative": narrative})
            extracted.raise_for_status()
            draft = extracted.json()["draft"]

            # Model-proposed indicators require explicit confirmation before they can be
            # tokenised — see CLAUDE.md. The seeder is the "analyst" here and accepts
            # what extraction located in the text.
            edits = {}
            if draft.get("requires_indicator_confirmation"):
                edits["indicators"] = draft["fields"]["indicators"]["value"] or []

            confirmed = client.post(
                f"/v1/intake/{draft['draft_id']}/confirm",
                json={"analyst": analyst,
                      "jurisdictions": INSTITUTIONS[institution]["jurisdictions"],
                      "edits": edits},
            )
            confirmed.raise_for_status()
            incident_id = confirmed.json()["incident_id"]

            result = client.post(f"/v1/incidents/{incident_id}/submit")
            if result.status_code != 200:
                print(f"  ! {institution}: submit returned {result.status_code} "
                      f"{result.text[:120]}", file=sys.stderr)
                continue

            payload = result.json()["payload_sent"]
            print(f"{institution:8} {days_ago:>2}d ago  tokens={len(payload['tokens']):<2} "
                  f"techniques={len(payload['technique_set'])}  {narrative[:46]}…")
            submitted += 1
            time.sleep(0.5)   # be gentle with a small VPS

    return submitted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--almaha", default="http://localhost:8101")
    parser.add_argument("--gulfsec", default="http://localhost:8102")
    parser.add_argument("--emcap", default="http://localhost:8103",
                        help="the remote VPS connector, e.g. https://c.marsad.example")
    parser.add_argument("--core", default="http://localhost:8000")
    parser.add_argument("--analyst", default="seed.operator")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    urls = {"almaha": args.almaha, "gulfsec": args.gulfsec, "emcap": args.emcap}
    count = seed(lambda name: urls[name], args.analyst, args.dry_run)

    if args.dry_run:
        return

    print(f"\nsubmitted {count}/{len(HISTORY)} incidents")
    correlations = httpx.get(f"{args.core}/v1/correlations", timeout=30).json()
    kinds: dict[str, int] = {}
    for correlation in correlations:
        kinds[correlation["kind"]] = kinds.get(correlation["kind"], 0) + 1
    print(f"core now reports {len(correlations)} correlation(s): "
          f"{json.dumps(kinds)}")
    if not correlations:
        print("! no correlations — the demo will open on an empty dashboard",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
