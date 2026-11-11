#!/usr/bin/env python3
"""
Key ceremony for one epoch: split a fresh token key across the custodians.

    python scripts/oprf_keygen.py --epoch 1 --threshold 2 --parties 3 --out deploy/oprf

Writes `custodian-N.json` (secret; deliver each to one custodian only and delete it from
this machine) and `public-keys.json` (the values every connector pins).

This is a trusted-dealer split. The key exists briefly in this process's memory and is
discarded when it exits, so run it on an offline machine with the custodians present.
Distributed key generation removes the dealer and is the planned upgrade.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from marsad_oprf.threshold import deal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--epoch", type=int, required=True)
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--parties", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    shares, public = deal(args.epoch, args.threshold, args.parties)
    for share in shares:
        path = args.out / f"custodian-{share.index}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(share.to_dict(), handle)
    (args.out / "public-keys.json").write_text(json.dumps(public.to_dict(), indent=2) + "\n")
    print(f"epoch {args.epoch}: {args.threshold}-of-{args.parties} shares written to {args.out}")


if __name__ == "__main__":
    main()
