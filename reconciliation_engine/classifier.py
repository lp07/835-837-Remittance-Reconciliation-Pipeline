"""
classifier.py — 835 Remittance Outcome Classifier

WHY THIS FILE EXISTS:
After matching a 837 claim to its 835 remittance, we need to classify
the payment outcome into one of 6 categories.

The classification logic is grounded in CARC group code semantics
from CMS X12 835 standards:

CO = Contractual Obligation → provider must write off
PR = Patient Responsibility → bill the patient
PI = Payer Initiated → payer policy reduction
OA = Other Adjustments → doesn't fit CO/PR/PI

CLASSIFICATION RULES (from CMS and X12 standards):

MATCHED:              paid > 0 AND only CO-45 adjustments (expected contractual)
                      paid_amount ≈ contracted_rate (within tolerance)

UNDERPAYMENT:         paid > 0 BUT paid_amount < contracted_rate (beyond tolerance)
                      Not explained by CO-45 alone

CONTRACTUAL_ADJUST:   paid > 0 AND combination of CO + PR adjustments
                      Patient has deductible/copay/coinsurance reducing payment

DENIAL:               paid == 0 AND CARC codes explain denial reason

REVERSAL:             negative payment OR CARC-72/OA reversal code present

PENDING:              no 835 match found
"""

import json
import logging
import os
from typing import Dict, Any, List

from reconciliation_engine.models import (
    ReconciliationStatus, DenialCategory,
    CARCAdjustment, ReconciliationResult
)

logger = logging.getLogger(__name__)


class RemittanceClassifier:
    """
    Classifies matched 837/835 pairs into reconciliation status categories.
    Uses CARC group codes and payment amounts to determine outcome.
    """

    def __init__(self, carc_config_dir: str = "carc_configs"):
        self._carc_config = self._load_carc_config(
            os.path.join(carc_config_dir, "carc_classifications.json")
        )
        # Build flat CARC → category lookup
        self._carc_to_category = self._build_carc_lookup()
        logger.info("RemittanceClassifier initialized.")

    def _load_carc_config(self, path: str) -> dict:
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"CARC config not found: {path}")
            return {}

    def _build_carc_lookup(self) -> Dict[str, str]:
        """Build {carc_code: category_name} dict for O(1) lookup."""
        lookup = {}
        for category, data in self._carc_config.get("carc_categories", {}).items():
            for code in data.get("codes", []):
                lookup[str(code)] = category
        return lookup

    def classify(
        self,
        result: ReconciliationResult,
        remittance_data: Dict[str, Any]
    ) -> ReconciliationResult:
        """
        Classify a matched claim's payment outcome.

        Populates:
        - result.status (ReconciliationStatus)
        - result.denial_category (if denied)
        - result.adjustments (list of CARCAdjustment)
        - result.paid_amount, allowed_amount, carc_codes, etc.

        Args:
            result:          RoutingResult with 837 fields already set
            remittance_data: Dict of 835 remittance fields

        Returns:
            Populated ReconciliationResult
        """
        # Extract 835 payment fields
        paid = float(remittance_data.get("paid_amount", 0) or 0)
        allowed = float(remittance_data.get("allowed_amount", paid) or paid)
        carc_str = str(remittance_data.get("carc_codes", ""))
        rarc_str = str(remittance_data.get("rarc_codes", ""))
        group_code = str(remittance_data.get("carc_group_code", "CO")).upper()
        adj_amount = float(remittance_data.get("adjustment_amount", 0) or 0)

        # Parse CARC/RARC codes
        carc_codes = [c.strip() for c in carc_str.split("|") if c.strip()]
        rarc_codes = [r.strip() for r in rarc_str.split("|") if r.strip()]

        # Build adjustment objects
        adjustments = self._build_adjustments(
            carc_codes, group_code, adj_amount, remittance_data
        )

        # Populate result fields
        result.paid_amount = paid
        result.allowed_amount = allowed
        result.carc_codes = carc_codes
        result.rarc_codes = rarc_codes
        result.adjustments = adjustments
        result.remittance_date = str(remittance_data.get("remittance_date", ""))
        result.check_number = str(remittance_data.get("check_number", ""))

        # Calculate days to payment
        result.days_to_payment = self._calc_days_to_payment(
            result.date_submitted,
            result.remittance_date
        )

        # ─── Classification Logic ──────────────────────────────────────
        # Step 1: Reversal check
        if paid < 0 or "72" in carc_codes:
            result.status = ReconciliationStatus.REVERSAL
            return result

        # Step 2: Denial check (zero payment with CARC)
        if paid == 0 and carc_codes:
            result.status = ReconciliationStatus.DENIAL
            result.denial_category = self._classify_denial(carc_codes, group_code)
            return result

        # Step 3: Zero payment without CARC — unusual, treat as pending
        if paid == 0:
            result.status = ReconciliationStatus.PENDING
            return result

        # Step 4: Positive payment — determine if matched, underpaid, or contractual
        has_patient_resp = any(a.group_code == "PR" for a in adjustments)

        if has_patient_resp:
            # Patient responsibility involved — contractual adjustment
            result.status = ReconciliationStatus.CONTRACTUAL_ADJUST
        else:
            # Pure payer payment — check against contracted rate in underpayment module
            # For now classify as MATCHED; underpayment.py will refine
            result.status = ReconciliationStatus.MATCHED

        return result

    def _build_adjustments(
        self,
        carc_codes: List[str],
        group_code: str,
        total_adj_amount: float,
        remittance_data: dict
    ) -> List[CARCAdjustment]:
        """Build CARCAdjustment objects from remittance data."""
        adjustments = []
        categories = self._carc_config.get("carc_categories", {})

        for code in carc_codes:
            category = self._carc_to_category.get(code, "OTHER")
            cat_data = categories.get(category, {})
            description = cat_data.get("description", f"CARC {code}")

            # Determine group code from CARC semantics
            effective_group = group_code
            if code in ["1", "2", "3"]:
                effective_group = "PR"  # Always patient responsibility
            elif code in ["45", "97", "4", "29", "50", "57", "96"]:
                effective_group = "CO"  # Always contractual
            elif code in ["18", "72"]:
                effective_group = "OA"

            # Split adjustment amount across CARC codes
            adj_per_code = total_adj_amount / max(len(carc_codes), 1)

            adjustments.append(CARCAdjustment(
                group_code=effective_group,
                reason_code=code,
                amount=round(adj_per_code, 2),
                description=description
            ))

        return adjustments

    def _classify_denial(
        self, carc_codes: List[str], group_code: str
    ) -> DenialCategory:
        """Map CARC codes to DenialCategory enum."""
        for code in carc_codes:
            category = self._carc_to_category.get(code, "")
            mapping = {
                "TIMELY_FILING":     DenialCategory.TIMELY_FILING,
                "BUNDLING":          DenialCategory.BUNDLING,
                "PRIOR_AUTH":        DenialCategory.PRIOR_AUTH,
                "MEDICAL_NECESSITY": DenialCategory.MEDICAL_NECESSITY,
                "DUPLICATE":         DenialCategory.DUPLICATE,
                "COVERAGE":          DenialCategory.COVERAGE,
                "TECHNICAL":         DenialCategory.TECHNICAL,
                "REVERSAL":          DenialCategory.OTHER,
            }
            if category in mapping:
                return mapping[category]

        # Fallback: use group code
        if group_code == "PR":
            return DenialCategory.PATIENT_RESP
        return DenialCategory.OTHER

    def _calc_days_to_payment(
        self, submitted: str, remit_date: str
    ) -> int:
        """Calculate days between claim submission and remittance."""
        from datetime import datetime
        try:
            sub = datetime.strptime(submitted[:10], "%Y-%m-%d")
            rem = datetime.strptime(remit_date[:10], "%Y-%m-%d")
            return max(0, (rem - sub).days)
        except (ValueError, TypeError):
            return 0
