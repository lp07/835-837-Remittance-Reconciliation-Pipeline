# =============================================================================
# Copyright (c) 2025 Lisa Patel | github.com/lp07
# Original portfolio project. Unauthorized commercial use prohibited.
# Attribution required for any use, modification, or distribution.
# =============================================================================
"""
feedback.py — Denial Pattern Analysis and Project 1 Feedback Loop

WHY THIS FILE EXISTS:
This is the feature that closes the loop between Project 3 and Project 1.

Reconciliation without feedback is just accounting.
With feedback, every denial pattern observed in the 835 becomes
a specific recommendation to improve upstream validation rules.

HOW IT WORKS:
1. Analyze all DENIAL results — group by CARC code + payer + CPT
2. Identify patterns that exceed frequency thresholds
3. For each pattern, generate a specific recommendation:
   - What config file to update in Project 1 or Project 2
   - What change to make (add CPT to risk list, update threshold, etc.)
   - Exact JSON change to make
   - Revenue impact of this pattern

EXAMPLES OF FEEDBACK:
Pattern: CO-97 (bundling) + CPT 93005 + BCBS × 23 claims = $2,760 denied
→ Add 93005 to cpt_risk.json bundling_risk category in Project 2

Pattern: CO-29 (timely filing) + CIGNA × 89 claims = $41,580 denied
→ Reduce CIGNA timely filing urgency threshold from 30 to 45 days in Project 2

Pattern: CO-15 (prior auth) + CPT 27447 + AETNA × 34 claims = $124,100 denied
→ Add aetna.json required_fields entry for authorization_number when CPT=27447

This is what production RCM platforms (MD Clarity RevFind, Waystar) do.
Most portfolios never model the feedback loop.
"""

import logging
import uuid
from typing import List, Dict, Tuple
from collections import defaultdict

from reconciliation_engine.models import (
    ReconciliationResult, ReconciliationStatus,
    DenialCategory, FeedbackRecommendation
)

logger = logging.getLogger(__name__)

# Minimum denial count before generating a recommendation
FREQUENCY_THRESHOLD = 5
# Minimum revenue impact before generating a recommendation
REVENUE_THRESHOLD = 500.0


class DenialFeedbackEngine:
    """
    Analyzes denial patterns from reconciled claims and generates
    specific configuration change recommendations for Project 1 and Project 2.
    """

    def analyze(
        self, results: List[ReconciliationResult]
    ) -> List[FeedbackRecommendation]:
        """
        Analyze all denial results and generate feedback recommendations.

        Args:
            results: All ReconciliationResult objects from this batch

        Returns:
            List of FeedbackRecommendation objects
        """
        denials = [r for r in results if r.status == ReconciliationStatus.DENIAL]

        if not denials:
            logger.info("No denials found. No feedback recommendations generated.")
            return []

        logger.info(f"Analyzing {len(denials)} denial records for patterns...")

        # Aggregate denial patterns
        # Key: (carc_code, payer, procedure_code) → (count, revenue_impact)
        pattern_counts: Dict[Tuple, int] = defaultdict(int)
        pattern_revenue: Dict[Tuple, float] = defaultdict(float)
        pattern_categories: Dict[Tuple, DenialCategory] = {}

        for result in denials:
            primary_carc = result.primary_carc or "UNKNOWN"
            key = (primary_carc, result.payer, result.procedure_code)
            pattern_counts[key] += 1
            pattern_revenue[key] += result.billed_amount
            if result.denial_category:
                pattern_categories[key] = result.denial_category

        # Generate recommendations for patterns exceeding thresholds
        recommendations = []
        for key, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            carc_code, payer, cpt = key
            revenue = pattern_revenue[key]
            category = pattern_categories.get(key, DenialCategory.OTHER)

            if count < FREQUENCY_THRESHOLD and revenue < REVENUE_THRESHOLD:
                continue

            rec = self._build_recommendation(
                carc_code, payer, cpt, count, revenue, category
            )
            if rec:
                recommendations.append(rec)

        logger.info(f"Generated {len(recommendations)} feedback recommendations.")
        return recommendations

    def _build_recommendation(
        self,
        carc_code: str,
        payer: str,
        cpt: str,
        count: int,
        revenue: float,
        category: DenialCategory
    ) -> FeedbackRecommendation:
        """Build a specific recommendation based on denial pattern."""

        rec_id = f"FEEDBACK_{carc_code}_{payer}_{cpt}_{str(uuid.uuid4())[:6].upper()}"

        # ─── Timely Filing Denials ────────────────────────────────────────────
        if category == DenialCategory.TIMELY_FILING:
            return FeedbackRecommendation(
                recommendation_id=rec_id,
                target_project="PROJECT_2_ROUTING",
                target_config_file="routing_configs/payer_risk.json",
                change_type="UPDATE_THRESHOLD",
                denial_category=category,
                payer=payer,
                carc_code=carc_code,
                affected_cpt=cpt,
                denial_count=count,
                revenue_impact=round(revenue, 2),
                recommendation=(
                    f"TIMELY FILING PATTERN: {count} claims denied (CO-29) for {payer}. "
                    f"${revenue:,.2f} lost. "
                    f"Recommendation: Reduce {payer} timely filing urgency threshold in "
                    f"routing_configs/thresholds.json. "
                    f"Increase 'warning_days_remaining' from 30 to 45 days for {payer} "
                    f"to give billing team more advance warning."
                ),
                config_change={
                    "file": "routing_configs/thresholds.json",
                    "change": f"Increase timely_filing_urgency.warning_days_remaining to 45 for {payer}",
                    "rationale": f"{count} claims exceeded {payer} filing window in this batch"
                }
            )

        # ─── Bundling Denials ─────────────────────────────────────────────────
        elif category == DenialCategory.BUNDLING:
            return FeedbackRecommendation(
                recommendation_id=rec_id,
                target_project="PROJECT_2_ROUTING",
                target_config_file="routing_configs/cpt_risk.json",
                change_type="ADD_CPT_RISK",
                denial_category=category,
                payer=payer,
                carc_code=carc_code,
                affected_cpt=cpt,
                denial_count=count,
                revenue_impact=round(revenue, 2),
                recommendation=(
                    f"BUNDLING PATTERN: CPT {cpt} denied {count} times for bundling (CO-97/CO-4) "
                    f"by {payer}. ${revenue:,.2f} impact. "
                    f"Recommendation: Add CPT {cpt} to 'bundling_risk' category in "
                    f"routing_configs/cpt_risk.json. "
                    f"This will increase risk score for claims with this code, "
                    f"routing them to REVIEW queue for modifier -59 check before submission."
                ),
                config_change={
                    "file": "routing_configs/cpt_risk.json",
                    "change": f"Add '{cpt}' to risk_categories.bundling_risk.codes array",
                    "rationale": f"CO-97/CO-4 bundling denial observed {count}x for {payer}"
                }
            )

        # ─── Prior Authorization Denials ──────────────────────────────────────
        elif category == DenialCategory.PRIOR_AUTH:
            return FeedbackRecommendation(
                recommendation_id=rec_id,
                target_project="PROJECT_1_VALIDATION",
                target_config_file=f"payer_configs/{payer.lower()}.json",
                change_type="ADD_RULE",
                denial_category=category,
                payer=payer,
                carc_code=carc_code,
                affected_cpt=cpt,
                denial_count=count,
                revenue_impact=round(revenue, 2),
                recommendation=(
                    f"PRIOR AUTH PATTERN: CPT {cpt} denied {count} times for missing "
                    f"prior authorization (CO-15) by {payer}. ${revenue:,.2f} impact. "
                    f"Recommendation: Add 'authorization_number' as a required field "
                    f"for CPT {cpt} in {payer.lower()}.json payer config in Project 1. "
                    f"Claims with this CPT and no auth number will be flagged before submission."
                ),
                config_change={
                    "file": f"payer_configs/{payer.lower()}.json",
                    "change": {
                        "field": "authorization_number",
                        "error_code": f"{payer[:3]}_AUTH_{cpt}",
                        "message": f"{payer} requires prior authorization for CPT {cpt}.",
                        "severity": "CRITICAL",
                        "edi_segment": "REF",
                        "condition": f"procedure_code == '{cpt}'"
                    },
                    "rationale": f"CO-15 prior auth denial observed {count}x for {payer} + CPT {cpt}"
                }
            )

        # ─── Technical Denials ────────────────────────────────────────────────
        elif category == DenialCategory.TECHNICAL:
            return FeedbackRecommendation(
                recommendation_id=rec_id,
                target_project="PROJECT_1_VALIDATION",
                target_config_file="claims_validator/rules.py",
                change_type="ADD_RULE",
                denial_category=category,
                payer=payer,
                carc_code=carc_code,
                affected_cpt=cpt,
                denial_count=count,
                revenue_impact=round(revenue, 2),
                recommendation=(
                    f"TECHNICAL DENIAL PATTERN: {count} technical denials (CARC {carc_code}) "
                    f"for {payer} + CPT {cpt}. ${revenue:,.2f} impact. "
                    f"Review Project 1 validation rules for CARC {carc_code}. "
                    f"This denial type should be catchable pre-submission. "
                    f"Consider adding or strengthening the corresponding validation rule."
                ),
                config_change={
                    "file": "claims_validator/rules.py",
                    "change": f"Review/add validation rule for CARC {carc_code} denial pattern",
                    "rationale": f"CARC {carc_code} technical denial observed {count}x for {payer}"
                }
            )

        # ─── Medical Necessity Denials ────────────────────────────────────────
        elif category == DenialCategory.MEDICAL_NECESSITY:
            return FeedbackRecommendation(
                recommendation_id=rec_id,
                target_project="PROJECT_2_ROUTING",
                target_config_file="routing_configs/cpt_risk.json",
                change_type="ADD_CPT_RISK",
                denial_category=category,
                payer=payer,
                carc_code=carc_code,
                affected_cpt=cpt,
                denial_count=count,
                revenue_impact=round(revenue, 2),
                recommendation=(
                    f"MEDICAL NECESSITY PATTERN: CPT {cpt} denied {count} times for "
                    f"medical necessity (CO-50/CO-57) by {payer}. ${revenue:,.2f} impact. "
                    f"Recommendation: Add CPT {cpt} to 'medical_necessity_scrutiny' in "
                    f"routing_configs/cpt_risk.json. Claims with this code will route to "
                    f"REVIEW queue for diagnosis/documentation check before submission."
                ),
                config_change={
                    "file": "routing_configs/cpt_risk.json",
                    "change": f"Add '{cpt}' to risk_categories.medical_necessity_scrutiny.codes",
                    "rationale": f"CO-50 medical necessity denial observed {count}x for {payer}"
                }
            )

        # ─── Default: Other patterns ──────────────────────────────────────────
        else:
            return FeedbackRecommendation(
                recommendation_id=rec_id,
                target_project="PROJECT_1_VALIDATION",
                target_config_file="general",
                change_type="REVIEW",
                denial_category=category,
                payer=payer,
                carc_code=carc_code,
                affected_cpt=cpt,
                denial_count=count,
                revenue_impact=round(revenue, 2),
                recommendation=(
                    f"DENIAL PATTERN (CARC {carc_code}): {count} claims denied for {payer} "
                    f"+ CPT {cpt}. ${revenue:,.2f} impact. "
                    f"Category: {category.value}. "
                    f"Manual review recommended to determine appropriate upstream rule change."
                ),
                config_change={
                    "file": "general",
                    "change": "Manual review required",
                    "rationale": f"CARC {carc_code} denial pattern requires domain expert review"
                }
            )
