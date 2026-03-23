"""
models.py — Data Models for the 835/837 Remittance Reconciliation Pipeline

WHY THIS FILE EXISTS:
Three core data flows run through this system:
1. ReconciliationResult — one claim matched to its 835 payment outcome
2. PaymentVariance — underpayment/overpayment against contracted rate
3. FeedbackRecommendation — rule change recommended for Project 1

All shapes defined here. All other modules import from here.

DOMAIN CONTEXT:
835 = Electronic Remittance Advice (ERA) — payer sends this after adjudication
837 = Healthcare Claim — provider sends this to request payment

The reconciliation problem: match every 837 claim to its 835 payment outcome,
classify the result, detect variances from contracted rates,
and learn from denial patterns to improve upstream validation.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class ReconciliationStatus(Enum):
    """
    Six classification outcomes for a reconciled claim.

    Based on CARC group code logic (CO/PR/OA/PI) from CMS and X12 standards:

    MATCHED              → Paid per contracted rate. CO adjustments only = expected write-offs.
    UNDERPAYMENT         → Paid less than contracted rate. Variance is recoverable.
    CONTRACTUAL_ADJUST   → Expected reduction per contract (deductible, copay, coinsurance).
                           CO + PR adjustments = patient/provider responsibility as contracted.
    DENIAL               → $0 payment. CARC codes explain why. Resubmit or appeal.
    REVERSAL             → Previously paid claim reversed/taken back by payer.
    PENDING              → No 835 received yet. Claim in A/R, awaiting payer response.
    """
    MATCHED            = "MATCHED"
    UNDERPAYMENT       = "UNDERPAYMENT"
    CONTRACTUAL_ADJUST = "CONTRACTUAL_ADJUSTMENT"
    DENIAL             = "DENIAL"
    REVERSAL           = "REVERSAL"
    PENDING            = "PENDING"


class DenialCategory(Enum):
    """
    High-level denial categories derived from CARC group codes.
    Used for pattern analysis and feedback loop recommendations.

    CO = Contractual Obligation (provider write-off)
    PR = Patient Responsibility (bill the patient)
    PI = Payer Initiated (payer policy reduction)
    OA = Other Adjustments
    """
    TECHNICAL          = "TECHNICAL"          # CO codes: NPI, format, eligibility errors
    MEDICAL_NECESSITY  = "MEDICAL_NECESSITY"  # CO-50, CO-57: not medically necessary
    BUNDLING           = "BUNDLING"           # CO-97, CO-4: bundled with another service
    DUPLICATE          = "DUPLICATE"          # OA-18: exact duplicate claim
    TIMELY_FILING      = "TIMELY_FILING"      # CO-29: filed after deadline
    PRIOR_AUTH         = "PRIOR_AUTH"         # CO-15: prior auth required/missing
    COVERAGE           = "COVERAGE"           # CO-96, CO-27: not covered under plan
    PATIENT_RESP       = "PATIENT_RESP"       # PR codes: deductible/copay/coinsurance
    OTHER              = "OTHER"


@dataclass
class CARCAdjustment:
    """
    A single CAS segment adjustment from the 835.

    In X12 835 terms:
    - CAS segment = Claim Adjustment Segment
    - group_code: CO / PR / OA / PI
    - reason_code: CARC numeric code (e.g. 45, 97, 29)
    - amount: dollar amount of this adjustment

    WHY WE MODEL THIS EXPLICITLY:
    One claim can have multiple CAS adjustments.
    CO-45 (contractual adjustment) + PR-1 (deductible) + PR-2 (coinsurance)
    all appear together on a single claim.
    We need to separate them to correctly classify the reconciliation outcome.
    """
    group_code: str    # CO, PR, OA, PI
    reason_code: str   # CARC code number
    amount: float      # Dollar amount of adjustment
    description: str   # Human-readable CARC description


@dataclass
class PaymentVariance:
    """
    Variance between what was paid and what was contracted.

    WHY THIS EXISTS:
    An UNDERPAYMENT is not just "paid less than billed."
    It's "paid less than the contracted rate for this CPT code and payer."

    Billed: $450 | Contracted: $280 | Paid: $195
    Variance = $195 - $280 = -$85 (underpayment of $85, not $255)

    This distinction is critical for correct recovery calculations.
    Billing $450 and receiving $280 is correct (contractual adjustment).
    Billing $450 and receiving $195 when contract says $280 is recoverable.
    """
    claim_id: str
    payer: str
    procedure_code: str
    billed_amount: float
    contracted_rate: float      # From rate_configs/
    paid_amount: float
    variance_amount: float      # paid - contracted (negative = underpayment)
    variance_pct: float         # variance / contracted * 100
    is_recoverable: bool        # True if variance exceeds tolerance threshold
    recovery_action: str        # "Appeal with contract" / "Verify fee schedule" / etc.


@dataclass
class FeedbackRecommendation:
    """
    A recommended rule change for Project 1 (Healthcare Claims DQ Platform)
    or Project 2 (Intelligent Claim Routing Engine) based on observed
    denial patterns in the 835 remittance data.

    WHY THIS IS THE MOST VALUABLE OUTPUT:
    Reconciliation without feedback is just accounting.
    Reconciliation WITH feedback closes the loop:
    - Denials observed in 835 → rule changes in Project 1 → fewer denials next cycle

    This is what production RCM systems do. Most portfolios never model it.

    Examples:
    - CO-97 bundling denials for CPT 93005 → add 93005 to cpt_risk.json bundling category
    - CO-29 timely filing for CIGNA × 89 claims → reduce CIGNA alert threshold from 30 to 45 days
    - CO-15 prior auth for CPT 27447 × 34 AETNA claims → add 27447 to aetna required_fields
    """
    recommendation_id: str
    target_project: str          # "PROJECT_1_VALIDATION" or "PROJECT_2_ROUTING"
    target_config_file: str      # Which JSON config to update
    change_type: str             # "ADD_RULE" / "UPDATE_THRESHOLD" / "ADD_CPT_RISK"
    denial_category: DenialCategory
    payer: str
    carc_code: str
    affected_cpt: str
    denial_count: int            # How many times this pattern appeared
    revenue_impact: float        # Total revenue lost to this pattern
    recommendation: str          # Human-readable recommendation
    config_change: dict          # Exact JSON change to make


@dataclass
class ReconciliationResult:
    """
    Complete reconciliation result for one 837 claim.

    Matches a submitted claim (837) to its payment outcome (835)
    and classifies the result into one of 6 categories.
    """
    # 837 Claim fields
    claim_id: str
    patient_id: str
    payer: str
    billed_amount: float
    date_of_service: str
    procedure_code: str
    date_submitted: str

    # 835 Remittance fields (None if PENDING)
    remittance_date: Optional[str] = None
    paid_amount: Optional[float] = None
    allowed_amount: Optional[float] = None
    carc_codes: List[str] = field(default_factory=list)
    rarc_codes: List[str] = field(default_factory=list)
    adjustments: List[CARCAdjustment] = field(default_factory=list)
    check_number: Optional[str] = None

    # Reconciliation outputs
    status: ReconciliationStatus = ReconciliationStatus.PENDING
    denial_category: Optional[DenialCategory] = None
    variance: Optional[PaymentVariance] = None
    days_to_payment: Optional[int] = None

    # Calculated fields
    @property
    def patient_responsibility(self) -> float:
        """Sum of all PR (Patient Responsibility) adjustments."""
        return sum(a.amount for a in self.adjustments if a.group_code == "PR")

    @property
    def contractual_adjustment(self) -> float:
        """Sum of all CO (Contractual Obligation) adjustments."""
        return sum(a.amount for a in self.adjustments if a.group_code == "CO")

    @property
    def recovery_amount(self) -> float:
        """Dollar amount recoverable if underpaid."""
        if self.variance and self.variance.is_recoverable:
            return abs(self.variance.variance_amount)
        return 0.0

    @property
    def primary_carc(self) -> str:
        """First/primary CARC code on this claim."""
        return self.carc_codes[0] if self.carc_codes else ""

    def to_dict(self) -> dict:
        return {
            "claim_id":              self.claim_id,
            "patient_id":            self.patient_id,
            "payer":                 self.payer,
            "procedure_code":        self.procedure_code,
            "date_of_service":       self.date_of_service,
            "date_submitted":        self.date_submitted,
            "billed_amount":         self.billed_amount,
            "allowed_amount":        self.allowed_amount or 0.0,
            "paid_amount":           self.paid_amount or 0.0,
            "patient_responsibility":self.patient_responsibility,
            "contractual_adjustment":self.contractual_adjustment,
            "remittance_date":       self.remittance_date or "",
            "days_to_payment":       self.days_to_payment or "",
            "status":                self.status.value,
            "denial_category":       self.denial_category.value if self.denial_category else "",
            "carc_codes":            "|".join(self.carc_codes),
            "rarc_codes":            "|".join(self.rarc_codes),
            "primary_carc":          self.primary_carc,
            "contracted_rate":       self.variance.contracted_rate if self.variance else "",
            "variance_amount":       self.variance.variance_amount if self.variance else 0.0,
            "variance_pct":          self.variance.variance_pct if self.variance else 0.0,
            "recovery_amount":       self.recovery_amount,
            "check_number":          self.check_number or "",
        }
