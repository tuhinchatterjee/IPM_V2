"""
Opus360 — certification harness for the frozen CreditProbe AdvancedCockpit.

The harness OBSERVES the frozen architecture. It never modifies it. Every
module here lives outside the protected paths listed in `protected.py`, and
the protected manifest is verified before and after every live batch.
"""

HARNESS_VERSION = "opus360-harness-1.0.0"

FROZEN_TAG = "cockpit-round-h-live-pass-2026-09-23"
FROZEN_COMMIT = "245c50e45786c6e0c866b281f9dd74da17d160b5"
FROZEN_TAG_OBJECT = "aa589cafa650e1ffd12713e84f8ab919b84a28f9"

#: The frozen provider configuration, read from the Round H record
#: (docs/cockpit_v4/ROUND_H_LIVE_UAT.md, scripts/cockpit_v4/live_uat.py).
APPROVED_MODEL = "claude-opus-5"
APPROVED_PRICE_CARD = "config/cockpit_v4/price_card.claude-opus-5.json"
APPROVED_RELEASES = {"corporate": "v4-saudi-corporate-20q-v4",
                     "retail": "v4-saudi-retail-20m-v5"}
#: Byte fingerprints of the releases the Round H UAT approved
#: (docs/cockpit_v4/evidence/live_uat_dry_run.json).
APPROVED_FINGERPRINTS = {
    "corporate": "e37236d0f6d4e494fea0fe2f2b66b83085e76cb9eabdd2c2e2b95ea87a36750f",
    "retail": "a1e797dcc73236b7a0bdac3635712a912c5680a1b3c7de60f059c78d893706cb",
}
