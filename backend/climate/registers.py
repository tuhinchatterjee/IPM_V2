"""
The audit trail carried over from the workbook: source register, assumption
register and verification log.

These are documentation, not inputs — nothing here feeds a calculation. They are
kept in code (rather than prose in a document) so the UI can render a status badge
next to every number and the export pack can ship the provenance with the result,
which is the whole ethos of the model.

`status` vocabulary: VERIFIED, PART VERIFIED, TO VERIFY, UNVERIFIED, PLAUSIBLE,
CORRECTED, RESOLVED, IDENTIFIED, DERIVED, JUDGEMENT, ASSUMPTION, INPUT, SAMPLE,
SOURCED, PLACEHOLDER, FLAGGED, OPEN.
"""

# ------------------------------------------------------------- source register
# (id, value, model location, source, note, status)

SOURCE_REGISTER = [
    (1, "NGFS quadrant mapping and warming", "Scenarios", "NGFS Phase V, Scenarios at a glance",
     "All four warming figures match the source.", "VERIFIED"),
    (2, "NGFS shadow carbon price", "Scenarios · carbon price", "NGFS Phase V, IIASA Scenario Explorer",
     "US$2010/tCO2, global weighted. Net Zero 2035 verified at 294. Other cells chart-read.", "PART VERIFIED"),
    (3, "Transition GDP deviation", "Scenarios · GDP deviation", "NGFS Phase V, NiGEM NGFS v1.23.2",
     "Net Zero and Delayed Transition plausible against the published chart and corroborated by ECB "
     "OP 281. Fragmented World unverifiable.", "PART VERIFIED"),
    (4, "US GDP deflator", "Settings · us_gdp_deflator", "US Bureau of Economic Analysis",
     "Implicit price deflator for GDP, target year over 2010.", "TO VERIFY"),
    (5, "Oman sector GVA", "Sectors · gva_omr",
     "UN SNA Table 2.4, Oman, value added by industry at basic prices, 2023 current prices",
     "Sums exactly to 41,963.9 OMR m; net of FISIM and taxes this gives 40,716.9, matching published "
     "2023 GDP of about RO 40.7bn.", "VERIFIED"),
    (6, "Split of ISIC B", "Sectors S02 / S03", "NCSI GDP by economic activity",
     "Non-oil Mining 205.8 OMR m (2023). Residual is oil and gas extraction.", "VERIFIED"),
    (7, "Oman sector emissions", "EDGAR categories · MtCO2e", "EDGAR, as entered in the v2 workbook",
     "All-gas CO2e, Scope 1, territorial, 2024. Buildings figure flagged as implausible.", "TO VERIFY"),
    (8, "Oman national total GHG", "Settings · national_total_ghg_mt", "EDGAR",
     "132.27 MtCO2e, about 25 tCO2e per head. High but consistent with Oman's position among the "
     "highest per-capita emitters.", "PLAUSIBLE"),
    (9, "EDGAR to sector allocation shares", "EDGAR categories · shares", "Analyst judgement",
     "Four rows carry judgement: industrial combustion, transport, buildings, and the residual. Replace "
     "with an EDGAR sub-sector download or an ISIC-basis account from Eora, EXIOBASE or GTAP.", "JUDGEMENT"),
    (10, "Pass-through by sector", "Sectors · pass_through",
     "Analyst judgement on trade exposure, informed by Cludius et al. (2020), Sijm et al. (2006), "
     "Alexeeva-Talebi (2011)",
     "Rationale recorded per sector. Base rate 45% for an unassessed sector.", "JUDGEMENT"),
    (11, "macro_beta", "Sectors · macro_beta", "Bank input, default 1.00",
     "Differentiation needs sector-level default history.", "INPUT"),
    (12, "EU median firm baseline PD", "Calibration · baseline_pd", "ECB OP 281, Chart 31 panel b",
     "Median-firm series runs 1.9% to 2.4% over 2020-2050.", "VERIFIED"),
    (13, "EU median firm PD response", "Calibration · anchor A / B", "ECB OP 281, Section 5.3",
     "+0.5% relative transition-only; +2.5% relative disorderly at 2050. Both are relative changes, "
     "not percentage points.", "VERIFIED"),
    (14, "EU carbon cost scope", "Calibration", "ECB OP 281, Section 5.1",
     "Flat carbon tax on Scope 1 direct emissions into operating expenses; Scope 3 drives revenues "
     "separately.", "VERIFIED"),
    (15, "EU pass-through", "Calibration · eu_pass_through", "ECB OP 281, Section 5.1",
     "Zero: no cost relief in the ECB cost channel.", "VERIFIED"),
    (16, "EU27 total GHG and GVA", "Calibration · route 1",
     "European Environment Agency; Eurostat nama_10_a10",
     "Inputs for the symmetric intensity route. Match the two reporting years.", "TO VERIFY"),
    (17, "Median to average intensity ratio", "Calibration · route1.median_to_average",
     "ECB OP 281, Chart 12",
     "Micro about 600 and large about 1,100 tCO2e/EURm; large firms produce about 90% of emissions.",
     "DERIVED"),
    (18, "Anchor carbon price", "Calibration · anchor_price_usd", "Assumption",
     "The ECB exercise uses NGFS PHASE I scenarios, so a Phase I orderly-transition price is required, "
     "not a Phase V price.", "ASSUMPTION"),
    (19, "Oman NPL ratio 2014-2024", "Macro · observations",
     "As entered in v2, no citation recorded",
     "Trace to the CBO Annual Report or Financial Stability Report.", "UNVERIFIED"),
    (20, "Oman real GDP growth", "Macro · observations", "Economist Intelligence Unit, series DGDP",
     "Source and extract date present in the v2 file.", "VERIFIED"),
    (21, "Selected regression coefficients", "Macro · beta", "Estimated live on the observations",
     "Reproduced by the engine on every run; quality check 13 confirms agreement.", "VERIFIED"),
    (22, "Master rating scale", "Rating grades", "Illustrative sample",
     "Replace with the bank's master scale — no code change required.", "SAMPLE"),
    (23, "OMR / USD peg", "Settings · currency_peg", "Central Bank of Oman",
     "Fixed at 2.6008 since 1986.", "VERIFIED"),
    (24, "Emissions intensity and denominator indices", "Scenarios · indices", "Bank input, default 1.00",
     "Switching them on requires no formula change downstream.", "INPUT"),
    (25, "Oman cyclone damage record", "Cyclone events",
     "Fritz et al. (2010) via IWA Water Practice & Technology 17(12); Haggag & Badry (2012); "
     "Government of Oman estimate cited in Al-Manji (2022)",
     "Three independent sources put Gonu at US$4.0 to 4.2bn. Together the three events give a directly "
     "sourced baseline annual average loss.", "VERIFIED"),
    (26, "Baseline AAL, heat and water stress", "Hazards H2 / H3", "Analyst input",
     "No public Oman-specific figure exists. Replace with NGFS Phase V acute damages by hazard for the "
     "Middle East region.", "INPUT"),
    (27, "Warming elasticities by hazard", "Hazards · elasticity", "Analyst judgement",
     "2.0 / 3.0 / 1.5. Cyclone damage scales with storm intensity; heat-related labour loss is strongly "
     "convex; water stress is less elastic because Oman is already at the extreme.", "JUDGEMENT"),
    (28, "Sector exposure weights", "Exposure · raw weights",
     "Analyst judgement, grounded in the Gonu and Shaheen damage pattern",
     "Normalised so the value-added-weighted mean is exactly 1.00, which preserves the national loss "
     "total whatever weights are entered.", "JUDGEMENT"),
    (29, "Insurance recovery and P&L share", "Hazards", "Analyst judgement",
     "25% recovery, 60% of retained loss to P&L. The 60/40 split is what keeps the PD and LGD channels "
     "from double counting the same damage.", "JUDGEMENT"),
    (30, "Warming at the horizon", "Derived · warming path",
     "NGFS Phase V, Scenarios at a glance (2100 values only)",
     "Straight-line interpolation between today and 2100. Replace with the MAGICC temperature path.",
     "PLACEHOLDER"),
]

SOURCE_REGISTER_ROWS = [
    dict(id=r[0], value=r[1], location=r[2], source=r[3], note=r[4], status=r[5])
    for r in SOURCE_REGISTER
]

# --------------------------------------------------------- assumption register
# (id, assumption, location, value/status, rationale and limitation)

ASSUMPTION_REGISTER = [
    ("A01", "Pure probit shift", "Grid", "N(N-1(PD0)+push+macro)",
     "Returns PD0 exactly at zero stress. The conditional-Vasicek form used in v2 maps an unconditional "
     "PD to a conditional PD and returns values BELOW baseline at zero stress."),
    ("A02", "Asset correlation rho is not used in the PD channel", "n/a", "Removed",
     "Basel CRE31.5 correlations are prudential parameters for a 99.9% capital quantile, not empirical "
     "asset correlations for scenario translation. Not required under a probit shift."),
    ("A03", "Acute physical risk only; no chronic channel", "Whole model", "Design",
     "No customer layer, no ECL, no LGD. Chronic physical risk through the macro channel is excluded."),
    ("A04", "Denominator is GVA", "Settings · denominator_basis", "GVA on both sides",
     "Oman publishes value added by activity but not turnover. Switch to TURNOVER and the EU side "
     "converts with it, so the two never sit on different bases."),
    ("A05", "EU intensity built symmetrically", "Calibration · route 1", "Route 1",
     "EU national Scope 1 emissions over EU GVA, exactly as the Oman intensity is built, so the turnover "
     "conversion never enters."),
    ("A06", "Median to average intensity ratio", "Calibration · route1.median_to_average", "0.57",
     "From OP 281 Chart 12. Without it the calibration would attribute the emissions of the largest firms "
     "to the median one."),
    ("A07", "k transfers from the EU to Oman unchanged", "Calibration · k", "Applied to Oman cost ratios",
     "Holding the cost ratio constant, the probit PD response to a cost shock is assumed the same in both "
     "economies. Not testable on Omani data. The largest transfer assumption in the model."),
    ("A08", "k is a scale, not a shape", "Calibration", "Curvature imposed",
     "One anchor pair identifies a multiplier only. Three or more anchors would give the curvature support."),
    ("A09", "Anchor carbon price vintage", "Calibration · anchor_price_usd", "Assumption",
     "The ECB exercise uses NGFS Phase I, so a Phase I price is required. v2 paired the ECB PD response "
     "with a Phase V price."),
    ("A10", "No abatement response", "Transition cost", "Full current emissions charged",
     "The NGFS shadow price is a marginal abatement cost, not a tax bill. Conservative."),
    ("A11", "Static intensity and denominator", "Scenarios · indices", "Both indices 1.00",
     "The two omissions bias the cost ratio in opposite directions and do not reliably cancel."),
    ("A12", "Households and own-account excluded", "EDGAR · HH column", "Excluded",
     "Private vehicle use and residential building energy are not attributable to a corporate borrower."),
    ("A13", "Pass-through on trade exposure", "Sectors · pass_through", "5% to 80%",
     "Base rate 45%. Utilities at 80% implies the cost lands on the sovereign, so their residual risk "
     "becomes sovereign-linked, which this model does not capture."),
    ("A14", "macro_beta 1.00 for every sector", "Sectors · macro_beta", "1.00",
     "Government-dependent sectors would normally exceed 1.00 because they transmit the fiscal cycle."),
    ("A15", "Macro beta estimated in first differences", "Macro · beta", "-0.952",
     "Only form with acceptable residual behaviour, and it maps a GDP LEVEL deviation onto the probit "
     "correctly by construction."),
    ("A16", "Correlation is the exposed lever", "Macro · correlation_in_use", "-0.5291",
     "beta = correlation x sd(D probit NPLR) / sd(GDP growth). The standard deviations are estimated "
     "adequately on ten observations; the correlation is not (p = 0.116)."),
    ("A17", "Only the deviation enters", "Macro shift", "Deviation only",
     "The regression intercept and any baseline growth assumption cancel."),
    ("A18", "Gross NPL ratio proxies the default rate", "Macro · observations", "Stock proxy for a flow",
     "The 2020 observation is a write-off-policy artefact. Replacing it with a default flow rate is the "
     "highest-value single improvement."),
    ("A19", "Headline GDP growth is the regressor", "Macro · observations", "EIU real GDP",
     "Non-oil GDP and Brent fit better but NGFS produces a TOTAL GDP deviation, so either would need a "
     "bridge equation."),
    ("A20", "Some overlap between the push and the macro leg", "Calibration / macro", "Accepted",
     "ECB stressed PDs already embed the macro response to carbon pricing. At current values the macro "
     "leg is small relative to the push."),
    ("A21", "Current Policies transition deviation is zero", "Scenarios · CP", "0.0%",
     "Correct by construction. Its physical damage, the dominant risk in that scenario, is only partly "
     "modelled (acute only)."),
    ("A22", "Master scale PDs treated as point-in-time", "Rating grades", "Assumed PIT",
     "If the scale is TTC a TTC-to-PIT step is needed before the shift. UNRESOLVED."),
    ("A23", "No hydrocarbon export revenue or fiscal channel", "Not modelled", "OPEN",
     "Oman's dominant transition exposure is loss of oil and gas export revenue and the fiscal contraction "
     "that follows, not a domestic carbon tax. Largest known gap."),
    ("A24", "GVA and emissions differ by one year", "Sectors / EDGAR", "OPEN",
     "GVA 2023, emissions 2024. Replacement 2024 GVA values are in the verification log."),
    ("A25", "Curvature parameter theta", "Settings · theta", "0.00 (logarithmic)",
     "push = k x ((1+x)^theta - 1)/theta, with LN(1+x) at theta = 0. The ECB anchors cannot identify theta "
     "because both sit in the near-linear region. Held at 0, with the full band reported."),
    ("A26", "Cost ratio cap", "Settings · cost_ratio_cap", "999 (off)",
     "Wired but not applied. Since curvature above the calibration range cannot be estimated, a cap is the "
     "only mechanism that bounds the result for utilities and manufacturing."),
    ("A27", "Coal anchor excluded from the fit", "Calibration · anchors 3-4", "Excluded, used as a check",
     "OP 281 states the coal-mining PD response is driven mainly by the need to fund abatement of very high "
     "Scope 3 emissions, which raises leverage. A different mechanism from the Scope 1 operating cost."),
    ("A28", "Physical risk enters PD as a second cost ratio", "Total cost ratio",
     "Added INSIDE the push transform",
     "push = k x g(transition cost ratio + physical cost ratio). Adding two separate pushes would "
     "understate the joint effect of facing both shocks at once, because the transform is concave."),
    ("A29", "k is reused for the physical push", "Push", "Same k as transition",
     "k maps a cost expressed as a share of value added into a probit PD shift. A dollar of flood damage "
     "hits the income statement the same way a dollar of carbon cost does."),
    ("A30", "Physical damage is converted to an annual P&L flow", "Hazards · pnl_share",
     "60% of retained loss",
     "The carbon cost ratio is an annual flow against annual value added, so the physical cost ratio must "
     "be too."),
    ("A31", "Channel separation between PD and LGD", "Hazards · pnl_share", "60% PD / 40% LGD",
     "The PD channel takes business interruption and repair expense; the LGD channel takes capital "
     "replacement and collateral loss. The two shares sum to one, so the same damage is never charged twice. "
     "The 40% remainder is left addressable for a future LGD module."),
    ("A32", "Chronic physical risk is NOT modelled", "Not modelled", "OPEN",
     "Only ACUTE physical risk is included. Chronic damages are the dominant physical channel in NGFS. "
     "Excluding them means Current Policies still looks benign here when it is not."),
    ("A33", "Exposure weights are relative, not absolute", "Exposure", "Normalised to a mean of 1.00",
     "They redistribute the national annual average loss across sectors without changing its total, so an "
     "error in the weights misallocates risk between sectors but cannot inflate system-wide risk."),
]

ASSUMPTION_REGISTER_ROWS = [
    dict(id=r[0], assumption=r[1], location=r[2], value=r[3], rationale=r[4])
    for r in ASSUMPTION_REGISTER
]

# ------------------------------------------------------------ verification log
# (id, value, value now in model, source checked against, finding, status)

VERIFICATION_LOG = [
    (1, "NGFS shadow carbon price, Net Zero 2050, 2035", "US$2010 294 /tCO2",
     "NGFS Phase V main report, Main results, Carbon prices",
     "The report states a price of about $300/tCO2 is needed by 2035 for net zero by 2050, rising from "
     "$98/tCO2 in 2025 to $294/tCO2. The workbook carried 290. Changed to 294.", "CORRECTED"),
    (2, "Units of the NGFS carbon price", "US$2010",
     "NGFS Phase V, Scenarios at a glance and Main results, chart axes",
     "Both carbon price charts are labelled US$2010 per tCO2. A price deflator is now applied explicitly. "
     "Omitting it understated every cost ratio by roughly a quarter.", "CORRECTED"),
    (3, "Regional applicability of the carbon price", "Global weighted",
     "NGFS Phase V, Main results, Carbon prices, footnote",
     "Published prices are weighted global values. The footnote states prices tend to be LOWER in emerging "
     "economies, so applying the global path to Oman biases the transition cost UPWARDS.",
     "VERIFIED, conservative bias documented"),
    (4, "End-of-century warming by scenario", "NZ 1.4, DT 1.7, FW 2.4, CP 3.0",
     "NGFS Phase V, Scenarios at a glance", "All four match the source exactly.", "VERIFIED"),
    (5, "Transition GDP deviation, Net Zero and Delayed Transition",
     "NZ -1.5 / -1.0 / -0.8; DT -0.3 / -2.0 / -1.7",
     "NGFS Phase V GDP decomposition chart; ECB OP 281 Section 3.2.1",
     "The published chart gives the transition component graphically, not as a table, so exact values "
     "cannot be read off. Magnitudes and shape are consistent. ECB OP 281 independently states the "
     "transition-risk impact is limited to no more than 2% of European GDP under a disorderly transition.",
     "PLAUSIBLE, not exact"),
    (6, "Transition GDP deviation, Fragmented World", "0.0 in every year",
     "NGFS Phase V GDP decomposition chart",
     "Fragmented World is NOT plotted in the published chart. No public figure exists. A zero deviation is "
     "not credible for a high-cost, badly co-ordinated transition. Requires the IIASA portal pull.",
     "UNVERIFIABLE - action required"),
    (7, "Transition GDP deviation, Current Policies", "0.0 in every year", "NGFS scenario design",
     "Correct by construction. Current Policies is the transition baseline and carries no additional "
     "transition cost. Its risk is physical.", "VERIFIED"),
    (8, "EU anchor: median firm baseline PD", "2.0%", "ECB OP 281, Chart 31 panel b, right-hand axis",
     "The median-firm series runs from about 1.9% in 2020 to about 2.4% by 2050. A 2020 baseline of 2.0% "
     "is supported.", "VERIFIED"),
    (9, "EU anchor: median firm PD response", "+0.5% RELATIVE (transition-only)",
     "ECB OP 281, Section 5.3",
     "Section 5.3 states the median firm would have a PD about 0.5% higher under orderly transition during "
     "the policy implementation phase compared with hot house world. Chart 28 confirms these are percentage "
     "CHANGES, not percentage points. So 2.00% becomes 2.01%.", "VERIFIED and corrected"),
    (10, "Origin of the 2.0% to 2.05% figure in the v2 sheet", "Not used as primary",
     "ECB OP 281, Section 5.3",
     "This is the +2.5% relative figure for DISORDERLY transition versus orderly at 2050. It mixes "
     "transition timing with residual physical effects. Retained as selectable Anchor B.", "IDENTIFIED"),
    (11, "Origin of the 2.0% to 4.0% figure in the v2 register", "Not used",
     "ECB OP 281, Section 5.4 and Chart 31",
     "This is COAL MINING (NACE B05), not the median firm. The register entry was a coal-mining anchor "
     "mislabelled as a median-firm anchor.", "RESOLVED"),
    (12, "Origin of the 20,000 t/$m intensity in the v2 register", "Not used", "ECB OP 281, Section 5.4",
     "A coal-mining SCOPE 3 figure, not a median-firm Scope 1 figure. The two v2 anchors were a "
     "self-consistent coal-mining pair, not a contradiction.", "RESOLVED"),
    (13, "Origin of the 1,100 t/EURm intensity in the v2 sheet", "Not used as stated",
     "ECB OP 281, Chart 12 and surrounding text",
     "1,100 tCO2e per EURm of revenue is the average for LARGE firms on a Scope 1+2+3 basis. Neither a "
     "median-firm figure nor a Scope 1 figure.", "CORRECTED"),
    (14, "Scope of the EU carbon cost channel", "Scope 1", "ECB OP 281, Section 5.1",
     "The carbon price reaches firms as a flat carbon tax on Scope 1 direct emissions. Confirms the Oman "
     "side should also use Scope 1, which it does.", "VERIFIED"),
    (15, "EU anchor pass-through", "0%", "ECB OP 281, Section 5.1",
     "The ECB applies the carbon tax to operating costs with no cost relief. v2 used 50%, inconsistent "
     "with how the anchor was generated.", "CORRECTED"),
    (16, "Median EU firm Scope 1 emission intensity", "Assumption, exposed",
     "ECB OP 281, Charts 12 and 13",
     "No median-firm Scope 1 figure is published anywhere in the paper. This is a required assumption; it "
     "is exposed with a full sensitivity grid for k.", "UNVERIFIABLE - assumption"),
    (17, "Carbon price paired with the EU anchor", "Assumption, exposed", "ECB OP 281, Section 3.1",
     "The ECB stress test uses NGFS PHASE I scenarios, not Phase V. v2 paired the ECB PD response with a "
     "Phase V NDC price of US$80.", "UNVERIFIABLE - assumption"),
    (18, "Oman sector GVA, reference year", "2023, current prices",
     "UN SNA Table 2.4 vs NCSI via Trading Economics",
     "The values match the NCSI series for 2023 exactly, NOT 2024. 2024 figures: agriculture 1,070.3, "
     "construction 2,760.6, manufacturing 4,149.0, utilities 1,004.3, transport 1,686.0, services 19,127.0. "
     "Emissions are 2024 EDGAR, so there is a ONE YEAR timing mismatch.",
     "CORRECTED to disclosure, replacement values supplied"),
    (19, "Split of ISIC B into oil and gas versus other mining", "98.6% / 1.4%",
     "NCSI GDP by activity via Trading Economics",
     "Non-oil Mining GVA is 205.8 OMR m for 2023. ISIC B total is 14,956.1, so oil and gas extraction is "
     "14,750.3. Replaces the 93% / 7% placeholder split used in v3.", "CORRECTED and now sourced"),
    (20, "Reconciliation of sector GVA to the national total", "41,963.9 OMR m", "UN SNA Table 2.4",
     "Sector GVA sums exactly to total value added at basic prices. Deducting FISIM of 1,013.9 and adding "
     "taxes less subsidies of -233.1 gives 40,716.9, matching published 2023 GDP.", "VERIFIED"),
    (21, "ISIC L (real estate), E (water and waste), N and R", "Absorbed, not itemised",
     "UN SNA Table 2.4",
     "Oman's submission does not itemise these sections, yet the table still reconciles to published GDP. "
     "Creating separate rows would have produced zero-GVA sectors — the v3 real-estate defect.",
     "VERIFIED and resolved"),
    (22, "Oman national total GHG", "132.27 MtCO2e", "EDGAR, as entered in the v2 workbook",
     "Not independently re-traced. Implies about 25 tCO2e per head against a population of 5.3 million.",
     "PLAUSIBLE, not re-traced"),
    (23, "EDGAR Buildings emissions for Oman", "22.23 MtCO2e", "Plausibility check only",
     "Implies about 4.2 tCO2e per head of DIRECT building fuel combustion, excluding electricity. High for "
     "a hot climate where building energy is overwhelmingly electric air conditioning. 70% is allocated to "
     "households so it does not distort corporate intensities.", "FLAGGED - re-download required"),
    (24, "Oman banking-system gross NPL ratio 2014-2024", "As in v2", "No citation existed in v2",
     "Not traced. Should come from the CBO Annual Report or Financial Stability Report.", "UNVERIFIED"),
    (25, "Oman real GDP growth 2014-2024", "EIU series DGDP", "Economist Intelligence Unit extract",
     "Source is recorded in the file and the extract date is present.", "VERIFIED"),
    (26, "OMR / USD peg", "2.6008", "Central Bank of Oman", "Fixed since 1986.", "VERIFIED"),
    (27, "EU anchor 2: high-emitting firms", "+2.0% relative, transition-only", "ECB OP 281 Section 5.4",
     "Transition costs raise high-emitting firms' PDs by 2% relative to a no-policy-action scenario in the "
     "short term, against 0.5% for median firms, in the same sentence. Same identification, same Scope 1 "
     "mechanism.", "VERIFIED"),
    (28, "EU anchors 3 and 4: coal mining", "+150% orderly, +100% disorderly", "ECB OP 281 Section 5.4",
     "Coal-mining PDs rise to 5.0% and 4.0% from a 2.0% base, driven mainly by Scope 3 abatement investment "
     "raising leverage. Retained as an out-of-sample check, not used to fit.", "VERIFIED, not fitted"),
    (29, "Curvature of the push function", "Not identifiable", "ECB OP 281, anchors 1 and 2",
     "Both anchors sit at cost ratios below 4% of value added, where every smooth functional form is "
     "indistinguishable from a straight line. The implied top-decile intensity multiple moves only from "
     "3.97 to 4.07 across the whole range from linear to saturating.", "UNVERIFIABLE - quantified"),
    (30, "Implied top-decile intensity multiple", "4.0x the median", "Derived from anchors 1 and 2",
     "A validation rather than an identification: a top-decile-to-median ratio of about 4 is entirely "
     "plausible, so the anchors are consistent with the functional form in use.", "DERIVED"),
    (31, "Oman real GDP growth series", "EIU", "Confirmed by the user as sourced from the EIU",
     "EIU supplies the HISTORICAL series used to estimate the macro leg. It cannot supply the NGFS scenario "
     "GDP deviations, which are NiGEM model output and a different object.", "VERIFIED"),
    (32, "Oman cyclone damage record",
     "Gonu US$4,200m (2007), Phet US$700m (2010), Shaheen US$500m (2021)",
     "Fritz et al. (2010); Haggag & Badry (2012); Al-Manji (2022)",
     "Three independent sources put Gonu at US$4.0 to 4.2bn. Shaheen's official government figure is about "
     "US$500m, notably lower than initial insurer fears.", "VERIFIED"),
    (33, "Cyclone frequency in Oman", "Roughly every 3 to 4 years",
     "IWA Water Practice & Technology 17(12)",
     "Intense storms strike Oman every three or four years between June and October. An 18-year window "
     "containing three major events is consistent with that.", "VERIFIED"),
    (34, "Baseline AAL, tropical cyclone and flood", "0.275% of national GVA per year",
     "Computed from the event record",
     "A FLOOR, not a full estimate. It counts only the three largest recorded events, omits smaller wadi "
     "flash floods and the April 2024 rainfall episode, omits all indirect losses, and does not deflate "
     "nominal damages. Every omission pushes the true figure up.", "SOURCED, conservative"),
    (35, "Baseline AAL, extreme heat and water stress", "0.30% and 0.10% of GVA", "Analyst input",
     "No public Oman-specific figure exists. Replace with NGFS Phase V acute damages, hazards heatwaves "
     "and drought, Middle East region.", "INPUT - not sourced"),
    (36, "Warming at the horizon by scenario", "Interpolated",
     "NGFS Phase V, Scenarios at a glance (2100 values only)",
     "Only end-of-century warming is published. Warming at 2040 or 2050 requires the MAGICC path. The "
     "straight-line interpolation used here is transparent but crude, and it is the weakest input in the "
     "physical module.", "PLACEHOLDER"),
    (37, "Warming elasticities by hazard", "2.0 / 3.0 / 1.5", "Analyst judgement",
     "Cyclone damage scales with storm intensity, which enters damage functions at a high power. "
     "Heat-related labour loss is strongly convex once wet-bulb thresholds are approached. Water stress is "
     "less elastic because Oman is already at the extreme of the scale.", "JUDGEMENT"),
    (38, "Sector exposure weights", "30 weights across 3 hazards",
     "Analyst judgement, grounded in the Gonu and Shaheen damage pattern",
     "Normalised so that the value-added-weighted mean is exactly 1.00, which preserves the national loss "
     "total whatever weights are entered. Replace with geolocated collateral and site data if held.",
     "JUDGEMENT"),
    (39, "Insurance recovery and P&L share", "25% recovery, 60% of retained loss to P&L",
     "Analyst judgement",
     "Oman's non-life insurance penetration is low and catastrophe cover is not universal. The 60/40 split "
     "is what keeps the PD and LGD channels from double counting the same damage.", "JUDGEMENT"),
]

VERIFICATION_LOG_ROWS = [
    dict(id=r[0], value=r[1], value_now=r[2], source=r[3], finding=r[4], status=r[5])
    for r in VERIFICATION_LOG
]


def status_tone(status: str) -> str:
    """Map a register status onto the UI badge tone: ok / warn / bad / info."""
    s = (status or "").upper()
    if s.startswith("VERIFIED") or s in {"RESOLVED", "SOURCED", "CORRECTED", "PASS"}:
        return "ok"
    if s.startswith("UNVERIFIABLE") or s in {"UNVERIFIED", "OPEN", "FLAGGED", "PLACEHOLDER"}:
        return "bad"
    if s in {"TO VERIFY", "TO_VERIFY", "PLAUSIBLE", "PART VERIFIED", "JUDGEMENT", "ASSUMPTION",
             "INPUT", "SAMPLE"} or s.startswith("PLAUSIBLE"):
        return "warn"
    return "info"
