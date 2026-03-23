"""
underpayment.py — Contracted Rate Comparison and Underpayment Detection

WHY THIS FILE EXISTS:
An underpayment is NOT simply "paid less than billed."
It is "paid less than the contracted rate for this CPT and payer."

Real-world example from MD Clarity research:
  Billed:       $450
  Contracted:   $280   (what payer agreed to pay)
  Paid:         $195   (what payer actually paid)
  Variance:     -$85   (underpayment — recoverable)
  CO-45 adj:    $170   (expected contractual write-off — not recoverable)

Without contracted rates, you can't detect the -$85 underpayment.
You'd just see "paid $195 vs billed $450" and write off the whole $255.
$85 of that is recoverable — but only if you know the contract says $280.

RESEARCH BASIS:
MD Clarity's RevFind, revenue cycle best practices (revenuecycleblog.com),
and MBW RCM underpayment recovery guides all confirm:
- Compare paid vs contracted (not billed) to detect true underpayments
- Use configurable tolerance thresholds (typically $5-$10 or 2-5%)
- Classify variances by type: true underpayment, config gap, expected
"""

import json
import logging
import os
from typing import Dict, Optional

from reconciliation_engine.models import (
    ReconciliationResult, ReconciliationStatus,
    PaymentVariance
)

logger = logging.getLogger(__name__)

# Tolerance below which variance is considered noise (not a true underpayment)
# Based on industry practice: $10 or 3% — whichever is lower
DOLLAR_TOLERANCE = 10.00
PCT_TOLERANCE = 3.0


class UnderpaymentDetector:
    """
    Compares paid amounts to contracted rates and flags underpayments.
    Updates ReconciliationResult.status from MATCHED → UNDERPAYMENT when warranted.
    """

    def __init__(self, rate_config_dir: str = "rate_configs"):
        self.rate_config_dir = rate_config_dir
        self._rate_tables: Dict[str, dict] = {}
        self._load_all_rates()
        logger.info(f"UnderpaymentDetector initialized. Payers loaded: {list(self._rate_tables.keys())}")

    def _load_all_rates(self):
        """Load all payer rate configs at startup."""
        if not os.path.exists(self.rate_config_dir):
            logger.warning(f"Rate config dir not found: {self.rate_config_dir}")
            return

        for filename in os.listdir(self.rate_config_dir):
            if filename.endswith(".json"):
                payer = filename.replace(".json", "").upper()
                path = os.path.join(self.rate_config_dir, filename)
                try:
                    with open(path) as f:
                        data = json.load(f)
                        self._rate_tables[payer] = data.get("rates", {})
                except Exception as e:
                    logger.error(f"Failed to load rate config {filename}: {e}")

    def get_contracted_rate(self, payer: str, procedure_code: str) -> Optional[float]:
        """
        Look up contracted rate for a payer/CPT combination.

        Falls back to DEFAULT rate if specific CPT not in contract.
        Returns None if payer not in rate tables.
        """
        payer_upper = payer.upper().strip()
        rates = self._rate_tables.get(payer_upper)
        if not rates:
            return None

        cpt = str(procedure_code).strip().upper()
        return rates.get(cpt, rates.get("DEFAULT"))

    def detect(self, result: ReconciliationResult) -> ReconciliationResult:
        """
        Check if a MATCHED or CONTRACTUAL_ADJUST claim is actually underpaid.

        Only runs on claims with positive payment amounts.
        Updates result.status and result.variance if underpayment detected.

        Args:
            result: ReconciliationResult with paid_amount populated

        Returns:
            Updated ReconciliationResult
        """
        # Only check positive-payment claims
        if result.paid_amount is None or result.paid_amount <= 0:
            return result

        # Skip denials, reversals, pending
        if result.status in [
            ReconciliationStatus.DENIAL,
            ReconciliationStatus.REVERSAL,
            ReconciliationStatus.PENDING
        ]:
            return result

        # Look up contracted rate
        contracted = self.get_contracted_rate(result.payer, result.procedure_code)
        if contracted is None:
            logger.debug(f"No contracted rate for {result.payer}/{result.procedure_code}")
            return result

        # Calculate effective payment (paid + patient responsibility)
        # Patient responsibility reduces payer payment — it's not an underpayment
        patient_resp = result.patient_responsibility
        effective_payer_payment = result.paid_amount

        # Variance = what payer paid vs what contract says payer should pay
        # (patient responsibility is separate — payer is off the hook for PR amounts)
        expected_payer_payment = contracted - patient_resp
        variance = effective_payer_payment - expected_payer_payment
        variance_pct = (variance / contracted * 100) if contracted > 0 else 0

        # Determine if variance exceeds tolerance
        is_underpayment = (
            variance < 0 and
            abs(variance) > DOLLAR_TOLERANCE and
            abs(variance_pct) > PCT_TOLERANCE
        )

        # Build variance object
        if is_underpayment:
            action = self._get_recovery_action(variance_pct, result.payer)
            result.variance = PaymentVariance(
                claim_id=result.claim_id,
                payer=result.payer,
                procedure_code=result.procedure_code,
                billed_amount=result.billed_amount,
                contracted_rate=contracted,
                paid_amount=result.paid_amount,
                variance_amount=round(variance, 2),
                variance_pct=round(variance_pct, 1),
                is_recoverable=True,
                recovery_action=action
            )
            result.status = ReconciliationStatus.UNDERPAYMENT
            logger.debug(
                f"Underpayment detected: {result.claim_id} | "
                f"{result.payer} | {result.procedure_code} | "
                f"Contracted: ${contracted} | Paid: ${result.paid_amount} | "
                f"Variance: ${variance:.2f}"
            )
        elif variance < 0:
            # Below tolerance — expected variance, not worth pursuing
            result.variance = PaymentVariance(
                claim_id=result.claim_id,
                payer=result.payer,
                procedure_code=result.procedure_code,
                billed_amount=result.billed_amount,
                contracted_rate=contracted,
                paid_amount=result.paid_amount,
                variance_amount=round(variance, 2),
                variance_pct=round(variance_pct, 1),
                is_recoverable=False,
                recovery_action="Within tolerance — no action needed"
            )

        return result

    def _get_recovery_action(self, variance_pct: float, payer: str) -> str:
        """Generate specific recovery action based on variance size."""
        abs_pct = abs(variance_pct)
        if abs_pct > 30:
            return (
                f"Significant underpayment ({abs_pct:.1f}% below contract). "
                f"Submit formal appeal to {payer} with contract rate documentation. "
                "Consider pattern review for systematic payer misconfiguration."
            )
        elif abs_pct > 10:
            return (
                f"Material underpayment ({abs_pct:.1f}% below contract). "
                f"Submit appeal to {payer} referencing contracted rate. "
                "Attach fee schedule page from payer contract."
            )
        else:
            return (
                f"Minor underpayment ({abs_pct:.1f}% below contract). "
                f"Submit corrected claim or appeal to {payer}. "
                "Verify fee schedule is loaded correctly in billing system."
            )
