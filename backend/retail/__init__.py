"""
The Saudi retail product.

One canonical analytical domain — `retail_cockpit`, shown as "Cockpit Data" —
holding a wide, joined, facility-level month-end dataset. Cockpit, Early
Warning and What-If all read that same table, so the exposure, stage and ECL
totals they quote are the same numbers by construction rather than by
coincidence.

Everything under here is SYNTHETIC. It describes no ANB customer, no ANB model
and no ANB policy, and nothing in it is approved by anyone.
"""

from backend.retail.config import RetailDemoConfig, load_config  # noqa: F401

DOMAIN_ID = "retail_cockpit"
DOMAIN_DISPLAY = "Cockpit Data"
CANONICAL_DATASET = "retail_facility_month"

#: The disclosure that travels with every figure this product shows.
SYNTHETIC_DISCLOSURE = (
    "Synthetic Saudi retail demonstration data — not ANB customer data or "
    "approved models."
)
