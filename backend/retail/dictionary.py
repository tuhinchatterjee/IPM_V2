"""
What every governed field of `retail_facility_month` MEANS.

Three hundred and two of the book's five hundred and forty-six columns reached
the reader with no definition at all. What they carried instead was their own
business name, followed by a pointer into this repository:

    Account inflows 1m SAR. See docs/RETAIL_DATA_DICTIONARY.md.

Which is not a definition — it restates the column heading — and the document
it names is generated FROM this registry, so it said the same thing back. A
credit officer following the instruction arrived at the sentence they had just
read. And a bank's data steward does not have this repository: an internal
path is not somewhere a user can go.

It was not only prose. `spec_for` guessed a column's TYPE from its name, and a
name with no recognised suffix fell through to `string`. Forty-four numeric
columns were declared that way — `behavioural_score`, `application_score_at_
origination`, `bureau_score_current`, `lgd_base`, `ccf_base`, every point-in-
time PD scenario and every scenario weight. `_rollup_for` quite correctly
refuses to average a string and falls back to `max`, so

    "What is the average behavioural score at August 2026?"

was answered **754.59** — the HIGHEST score in the book, under the word
average. The right answer is 673.99. Nothing on the screen said which one had
been computed.

So every entry below carries the definition AND the type, the unit and the
aggregation semantics, and `tests/retail/test_ret_overnight_dictionary.py`
reconciles all three against the published Parquet rather than against this
file. A dictionary that disagrees with its own book is worse than none: it is
a wrong answer with a governance stamp on it.

Every figure here is SYNTHETIC demonstration data. No threshold, coefficient or
definition below is an ANB policy or a SAMA requirement.
"""

from __future__ import annotations

from typing import Any

from backend.retail.schema import (COUNT, DESCRIPTOR, EVENT_DATE, FLOW,
                                   IDENTIFIER, RATIO, STOCK)

CUSTOMER = "CUSTOMER"

#: name -> (data_type, unit, semantics, definition)
#:
#: `unit` is None where the figure has none. `semantics` decides how the
#: engine may aggregate it; see the table at the head of the generated
#: dictionary for what each one permits.
ENTRIES: dict[str, tuple[str, str | None, str, str]] = {

    # ---------------------------------------------------------- the customer
    "age_band": ("string", None, DESCRIPTOR,
        "The customer's age at this month-end, in bands. Banded rather than "
        "exact so an age cannot identify a person in a demonstration book."),
    "city": ("string", None, DESCRIPTOR,
        "The city of the customer's registered address."),
    "region": ("string", None, DESCRIPTOR,
        "The Saudi administrative region of the customer's address, as a code. "
        "`region_label` is the same thing written for a reader."),
    "region_label": ("string", None, DESCRIPTOR,
        "The Saudi administrative region of the customer's address, written "
        "the way it is shown on screen."),
    "residency_category": ("string", None, DESCRIPTOR,
        "Whether the customer is a Saudi citizen or a resident. It changes "
        "which affordability and tenor rules a product applies."),
    "customer_segment": ("string", None, DESCRIPTOR,
        "The bank's relationship segment — MASS, MASS_AFFLUENT, AFFLUENT or "
        "PRIVATE — set from income and holdings, not from credit quality."),
    "customer_scope": ("string", None, DESCRIPTOR,
        "The population this book covers: natural persons borrowing for "
        "themselves. It is one value everywhere, and it is the sentence that "
        "says why no company appears in this dataset."),
    "customer_tenure_months": ("integer", "months", STOCK,
        "Whole months since the customer's relationship with the bank began, "
        "measured to this month-end. A CUSTOMER attribute repeated on each of "
        "their facilities: averaging it across facility rows weights long "
        "relationships by how many products they hold."),
    "customer_relationship_start_date": ("date", None, EVENT_DATE,
        "The month-end on which the customer's first relationship with the "
        "bank opened. Earlier than the origination date of any one facility."),
    "dependants_band": ("string", None, DESCRIPTOR,
        "How many dependants the customer declared at origination, in bands. "
        "An input to the household expense floor, not to the score."),
    "income_band": ("string", None, DESCRIPTOR,
        "Verified monthly income at this month-end, in bands. Banded for "
        "grouping; `verified_monthly_salary_sar` carries the figure."),
    "indebtedness_band": ("string", None, DESCRIPTOR,
        "Total monthly credit obligations as a share of verified income, in "
        "bands — the debt burden ratio a reader groups by."),
    "employment_status": ("string", None, DESCRIPTOR,
        "Where the customer's income comes from: GOVERNMENT, "
        "GOVERNMENT_RELATED, PRIVATE_SECTOR, SELF_EMPLOYED or RETIRED. The "
        "strongest single non-behavioural predictor in this book."),
    "employer_id": ("string", None, IDENTIFIER,
        "The employer paying the salary, as a key. Concentration by employer "
        "is a retail risk in its own right where one employer pays many "
        "customers of the same book."),
    "employer_sector": ("string", None, DESCRIPTOR,
        "The economic sector of the customer's employer. The retail book's "
        "nearest equivalent of an industry exposure: it says what a salary "
        "depends on, not what the borrower does."),
    "employment_tenure_months": ("integer", "months", STOCK,
        "Whole months in current employment at this month-end. A CUSTOMER "
        "attribute repeated on every facility they hold."),
    "employment_change_flag": ("boolean", None, DESCRIPTOR,
        "Whether the employer on record changed since the previous month-end. "
        "A change is not itself adverse; a change WITH a salary interruption "
        "is what the early warning rules read."),
    "job_loss_reported_flag": ("boolean", None, DESCRIPTOR,
        "Whether a loss of employment has been reported for this customer. "
        "Declared or inferred — `job_loss_signal_source` says which."),
    "job_loss_signal_source": ("string", None, DESCRIPTOR,
        "Where the job-loss signal came from. In this synthetic book it is a "
        "customer declaration; in a real installation it would name the "
        "channel that reported it."),
    "housing_support_flag": ("boolean", None, DESCRIPTOR,
        "Whether the customer receives government housing support on this "
        "facility. It changes the instalment the household actually pays."),
    "housing_support_type": ("string", None, DESCRIPTOR,
        "Which housing support programme applies, or NONE."),

    # ------------------------------------------------ income and affordability
    "verified_monthly_salary_sar": ("number", "SAR", STOCK,
        "Monthly salary the bank has verified, at this month-end. A CUSTOMER "
        "level: summing it across a customer's facilities counts one person's "
        "income several times over."),
    "verified_other_monthly_income_sar": ("number", "SAR", STOCK,
        "Verified monthly income other than salary — rent, pension, a second "
        "trade. A CUSTOMER level, repeated on each facility."),
    "salary_verification_status": ("string", None, DESCRIPTOR,
        "How income was evidenced: VERIFIED_TRANSFER, where the salary lands "
        "in an account at this bank, or DECLARED_DOCUMENTED, where it was "
        "documented but is paid elsewhere. The first is materially stronger."),
    "salary_transfer_flag": ("boolean", None, DESCRIPTOR,
        "Whether the customer's salary is transferred to this bank. The "
        "single most important affordability control in Saudi retail lending: "
        "it is what makes an instalment deductible at source."),
    "origination_salary_transfer_status": ("string", None, DESCRIPTOR,
        "Whether the salary was transferred to this bank AT ORIGINATION. "
        "Frozen: it does not follow the customer if the arrangement lapses."),
    "household_expenses_sar": ("number", "SAR", STOCK,
        "The monthly household expense figure used in the affordability test "
        "at this month-end — the larger of what the customer declared and the "
        "policy floor for their dependants band."),
    "monthly_own_bank_credit_obligations_sar": ("number", "SAR", STOCK,
        "Monthly instalments owed to THIS bank across all of the customer's "
        "facilities, at this month-end. A CUSTOMER level."),
    "monthly_external_credit_obligations_sar": ("number", "SAR", STOCK,
        "Monthly instalments owed to OTHER lenders, from the bureau. A "
        "CUSTOMER level, repeated on each facility."),
    "external_obligations_change_3m_sar": ("number", "SAR", STOCK,
        "Change in monthly obligations to other lenders over three months. "
        "Positive means the customer has taken on borrowing elsewhere — the "
        "earliest visible sign of stress this book carries."),
    "obligation_scope_definition": ("string", None, DESCRIPTOR,
        "Which obligations the debt burden ratio counts, stated so the "
        "denominator can be reproduced."),
    "affordability_buffer_sar": ("number", "SAR", STOCK,
        "Verified income less household expenses and every monthly credit "
        "obligation. What is left each month once the household has paid what "
        "it must. Negative means the arithmetic does not close."),
    "balance_buffer_months": ("number", "months", RATIO,
        "How many months of the scheduled instalment the customer's average "
        "account balance would cover. A liquidity cushion, not a level."),
    "income_volatility_6m": ("number", None, RATIO,
        "Coefficient of variation of the last six salary credits. High means "
        "the income arrives in uneven amounts, whatever its average."),
    "salary_change_3m_ratio": ("number", "ratio", RATIO,
        "The latest salary credit over the average of the three before it. "
        "Below 1 means the salary has fallen."),
    "salary_credit_amount_1m_sar": ("number", "SAR", FLOW,
        "The salary credited to the customer's account in this month."),
    "salary_credit_average_3m_sar": ("number", "SAR", STOCK,
        "Average monthly salary credit over three months, to this month-end."),
    "salary_credit_average_6m_sar": ("number", "SAR", STOCK,
        "Average monthly salary credit over six months, to this month-end."),
    "salary_credit_last_date": ("date", None, EVENT_DATE,
        "The month-end of the most recent salary credit received."),
    "expected_salary_credit_date": ("date", None, EVENT_DATE,
        "When the next salary credit is due, from the customer's pattern."),
    "salary_delay_days": ("integer", "days", STOCK,
        "Days between when the salary was expected and when it arrived. Zero "
        "where it arrived on time."),
    "salary_missed_cycle_count_3m": ("number", None, COUNT,
        "Salary cycles with no credit at all in the last three months."),
    "account_average_balance_3m_sar": ("number", "SAR", STOCK,
        "Average current-account balance over three months, to this "
        "month-end. A CUSTOMER level."),
    "account_inflows_1m_sar": ("number", "SAR", FLOW,
        "Everything credited to the customer's accounts in this month, salary "
        "included. A PERIOD amount: sum it over the months of the period "
        "wanted, never across a level."),
    "account_outflows_1m_sar": ("number", "SAR", FLOW,
        "Everything debited from the customer's accounts in this month. A "
        "PERIOD amount."),

    # -------------------------------------------------------- the facility
    "product_label": ("string", None, DESCRIPTOR,
        "The retail product this facility is: Credit Card, Personal Finance, "
        "Auto Finance or Home Finance. The dimension almost every question "
        "about this book is grouped by."),
    "product_subsegment": ("string", None, DESCRIPTOR,
        "The variant within the product — a first home against a refinance, a "
        "new car against a used one, new lending against a top-up. Products "
        "behave differently inside these splits."),
    "facility_status": ("string", None, DESCRIPTOR,
        "Whether the facility is OPEN or CLOSED at this month-end. A closed "
        "facility keeps its row so the history can be read; it carries no "
        "exposure."),
    "closure_date": ("date", None, EVENT_DATE,
        "The month-end on which the facility closed, where it has."),
    "closure_reason": ("string", None, DESCRIPTOR,
        "Why the facility closed: SETTLED_EARLY, MATURED or WRITTEN_OFF. The "
        "third is a credit loss and the first two are not."),
    "currency": ("string", None, DESCRIPTOR,
        "The currency of the facility. Saudi riyal throughout this book, so "
        "every amount is comparable without conversion."),
    "portfolio_country": ("string", None, DESCRIPTOR,
        "The country of the lending book. SA throughout."),
    "contract_structure": ("string", None, DESCRIPTOR,
        "The Islamic financing structure: MURABAHA (cost-plus sale), "
        "TAWARRUQ (monetisation) or IJARA (lease). It decides how profit is "
        "recognised, not how risk is measured."),
    "auto_structure": ("string", None, DESCRIPTOR,
        "The financing structure for a vehicle facility — MURABAHA or IJARA. "
        "Under IJARA the bank holds title until the final payment."),
    "rate_type": ("string", None, DESCRIPTOR,
        "Whether the profit rate is FIXED for the term or FLOATING against a "
        "benchmark. Floating facilities carry instalment risk to the customer."),
    "nominal_annual_profit_interest_rate": ("number", "ratio", RATIO,
        "The contractual annual profit rate, as a decimal. Nominal: it does "
        "not include fees and is not what the customer effectively pays."),
    "effective_annual_interest_rate": ("number", "ratio", RATIO,
        "The annual rate including fees, on the same basis the customer is "
        "quoted. The rate the ECL discounting uses."),
    "monthly_discount_rate": ("number", "ratio", RATIO,
        "The effective annual rate converted to one month, which is the rate "
        "the ECL cashflows are actually discounted at."),
    "discount_method": ("string", None, DESCRIPTOR,
        "How the monthly discount rate was derived from the annual one, "
        "stated so the discounting can be reproduced."),
    "original_finance_amount_sar": ("number", "SAR", STOCK,
        "The amount financed at origination. Fixed for the life of the "
        "facility; it does not move as the balance amortises."),
    "original_credit_limit_sar": ("number", "SAR", STOCK,
        "The credit limit set at origination. On a card this is what the "
        "customer may draw; on an instalment facility it equals the amount "
        "financed."),
    "original_tenor_months": ("number", "months", STOCK,
        "The contractual term in months at origination."),
    "remaining_contractual_tenor_months": ("number", "months", STOCK,
        "Months from this month-end to contractual maturity."),
    "contractual_maturity_date": ("date", None, EVENT_DATE,
        "The month-end on which the last contractual payment falls due."),
    "scheduled_monthly_payment_sar": ("number", "SAR", STOCK,
        "The instalment contractually due each month at this month-end."),
    "secured_flag": ("boolean", None, DESCRIPTOR,
        "Whether the facility has collateral behind it. Home and auto "
        "facilities do; cards and personal finance do not."),
    "collateral_type": ("string", None, DESCRIPTOR,
        "What secures the facility — RESIDENTIAL_PROPERTY or VEHICLE."),
    "collateral_value_origination_sar": ("number", "SAR", STOCK,
        "The collateral's appraised value at origination. Not revalued: the "
        "current LTV moves with the balance, not with the property."),
    "collateral_valuation_date": ("date", None, EVENT_DATE,
        "When the collateral was last valued."),
    "down_payment_sar": ("number", "SAR", STOCK,
        "What the customer paid up front at origination."),
    "down_payment_band": ("string", None, DESCRIPTOR,
        "The down payment as a share of the asset price, in bands."),
    "ltv_origination_ratio": ("number", "ratio", RATIO,
        "Amount financed over collateral value at origination. A RATIO: "
        "recompute it from summed amounts, never average it across rows."),
    "ltv_current_ratio": ("number", "ratio", RATIO,
        "Current balance over the collateral's origination value. It falls as "
        "the balance amortises because the value is not refreshed."),
    "ltv_band": ("string", None, DESCRIPTOR,
        "The current loan-to-value ratio, in bands."),
    "property_type": ("string", None, DESCRIPTOR,
        "What kind of property secures a home facility."),
    "home_purpose": ("string", None, DESCRIPTOR,
        "Why the home facility was taken: FIRST_HOME, SECOND_PROPERTY or "
        "REFINANCE."),
    "vehicle_new_used": ("string", None, DESCRIPTOR,
        "Whether the financed vehicle was new or used at origination."),
    "vehicle_age_months": ("number", "months", STOCK,
        "The vehicle's age in months at this month-end."),
    "dealer_id": ("string", None, IDENTIFIER,
        "The dealer that introduced an auto facility. Dealer concentration "
        "and dealer-level default rates are an origination quality question."),
    "balloon_payment_sar": ("number", "SAR", STOCK,
        "A final lump sum due at the end of the term, above the regular "
        "instalments. Zero where the facility fully amortises."),
    "balloon_due_date": ("date", None, EVENT_DATE,
        "When the balloon payment falls due."),
    "balloon_band": ("string", None, DESCRIPTOR,
        "The balloon as a share of the amount financed, in bands. NONE where "
        "there is no balloon."),
    "months_to_balloon": ("number", "months", STOCK,
        "Months from this month-end until the balloon falls due. The months "
        "before it are the months to find the money in."),
    "origination_balloon_ratio": ("number", "ratio", RATIO,
        "The balloon over the amount financed, at origination."),
    "refinanced_from_facility_id": ("string", None, IDENTIFIER,
        "The facility this one refinanced, where it refinanced one. A chain "
        "of refinancings is a repayment difficulty that never showed as DPD."),
    "branch_id": ("string", None, IDENTIFIER,
        "The branch that booked the facility."),
    "origination_channel": ("string", None, DESCRIPTOR,
        "How the facility was sold: BRANCH, DIGITAL, PARTNER, DEALER or "
        "RELATIONSHIP_MANAGER. Channels differ in default rate at the same "
        "score, which is the point of measuring it."),
    "origination_date": ("date", None, EVENT_DATE,
        "The month-end on which the facility was booked."),
    "application_date": ("date", None, EVENT_DATE,
        "The month-end on which the customer applied."),
    "approval_date": ("date", None, EVENT_DATE,
        "The month-end on which the application was approved."),
    "decision_at_origination": ("string", None, DESCRIPTOR,
        "What the credit decision was. Every facility in a book of BOOKED "
        "facilities was approved; declined applications are not here, which "
        "is why an approval rate cannot be computed from this dataset."),
    "new_to_bank_at_origination_flag": ("boolean", None, DESCRIPTOR,
        "Whether the customer was new to the bank when this facility was "
        "booked. A new-to-bank customer is scored without internal history."),
    "policy_version_at_origination": ("string", None, IDENTIFIER,
        "The version of the credit policy — cutoffs and rules — in force when "
        "this facility was decided."),
    "applied_score_cutoff": ("number", "points", STOCK,
        "The application score cutoff that applied to this facility at "
        "origination. A facility booked below it is a policy exception."),
    "policy_exception_flag": ("boolean", None, DESCRIPTOR,
        "Whether the facility was booked outside policy — below cutoff, or "
        "past an affordability limit."),
    "policy_exception_reason": ("string", None, DESCRIPTOR,
        "Which policy the exception was against, in words."),

    # -------------------------------------- origination-time frozen measures
    "origination_income_sar": ("number", "SAR", STOCK,
        "Verified monthly income AT ORIGINATION. Frozen: it is what was "
        "underwritten, and comparing it with income now is how income drift "
        "is measured."),
    "origination_salary_sar": ("number", "SAR", STOCK,
        "Verified monthly salary at origination. Frozen."),
    "origination_household_expenses_sar": ("number", "SAR", STOCK,
        "The household expense figure used in the affordability test at "
        "origination. Frozen."),
    "origination_external_obligations_sar": ("number", "SAR", STOCK,
        "Monthly obligations to other lenders at origination. Frozen."),
    "origination_own_bank_obligations_sar": ("number", "SAR", STOCK,
        "Monthly obligations to this bank at origination. Frozen."),
    "origination_total_obligations_sar": ("number", "SAR", STOCK,
        "All monthly credit obligations at origination. Frozen."),
    "origination_disposable_income_sar": ("number", "SAR", STOCK,
        "Income less expenses and obligations at origination — the "
        "affordability buffer as it was underwritten."),
    "origination_debt_burden_ratio": ("number", "ratio", RATIO,
        "Total monthly obligations over income at origination. The ratio the "
        "affordability limit was tested against."),
    "origination_instalment_to_income_ratio": ("number", "ratio", RATIO,
        "This facility's instalment over income at origination."),
    "origination_amount_to_income_ratio": ("number", "ratio", RATIO,
        "Amount financed over monthly income at origination — how many months "
        "of income was lent."),
    "origination_income_stability_ratio": ("number", "ratio", RATIO,
        "How steady the income was over the months before origination. Low "
        "means it varied."),
    "origination_employment_tenure_months": ("integer", "months", STOCK,
        "Months in employment at origination. Frozen."),
    "origination_customer_tenure_months": ("integer", "months", STOCK,
        "Months of relationship with the bank at origination. Zero for a "
        "new-to-bank customer."),
    "origination_bureau_enquiries_3m": ("number", None, COUNT,
        "Bureau enquiries in the three months before origination — how hard "
        "the customer was shopping for credit when they applied."),
    "origination_bureau_active_facilities": ("number", None, COUNT,
        "Facilities open with other lenders at origination."),
    "origination_bureau_external_dpd_max": ("number", "days", STOCK,
        "Worst days past due with any other lender, at origination."),

    # ------------------------------------------------ delinquency and arrears
    "previous_month_dpd": ("number", "days", STOCK,
        "Days past due at the PREVIOUS month-end. Held on the row so a "
        "movement can be read without joining the book to itself."),
    "max_dpd_3m": ("number", "days", STOCK,
        "The worst days past due reached in the last three months. A "
        "facility can be current today and have been 60 days down in May."),
    "max_dpd_6m": ("number", "days", STOCK,
        "The worst days past due reached in the last six months."),
    "max_dpd_12m": ("number", "days", STOCK,
        "The worst days past due reached in the last twelve months."),
    "days_30plus_count_12m": ("number", None, COUNT,
        "Days spent at 30 or more days past due over twelve months."),
    "months_30plus_count_12m": ("number", None, COUNT,
        "Month-ends at 30 or more days past due over twelve months. Three "
        "separate month-ends in arrears is a different risk from one long "
        "spell, and this is the column that tells them apart."),
    "missed_payment_count_3m": ("number", None, COUNT,
        "Scheduled payments not made in the last three months."),
    "missed_payment_count_6m": ("number", None, COUNT,
        "Scheduled payments not made in the last six months."),
    "full_payment_months_6m": ("number", None, COUNT,
        "Months in the last six in which the full instalment was paid."),
    "payment_to_due_ratio_1m": ("number", "ratio", RATIO,
        "What was paid over what was due, in this month. Below 1 is a part "
        "payment; a card customer paying the minimum sits well below it."),
    "payment_to_due_ratio_3m": ("number", "ratio", RATIO,
        "What was paid over what was due, across three months."),
    "returned_payment_count_3m": ("number", None, COUNT,
        "Direct debits returned unpaid in the last three months."),
    "autopay_failure_count_3m": ("number", None, COUNT,
        "Automatic payment attempts that failed in the last three months."),
    "oldest_unpaid_due_date": ("date", None, EVENT_DATE,
        "The due date of the oldest instalment still unpaid. It is what days "
        "past due is counted from."),
    "collections_stage": ("string", None, DESCRIPTOR,
        "How far into collections the facility has gone: NONE, SOFT_REMINDER, "
        "TELE_COLLECTION, FIELD, LEGAL or WRITE_OFF."),
    "contact_attempts_3m": ("integer", None, COUNT,
        "Collections contact attempts in the last three months."),
    "promise_to_pay_flag": ("boolean", None, DESCRIPTOR,
        "Whether the customer has an outstanding promise to pay."),
    "promise_to_pay_due_date": ("date", None, EVENT_DATE,
        "When the promised payment is due."),
    "broken_promise_count_3m": ("number", None, COUNT,
        "Promises to pay that were made and not kept, over three months. A "
        "broken promise is a stronger signal than a missed instalment: the "
        "customer engaged and still did not pay."),

    # ------------------------------------------------- card behaviour
    "card_behaviour_segment": ("string", None, DESCRIPTOR,
        "How the card is used: TRANSACTOR (settled in full), REVOLVER "
        "(carries a balance) or INACTIVE. The same limit is a different risk "
        "in each."),
    "utilisation_avg_3m": ("number", "ratio", RATIO,
        "Average drawn balance over credit limit across three months."),
    "utilisation_band": ("string", None, DESCRIPTOR,
        "Current utilisation, in bands. Above 100% means an overlimit "
        "balance."),
    "utilisation_change_3m_pp": ("number", "percentage points", RATIO,
        "Change in utilisation over three months, in percentage points. "
        "Already a difference: do not difference it again."),
    "overlimit_days_3m": ("number", "days", COUNT,
        "Days spent above the credit limit in the last three months."),
    "minimum_payment_only_months_3m": ("number", None, COUNT,
        "Months in the last three where only the minimum payment was made."),
    "cash_advance_share_3m": ("number", "ratio", RATIO,
        "Cash advances as a share of card spend over three months. Cash "
        "advance on a card is expensive money and is read as a liquidity "
        "signal, not as spending."),

    # ------------------------------------------------------------ the bureau
    "bureau_source_label": ("string", None, DESCRIPTOR,
        "Which bureau the external data came from. Synthetic here: this book "
        "carries a bureau PROXY, not SIMAH data."),
    "bureau_score_scale_id": ("string", None, IDENTIFIER,
        "The scale the bureau score is expressed on, so scores from different "
        "vintages are not compared across scales."),
    "bureau_score_current": ("number", "points", STOCK,
        "The customer's bureau score at this month-end. Higher is safer."),
    "bureau_score_current_date": ("date", None, EVENT_DATE,
        "When the current bureau score was drawn."),
    "bureau_score_at_origination": ("number", "points", STOCK,
        "The bureau score as at origination. Frozen: comparing it with the "
        "current score measures how the customer has moved since underwriting."),
    "bureau_score_origination_date": ("date", None, EVENT_DATE,
        "When the origination bureau score was drawn."),
    "bureau_score_change_3m": ("number", "points", RATIO,
        "Change in the bureau score over three months. Already a difference."),
    "bureau_enquiries_3m": ("number", None, COUNT,
        "Credit enquiries recorded at the bureau in three months. A burst of "
        "enquiries is a customer looking for money."),
    "bureau_enquiries_6m": ("number", None, COUNT,
        "Credit enquiries recorded at the bureau in six months."),
    "bureau_active_facilities_count": ("number", None, COUNT,
        "Facilities the customer has open with other lenders."),
    "bureau_total_exposure_sar": ("number", "SAR", STOCK,
        "Total balances owed to other lenders. A CUSTOMER level: summing it "
        "over a customer's facilities counts the same external debt twice."),
    "bureau_external_dpd_max": ("number", "days", STOCK,
        "Worst days past due with any other lender. A customer current here "
        "and 90 days down elsewhere is the case this column exists for."),
    "bureau_adverse_flag": ("boolean", None, DESCRIPTOR,
        "Whether the bureau reports an adverse event — a default, a judgment "
        "or a write-off — with another lender."),
    "bureau_thin_file_flag": ("boolean", None, DESCRIPTOR,
        "Whether the bureau holds too little history to score reliably. A "
        "thin file is not a bad file, and treating it as one is a known way "
        "to decline good customers."),
    "bureau_data_available_flag": ("boolean", None, DESCRIPTOR,
        "Whether bureau data was returned at all for this customer."),
    "bureau_data_freshness_days": ("integer", "days", STOCK,
        "How old the bureau data is, in days, at this month-end."),

    # ------------------------------------------------ the application score
    "application_score_at_origination": ("number", "points", STOCK,
        "The application scorecard's score when the facility was decided. "
        "Higher is safer. Frozen for the life of the facility: this is the "
        "column origination quality by vintage is measured on."),
    "application_score_band": ("string", None, DESCRIPTOR,
        "The application score expressed as a band, A+ through E."),
    "application_score_date": ("date", None, EVENT_DATE,
        "When the application score was produced."),
    "application_score_direction": ("string", None, DESCRIPTOR,
        "Which way the scale runs. HIGHER_IS_SAFER throughout, stated "
        "explicitly because a validation test that assumes the other "
        "direction reports every Gini with its sign reversed."),
    "application_score_model_id": ("string", None, IDENTIFIER,
        "Which application scorecard scored this facility. There is one per "
        "product, and comparing scores across two of them is not meaningful."),
    "application_score_model_version": ("string", None, IDENTIFIER,
        "The version of that application scorecard."),
    "application_score_status": ("string", None, DESCRIPTOR,
        "Whether an application score exists, and why not where it does not."),
    "application_score_reconciled_flag": ("boolean", None, DESCRIPTOR,
        "Whether the stored score was reproduced exactly from the stored "
        "inputs, the frozen bins and the published coefficients. False is an "
        "implementation defect, not a model outcome."),
    "application_transform_version": ("string", None, IDENTIFIER,
        "The version of the weight-of-evidence transformation the "
        "application scorecard used."),
    "application_predicted_pd_12m": ("number", "ratio", RATIO,
        "The twelve-month probability of default the application score maps "
        "to. A probability: recompute it over a population, never sum it."),
    "app_model_id": ("string", None, IDENTIFIER,
        "The application model that produced the flattened `app_*` columns."),
    "app_model_version": ("string", None, IDENTIFIER,
        "The version of that application model. Two facilities scored by "
        "different versions are not comparable on the same scale."),
    "app_transform_version": ("string", None, IDENTIFIER,
        "The binning and weight-of-evidence version it used."),
    "app_target_definition_id": ("string", None, IDENTIFIER,
        "What the application model was trained to predict, as a governed "
        "definition — first default within twelve months of origination."),
    "app_score_value": ("number", "points", STOCK,
        "The application score as computed here, after clipping to the "
        "publishable range. Equal to `application_score_at_origination`."),
    "app_score_unclipped": ("number", "points", STOCK,
        "The application score before clipping to the publishable range. "
        "Where the two differ, the clip is doing the work."),
    "app_score_logit": ("number", None, RATIO,
        "The log-odds the application model produced, before the points "
        "mapping. The scale the model actually works on."),
    "app_score_base_points": ("number", "points", STOCK,
        "The application scorecard's intercept in points. Base points plus "
        "every feature's points equals the score exactly."),
    "app_score_points_total": ("number", "points", STOCK,
        "The sum of every application feature's points contribution."),
    "app_score_band_value": ("string", None, DESCRIPTOR,
        "The band the application score falls in, A+ through E."),
    "app_predicted_pd_12m": ("number", "ratio", RATIO,
        "The twelve-month PD the application score maps to."),
    "app_input_missing_count": ("integer", None, COUNT,
        "How many application model inputs were absent and scored in the "
        "MISSING bin. A score built on absent inputs is weaker than the same "
        "score built on present ones."),

    # ------------------------------------------------ the behavioural score
    "behavioural_score": ("number", "points", STOCK,
        "The behavioural scorecard's score at THIS month-end, from how the "
        "customer has actually behaved. Higher is safer. Recomputed monthly: "
        "this is the column the monthly risk view is built on."),
    "behavioural_score_band": ("string", None, DESCRIPTOR,
        "The behavioural score expressed as a band, A+ through E."),
    "behavioural_score_previous_month": ("number", "points", STOCK,
        "The behavioural score at the previous month-end, held on the row so "
        "a movement can be read without a self-join."),
    "behavioural_score_change_3m": ("number", "points", RATIO,
        "Change in the behavioural score over three months. Already a "
        "difference: do not difference it again. A large fall is the "
        "deterioration signal the early warning rules read first."),
    "behavioural_score_date": ("date", None, EVENT_DATE,
        "When the behavioural score was produced — this month-end."),
    "behavioural_score_direction": ("string", None, DESCRIPTOR,
        "Which way the scale runs. HIGHER_IS_SAFER."),
    "behavioural_score_model_id": ("string", None, IDENTIFIER,
        "Which behavioural scorecard scored this facility. One per product."),
    "behavioural_score_model_version": ("string", None, IDENTIFIER,
        "The version of that behavioural scorecard."),
    "behavioural_score_status": ("string", None, DESCRIPTOR,
        "Whether a behavioural score exists. NOT_SCORED_THIN_HISTORY where "
        "the facility has too few months to score — a state, not a zero."),
    "behavioural_score_reconciled_flag": ("boolean", None, DESCRIPTOR,
        "Whether the stored behavioural score was reproduced exactly from "
        "stored inputs, frozen bins and published coefficients."),
    "behavioural_transform_version": ("string", None, IDENTIFIER,
        "The weight-of-evidence version the behavioural scorecard used."),
    "behavioural_predicted_pd_12m": ("number", "ratio", RATIO,
        "The twelve-month PD the behavioural score maps to."),
    "behaviour_history_months_available": ("number", "months", STOCK,
        "How many months of behaviour the facility has. Below the model's "
        "minimum it is not scored, and this column says why."),
    "behavioural_expected_life_months": ("integer", "months", STOCK,
        "The expected remaining life the behavioural view assumes, which on a "
        "revolving facility is not the contractual term."),
    "beh_model_id": ("string", None, IDENTIFIER,
        "The behavioural model that produced the flattened `beh_*` columns."),
    "beh_model_version": ("string", None, IDENTIFIER,
        "The version of that behavioural model. Two facilities scored by "
        "different versions are not comparable on the same scale."),
    "beh_transform_version": ("string", None, IDENTIFIER,
        "The binning and weight-of-evidence version it used."),
    "beh_target_definition_id": ("string", None, IDENTIFIER,
        "What the behavioural model was trained to predict, as a governed "
        "definition — first default within the twelve months after the "
        "observation month."),
    "beh_score_value": ("number", "points", STOCK,
        "The behavioural score as computed here, after clipping. Equal to "
        "`behavioural_score`."),
    "beh_score_unclipped": ("number", "points", STOCK,
        "The behavioural score before clipping to the publishable range."),
    "beh_score_logit": ("number", None, RATIO,
        "The log-odds the behavioural model produced, before the points "
        "mapping."),
    "beh_score_base_points": ("number", "points", STOCK,
        "The behavioural scorecard's intercept in points."),
    "beh_score_points_total": ("number", "points", STOCK,
        "The sum of every behavioural feature's points contribution."),
    "beh_score_band_value": ("string", None, DESCRIPTOR,
        "The band the behavioural score falls in, A+ through E."),
    "beh_predicted_pd_12m": ("number", "ratio", RATIO,
        "The twelve-month PD the behavioural score maps to."),
    "beh_input_missing_count": ("number", None, COUNT,
        "How many behavioural model inputs were absent and scored in the "
        "MISSING bin."),

    # ------------------------------------------- score governance and overrides
    "score_subject_grain": ("string", None, DESCRIPTOR,
        "What one scored row IS. FACILITY here: a customer with three "
        "facilities has three scores, and averaging them is not a customer "
        "score."),
    "score_target_definition_id": ("string", None, IDENTIFIER,
        "The outcome both scorecards are measured against, as a governed "
        "definition."),
    "score_input_missing_count": ("number", None, COUNT,
        "Model inputs absent at scoring, across both scorecards."),
    "score_input_stale_count": ("integer", None, COUNT,
        "Model inputs that were present but older than their freshness rule "
        "allows. Stale is not missing, and the two are counted apart."),
    "score_override_flag": ("boolean", None, DESCRIPTOR,
        "Whether a human changed the score the model produced."),
    "score_override_direction": ("string", None, DESCRIPTOR,
        "Whether the override made the score better or worse."),
    "score_override_reason": ("string", None, DESCRIPTOR,
        "Why the score was overridden, in words. An override rate and its "
        "reasons are a model governance finding in their own right."),
    "score_implementation_check_status": ("string", None, DESCRIPTOR,
        "Whether the stored score was reproduced from its stored inputs. PASS "
        "means the implementation agrees with the specification."),
    "score_evidence_ref": ("string", None, IDENTIFIER,
        "The key of the stored evidence for this score — inputs, bins, "
        "weights and the arithmetic. What makes the score auditable."),

    # ------------------------------------------------------- IFRS 9 staging
    "previous_month_stage": ("integer", None, DESCRIPTOR,
        "The IFRS 9 stage at the previous month-end. Held on the row so a "
        "stage migration can be read without joining the book to itself."),
    "stage_entry_date": ("date", None, EVENT_DATE,
        "When the facility entered its current stage. How long it has been in "
        "Stage 2 matters as much as that it is."),
    "stage_override_flag": ("boolean", None, DESCRIPTOR,
        "Whether the stage was set by judgment rather than by the rules."),
    "stage_override_reason": ("string", None, DESCRIPTOR,
        "Why the stage was overridden, in words."),
    "staging_policy_version": ("string", None, IDENTIFIER,
        "The version of the staging policy that produced this stage."),
    "sicr_flag": ("boolean", None, DESCRIPTOR,
        "Whether a significant increase in credit risk has been identified — "
        "the test that moves a facility from Stage 1 to Stage 2."),
    "sicr_quantitative_flag": ("boolean", None, DESCRIPTOR,
        "Whether the SICR test was met on the quantitative limb: lifetime PD "
        "has risen enough against origination."),
    "sicr_qualitative_flag": ("boolean", None, DESCRIPTOR,
        "Whether the SICR test was met on the qualitative limb — forbearance, "
        "repeated arrears, a behavioural collapse."),
    "sicr_dpd_backstop_flag": ("boolean", None, DESCRIPTOR,
        "Whether the 30-days-past-due backstop alone moved this facility to "
        "Stage 2. A backstop-only population is one whose models saw nothing."),
    "sicr_pd_ratio": ("number", "ratio", RATIO,
        "Lifetime PD now over lifetime PD at origination. The quantitative "
        "SICR test compares this with its threshold."),
    "sicr_pd_absolute_change": ("number", "ratio", RATIO,
        "Lifetime PD now minus lifetime PD at origination, in absolute terms. "
        "The second half of the quantitative test: a small PD can triple "
        "without becoming material."),
    "sicr_reason": ("string", None, DESCRIPTOR,
        "Which test moved this facility, in words. The sentence a reviewer "
        "reads when they ask why a facility is in Stage 2."),
    "credit_impaired_flag": ("boolean", None, DESCRIPTOR,
        "Whether the facility is credit-impaired — Stage 3. Not the same as "
        "written off, and not the same as in collections."),
    "unlikeliness_to_pay_flag": ("boolean", None, DESCRIPTOR,
        "Whether default was called on unlikeliness to pay rather than on "
        "days past due. It is what catches a default that never showed as "
        "arrears."),
    "default_definition_id": ("string", None, IDENTIFIER,
        "The governed definition of default in force — 90 days past due or "
        "unlikeliness to pay."),
    "default_reason": ("string", None, DESCRIPTOR,
        "Which limb of the default definition was met."),
    "default_episode_id": ("string", None, IDENTIFIER,
        "The key of this default episode. A facility that defaults, cures and "
        "defaults again has two episodes, and counting defaults without this "
        "column counts the customer twice."),
    "first_default_date": ("date", None, EVENT_DATE,
        "When this facility first defaulted."),
    "latest_default_date": ("date", None, EVENT_DATE,
        "When this facility most recently defaulted."),
    "cure_flag": ("boolean", None, DESCRIPTOR,
        "Whether the facility has cured out of default."),
    "cure_date": ("date", None, EVENT_DATE,
        "When the facility cured."),
    "cure_probation_months": ("integer", "months", STOCK,
        "How many months a cured facility must stay current before it leaves "
        "default. A cure inside probation is not yet a cure."),
    "forbearance_flag": ("boolean", None, DESCRIPTOR,
        "Whether the facility has been granted forbearance — a concession "
        "made because the customer was in financial difficulty."),
    "forbearance_start_date": ("date", None, EVENT_DATE,
        "When forbearance was granted."),
    "restructured_flag": ("boolean", None, DESCRIPTOR,
        "Whether the facility's terms were restructured. Restructuring "
        "without financial difficulty is not forbearance; the two flags are "
        "separate for that reason."),
    "restructure_date": ("date", None, EVENT_DATE,
        "When the facility was restructured."),
    "writeoff_flag": ("boolean", None, DESCRIPTOR,
        "Whether the balance has been written off. A write-off removes the "
        "asset; it does not end the claim on the customer."),
    "credit_risk_model_id": ("string", None, IDENTIFIER,
        "The IFRS 9 model set that produced the staging, PD, LGD and EAD on "
        "this row."),

    # ------------------------------------------------------- PD, LGD, EAD, ECL
    "ifrs9_pd_source_model": ("string", None, DESCRIPTOR,
        "Which scorecard the IFRS 9 PD was mapped from — the behavioural "
        "model where the facility has history, the application model where it "
        "does not."),
    "ifrs9_pd_mapping_version": ("string", None, IDENTIFIER,
        "The version of the score-to-PD mapping used."),
    "pd_curve_id": ("string", None, IDENTIFIER,
        "The PD term structure applied to this facility."),
    "pd_model_version": ("string", None, IDENTIFIER,
        "The version of the PD model."),
    "pd_pit_12m_anchor": ("number", "ratio", RATIO,
        "The twelve-month point-in-time PD before scenario weighting — the "
        "anchor the three scenarios are built around. A probability: never "
        "sum it, and recompute it over a population weighted by exposure."),
    "pd_pit_12m_upturn": ("number", "ratio", RATIO,
        "Twelve-month point-in-time PD under the upturn scenario."),
    "pd_pit_12m_downturn": ("number", "ratio", RATIO,
        "Twelve-month point-in-time PD under the downturn scenario."),
    "pd_pit_lifetime_upturn": ("number", "ratio", RATIO,
        "Lifetime point-in-time PD under the upturn scenario."),
    "pd_pit_lifetime_downturn": ("number", "ratio", RATIO,
        "Lifetime point-in-time PD under the downturn scenario."),
    "pd_pit_at_origination_12m": ("number", "ratio", RATIO,
        "The twelve-month point-in-time PD as at origination. Frozen: it is "
        "the denominator of the quantitative SICR test."),
    "pd_ttc_at_origination_12m": ("number", "ratio", RATIO,
        "The twelve-month through-the-cycle PD at origination — the same risk "
        "without the point in the cycle."),
    "pd_origination_curve_remaining_life": ("number", "ratio", RATIO,
        "The origination PD curve read at the facility's remaining life, so "
        "the SICR comparison is like for like rather than comparing a "
        "remaining-life PD with a whole-life one."),
    "lgd_base": ("number", "ratio", RATIO,
        "Loss given default under the base scenario — the share of exposure "
        "expected to be lost once a default happens, after recoveries and "
        "collateral. A RATIO: weight it by exposure, never average it."),
    "lgd_upturn": ("number", "ratio", RATIO,
        "Loss given default under the upturn scenario."),
    "lgd_downturn": ("number", "ratio", RATIO,
        "Loss given default under the downturn scenario. On a secured "
        "facility this is where a fall in collateral values shows up."),
    "lgd_curve_id": ("string", None, IDENTIFIER,
        "The LGD curve applied to this facility."),
    "lgd_model_version": ("string", None, IDENTIFIER,
        "The version of the LGD model."),
    "recovery_rate_nominal": ("number", "ratio", RATIO,
        "The share of exposure expected to be recovered, before discounting. "
        "One minus this, discounted for the delay, is LGD."),
    "recovery_delay_months": ("number", "months", STOCK,
        "How long recoveries take to arrive. The delay is why a nominal "
        "recovery rate and a discounted one differ."),
    "recovery_cashflow_ref": ("string", None, IDENTIFIER,
        "The recovery cashflow profile used."),
    "expected_sale_cost_ratio": ("number", "ratio", RATIO,
        "Costs of realising collateral, as a share of its value. It is why "
        "LGD on a fully secured facility is not zero."),
    "ccf_base": ("number", "ratio", RATIO,
        "Credit conversion factor under the base scenario — the share of the "
        "undrawn limit expected to be drawn before default. It is what makes "
        "exposure at default exceed today's balance on a card."),
    "ccf_upturn": ("number", "ratio", RATIO,
        "Credit conversion factor under the upturn scenario."),
    "ccf_downturn": ("number", "ratio", RATIO,
        "Credit conversion factor under the downturn scenario."),
    "ead_base_sar": ("number", "SAR", STOCK,
        "Exposure at default under the base scenario: drawn balance plus the "
        "converted share of the undrawn limit. The exposure ECL is computed "
        "on, and the one an exposure-weighted average must weight by."),
    "ead_upturn_sar": ("number", "SAR", STOCK,
        "Exposure at default under the upturn scenario."),
    "ead_downturn_sar": ("number", "SAR", STOCK,
        "Exposure at default under the downturn scenario."),
    "ead_curve_id": ("string", None, IDENTIFIER,
        "The EAD curve applied to this facility."),
    "ead_model_version": ("string", None, IDENTIFIER,
        "The version of the EAD model."),
    "ecl_drawn_balance_sar": ("number", "SAR", STOCK,
        "The drawn balance the ECL calculation started from."),
    "ecl_undrawn_commitment_sar": ("number", "SAR", STOCK,
        "The undrawn limit the credit conversion factor was applied to."),
    "ecl_horizon_type": ("string", None, DESCRIPTOR,
        "Which horizon this facility's ECL covers — twelve months for Stage "
        "1, remaining lifetime for Stage 2, and the recovery profile for "
        "Stage 3. It is the sentence that explains why two facilities of the "
        "same size carry very different allowances."),
    "ecl_expected_life_months": ("integer", "months", STOCK,
        "The life the lifetime ECL was computed over. On a revolving facility "
        "this is a behavioural estimate, not the contractual term."),
    "ecl_remaining_life_months": ("integer", "months", STOCK,
        "Months of expected life remaining at this month-end."),
    "ecl_contractual_remaining_months": ("integer", "months", STOCK,
        "Months to contractual maturity. Where this and the expected life "
        "differ, the behavioural assumption is doing the work."),
    "ecl_model_version": ("string", None, IDENTIFIER,
        "The version of the ECL engine that produced the allowance."),
    "allowance_scope": ("string", None, DESCRIPTOR,
        "What the loss allowance is measured on — the facility as a whole, "
        "here, rather than a portion of it."),
    "scenario_set_id": ("string", None, IDENTIFIER,
        "The forward-looking scenario set used."),
    "scenario_set_version": ("string", None, IDENTIFIER,
        "The version of that scenario set."),
    "scenario_weight_base": ("number", "ratio", RATIO,
        "The probability weight on the base scenario. The three weights sum "
        "to one, which is the invariant a scenario-weight test checks."),
    "scenario_weight_upturn": ("number", "ratio", RATIO,
        "The probability weight on the upturn scenario."),
    "scenario_weight_downturn": ("number", "ratio", RATIO,
        "The probability weight on the downturn scenario."),

    # ------------------------------------------------- monitoring and outcomes
    "monitoring_as_of_date": ("date", None, EVENT_DATE,
        "The month-end this monitoring observation was taken at."),
    "monitoring_reference_id": ("string", None, IDENTIFIER,
        "The key of the monthly monitoring cohort this row belongs to."),
    "monitoring_reference_type": ("string", None, DESCRIPTOR,
        "How the monitoring cohort was formed — a monthly landmark cohort: "
        "everyone eligible at this month-end, followed forward."),
    "monitoring_exclusion_reason": ("string", None, DESCRIPTOR,
        "Why a facility is not in the monitoring cohort — already in default "
        "at the observation date, most often. Excluding it is right, and it "
        "is why a default rate over this book is not a count of defaults over "
        "a count of rows."),
    "model_use_population": ("string", None, DESCRIPTOR,
        "Whether this row is in the population a model may be measured on. "
        "A facility already in default is excluded from a PD test: its "
        "outcome is known before the prediction is made."),
    "performance_window_start": ("date", None, EVENT_DATE,
        "The first month of the window this observation's outcome is measured "
        "over."),
    "performance_window_end": ("date", None, EVENT_DATE,
        "The last month of that window. Where it is in the future, the "
        "outcome is not yet knowable, and a default rate computed over this "
        "row is a rate over the defaults that have already happened."),
    "performance_window_months": ("integer", "months", STOCK,
        "How long the performance window is — twelve months here."),
    "observed_followup_months": ("integer", "months", STOCK,
        "How many months of the window have actually elapsed. Below the "
        "window length the cohort is immature."),
    "censoring_reason": ("string", None, DESCRIPTOR,
        "Why an outcome is not observed for this row, in words. Usually that "
        "the window has not closed."),
    "prediction_reference_date": ("date", None, EVENT_DATE,
        "The date the prediction was made as at. Everything used to make it "
        "must be knowable on this date, which is what stops an outcome "
        "leaking into a predictor."),

    # ------------------------------------------------ provenance and plumbing
    "source_system": ("string", None, IDENTIFIER,
        "Which system this row came from. A synthetic generator here, stated "
        "rather than implied."),
    "source_record_id": ("string", None, IDENTIFIER,
        "The key of the source record this row was built from, so any figure "
        "can be traced back to what the source system sent."),
    "source_available_at": ("string", None, EVENT_DATE,
        "When the source data became available. Read with "
        "`calculation_available_at` it says how long the book took to close."),
    "calculation_run_id": ("string", None, IDENTIFIER,
        "The key of the calculation run that produced this row. Two rows with "
        "the same run id were produced by the same code and the same inputs."),
    "calculation_input_hash": ("string", None, IDENTIFIER,
        "A hash of the inputs to the calculation. Two runs with the same hash "
        "and different outputs is a reproducibility defect."),
    "calculation_method_label": ("string", None, DESCRIPTOR,
        "The calculation method, in words — a transparent monthly-hazard "
        "expected credit loss in this installation."),
    "calculation_available_at": ("string", None, EVENT_DATE,
        "When the calculated figures became available."),
    "data_quality_status": ("string", None, DESCRIPTOR,
        "Whether this row passed the publication quality checks. "
        "THIN_HISTORY marks a facility with too little history to score, "
        "which is a state rather than a fault."),
    "generator_version": ("string", None, IDENTIFIER,
        "The version of the synthetic generator that produced this book."),
    "is_synthetic": ("boolean", None, DESCRIPTOR,
        "Whether the row is synthetic. True on every row of this book: it is "
        "demonstration data, and this column is what makes that checkable "
        "rather than a claim in a footnote."),
}


def spec_kwargs(name: str) -> dict[str, Any] | None:
    """The curated entry for a column, as ColumnSpec keyword arguments."""
    entry = ENTRIES.get(name)
    if entry is None:
        return None
    data_type, unit, semantics, definition = entry
    return {"data_type": data_type, "unit": unit, "semantics": semantics,
            "definition": definition}


__all__ = ["ENTRIES", "spec_kwargs"]
