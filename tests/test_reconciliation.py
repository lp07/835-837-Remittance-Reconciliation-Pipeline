# =============================================================================
# Copyright (c) 2025 Lisa Patel | github.com/lp07
# Original portfolio project. Unauthorized commercial use prohibited.
# Attribution required for any use, modification, or distribution.
# =============================================================================
"""
tests/test_reconciliation.py — Unit Tests for Reconciliation Engine
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from reconciliation_engine.models import (
    ReconciliationResult, ReconciliationStatus, DenialCategory
)
from reconciliation_engine.classifier import RemittanceClassifier
from reconciliation_engine.underpayment import UnderpaymentDetector
from reconciliation_engine.matcher import ClaimMatcher
import pandas as pd

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "carc_configs")
RATE_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rate_configs")


def make_result(**overrides):
    defaults = {
        "claim_id": "CLM000001", "patient_id": "PAT12345",
        "payer": "BCBS", "billed_amount": 450.0,
        "date_of_service": "2026-01-15", "procedure_code": "99214",
        "date_submitted": "2026-01-20",
    }
    defaults.update(overrides)
    return ReconciliationResult(**defaults)


def make_remittance(**overrides):
    defaults = {
        "remittance_id": "REM000001", "claim_id_ref": "CLM000001",
        "patient_id": "PAT12345", "payer": "BCBS",
        "date_of_service": "2026-01-15", "remittance_date": "2026-02-10",
        "billed_amount": 450.0, "allowed_amount": 142.0,
        "paid_amount": 142.0, "adjustment_amount": 308.0,
        "carc_codes": "45", "rarc_codes": "",
        "carc_group_code": "CO", "check_number": "CHK123456",
    }
    defaults.update(overrides)
    return defaults


# ─── Classifier Tests ─────────────────────────────────────────────────────────

class TestClassifier:

    @pytest.fixture
    def clf(self):
        return RemittanceClassifier(carc_config_dir=CONFIG_DIR)

    def test_matched_claim_classified_correctly(self, clf):
        result = make_result()
        remit = make_remittance(paid_amount=142.0, carc_codes="45", carc_group_code="CO")
        result = clf.classify(result, remit)
        assert result.status == ReconciliationStatus.MATCHED
        assert result.paid_amount == 142.0

    def test_denial_timely_filing_classified(self, clf):
        result = make_result()
        remit = make_remittance(paid_amount=0, allowed_amount=0,
                                carc_codes="29", carc_group_code="CO", adjustment_amount=450.0)
        result = clf.classify(result, remit)
        assert result.status == ReconciliationStatus.DENIAL
        assert result.denial_category == DenialCategory.TIMELY_FILING

    def test_denial_bundling_classified(self, clf):
        result = make_result()
        remit = make_remittance(paid_amount=0, allowed_amount=0,
                                carc_codes="97", carc_group_code="CO", adjustment_amount=450.0)
        result = clf.classify(result, remit)
        assert result.status == ReconciliationStatus.DENIAL
        assert result.denial_category == DenialCategory.BUNDLING

    def test_denial_prior_auth_classified(self, clf):
        result = make_result()
        remit = make_remittance(paid_amount=0, allowed_amount=0,
                                carc_codes="15", carc_group_code="CO", adjustment_amount=450.0)
        result = clf.classify(result, remit)
        assert result.status == ReconciliationStatus.DENIAL
        assert result.denial_category == DenialCategory.PRIOR_AUTH

    def test_reversal_classified(self, clf):
        result = make_result()
        remit = make_remittance(paid_amount=-142.0, carc_codes="72",
                                carc_group_code="PR", adjustment_amount=142.0)
        result = clf.classify(result, remit)
        assert result.status == ReconciliationStatus.REVERSAL

    def test_patient_responsibility_classified_as_contractual(self, clf):
        result = make_result()
        remit = make_remittance(paid_amount=107.0, allowed_amount=142.0,
                                carc_codes="45|1", carc_group_code="CO",
                                adjustment_amount=343.0)
        result = clf.classify(result, remit)
        assert result.status == ReconciliationStatus.CONTRACTUAL_ADJUST

    def test_days_to_payment_calculated(self, clf):
        result = make_result(date_submitted="2026-01-20")
        remit = make_remittance(remittance_date="2026-02-10", paid_amount=142.0)
        result = clf.classify(result, remit)
        assert result.days_to_payment == 21

    def test_carc_codes_populated(self, clf):
        result = make_result()
        remit = make_remittance(carc_codes="45|1", paid_amount=107.0)
        result = clf.classify(result, remit)
        assert "45" in result.carc_codes
        assert "1" in result.carc_codes


# ─── Underpayment Tests ───────────────────────────────────────────────────────

class TestUnderpaymentDetector:

    @pytest.fixture
    def det(self):
        return UnderpaymentDetector(rate_config_dir=RATE_DIR)

    def test_matched_payment_not_flagged(self, det):
        result = make_result(procedure_code="99214", payer="BCBS",
                             billed_amount=450.0)
        result.paid_amount = 142.0  # Exactly contracted
        result.status = ReconciliationStatus.MATCHED
        result = det.detect(result)
        assert result.status == ReconciliationStatus.MATCHED
        assert result.variance is None or not result.variance.is_recoverable

    def test_underpayment_detected(self, det):
        result = make_result(procedure_code="99214", payer="BCBS", billed_amount=450.0)
        result.paid_amount = 90.0   # Well below contracted $142
        result.status = ReconciliationStatus.MATCHED
        result = det.detect(result)
        assert result.status == ReconciliationStatus.UNDERPAYMENT
        assert result.variance is not None
        assert result.variance.is_recoverable
        assert result.variance.variance_amount < 0

    def test_recovery_amount_calculated(self, det):
        result = make_result(procedure_code="99214", payer="BCBS", billed_amount=450.0)
        result.paid_amount = 90.0
        result.status = ReconciliationStatus.MATCHED
        result = det.detect(result)
        assert result.recovery_amount > 0

    def test_denial_not_checked_for_underpayment(self, det):
        result = make_result()
        result.paid_amount = 0.0
        result.status = ReconciliationStatus.DENIAL
        result = det.detect(result)
        assert result.status == ReconciliationStatus.DENIAL

    def test_contracted_rate_lookup(self, det):
        rate = det.get_contracted_rate("BCBS", "99214")
        assert rate == 142.0

    def test_unknown_payer_returns_none(self, det):
        rate = det.get_contracted_rate("UNKNOWN_PAYER", "99213")
        assert rate is None

    def test_unknown_cpt_uses_default(self, det):
        rate = det.get_contracted_rate("BCBS", "XXXXX")
        assert rate == 85.0  # DEFAULT rate


# ─── Matcher Tests ────────────────────────────────────────────────────────────

class TestMatcher:

    @pytest.fixture
    def matcher(self):
        return ClaimMatcher()

    def test_primary_match_by_claim_id(self, matcher):
        claims = pd.DataFrame([{
            "claim_id": "CLM000001", "patient_id": "PAT111",
            "payer": "BCBS", "date_of_service": "2026-01-15"
        }])
        remits = pd.DataFrame([{
            "remittance_id": "REM000001", "claim_id_ref": "CLM000001",
            "patient_id": "PAT111", "payer": "BCBS",
            "date_of_service": "2026-01-15", "paid_amount": 100.0
        }])
        matched, unmatched, orphaned = matcher.match(claims, remits)
        assert "CLM000001" in matched
        assert len(unmatched) == 0

    def test_unmatched_claim_goes_to_pending(self, matcher):
        claims = pd.DataFrame([{
            "claim_id": "CLM999999", "patient_id": "PAT999",
            "payer": "CIGNA", "date_of_service": "2026-01-01"
        }])
        remits = pd.DataFrame([{
            "remittance_id": "REM000001", "claim_id_ref": "CLM000001",
            "patient_id": "PAT111", "payer": "BCBS",
            "date_of_service": "2026-01-15", "paid_amount": 100.0
        }])
        matched, unmatched, orphaned = matcher.match(claims, remits)
        assert "CLM999999" in unmatched
        assert len(matched) == 0

    def test_composite_fallback_match(self, matcher):
        claims = pd.DataFrame([{
            "claim_id": "CLM000001", "patient_id": "PAT111",
            "payer": "BCBS", "date_of_service": "2026-01-15"
        }])
        # Remit has different claim_id_ref but same patient/dos/payer
        remits = pd.DataFrame([{
            "remittance_id": "REM000001", "claim_id_ref": "",
            "patient_id": "PAT111", "payer": "BCBS",
            "date_of_service": "2026-01-15", "paid_amount": 100.0
        }])
        matched, unmatched, orphaned = matcher.match(claims, remits)
        assert "CLM000001" in matched


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
