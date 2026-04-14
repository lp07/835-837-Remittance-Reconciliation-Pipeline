# =============================================================================
# Copyright (c) 2025 Lisa Patel | github.com/lp07
# Original portfolio project. Unauthorized commercial use prohibited.
# Attribution required for any use, modification, or distribution.
# =============================================================================
"""
reporter.py — Reconciliation Report Generator

Four output files:
1. reconciliation_report.csv     — every claim with full reconciliation detail
2. underpayment_pipeline.csv     — underpaid claims sorted by recovery amount
3. denial_analysis.csv           — denial breakdown by CARC, payer, CPT
4. feedback_recommendations.json — rule changes for Project 1 and Project 2
"""

import json
import logging
import os
from typing import List
from datetime import datetime

import pandas as pd

from reconciliation_engine.models import (
    ReconciliationResult, ReconciliationStatus,
    FeedbackRecommendation
)

logger = logging.getLogger(__name__)


class ReconciliationReporter:

    def __init__(self, output_dir: str = "data/sample_output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_reconciliation_report(
        self, results: List[ReconciliationResult]
    ) -> str:
        """Full claim-level reconciliation report."""
        rows = [r.to_dict() for r in results]
        df = pd.DataFrame(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.output_dir, f"reconciliation_report_{ts}.csv")
        df.to_csv(path, index=False)
        logger.info(f"Reconciliation report saved: {path}")
        return path

    def generate_underpayment_pipeline(
        self, results: List[ReconciliationResult]
    ) -> str:
        """
        Recovery pipeline — underpaid claims sorted by recovery amount descending.
        This is the primary output for the revenue recovery team.
        """
        underpaid = [r for r in results if r.status == ReconciliationStatus.UNDERPAYMENT]
        if not underpaid:
            logger.info("No underpayments detected.")
            return ""

        rows = []
        for r in underpaid:
            v = r.variance
            rows.append({
                "claim_id":         r.claim_id,
                "patient_id":       r.patient_id,
                "payer":            r.payer,
                "procedure_code":   r.procedure_code,
                "date_of_service":  r.date_of_service,
                "billed_amount":    r.billed_amount,
                "contracted_rate":  v.contracted_rate if v else "",
                "paid_amount":      r.paid_amount,
                "variance_amount":  v.variance_amount if v else 0,
                "variance_pct":     v.variance_pct if v else 0,
                "recovery_amount":  r.recovery_amount,
                "carc_codes":       "|".join(r.carc_codes),
                "recovery_action":  v.recovery_action if v else "",
                "check_number":     r.check_number,
                "remittance_date":  r.remittance_date,
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("recovery_amount", ascending=False)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.output_dir, f"underpayment_pipeline_{ts}.csv")
        df.to_csv(path, index=False)
        logger.info(f"Underpayment pipeline saved: {path} ({len(df)} claims, ${df['recovery_amount'].sum():,.2f} total)")
        return path

    def generate_denial_analysis(
        self, results: List[ReconciliationResult]
    ) -> str:
        """Denial breakdown by CARC code, payer, and CPT."""
        denials = [r for r in results if r.status == ReconciliationStatus.DENIAL]
        if not denials:
            return ""

        rows = []
        for r in denials:
            rows.append({
                "claim_id":         r.claim_id,
                "payer":            r.payer,
                "procedure_code":   r.procedure_code,
                "date_of_service":  r.date_of_service,
                "billed_amount":    r.billed_amount,
                "primary_carc":     r.primary_carc,
                "all_carc_codes":   "|".join(r.carc_codes),
                "rarc_codes":       "|".join(r.rarc_codes),
                "denial_category":  r.denial_category.value if r.denial_category else "",
            })

        df = pd.DataFrame(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.output_dir, f"denial_analysis_{ts}.csv")
        df.to_csv(path, index=False)
        logger.info(f"Denial analysis saved: {path}")
        return path

    def generate_feedback_report(
        self, recommendations: List[FeedbackRecommendation]
    ) -> str:
        """Feedback recommendations for Project 1 and Project 2."""
        if not recommendations:
            return ""

        output = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_recommendations": len(recommendations),
            "total_revenue_impact": round(
                sum(r.revenue_impact for r in recommendations), 2
            ),
            "recommendations": [
                {
                    "recommendation_id":  r.recommendation_id,
                    "target_project":     r.target_project,
                    "target_config_file": r.target_config_file,
                    "change_type":        r.change_type,
                    "denial_category":    r.denial_category.value,
                    "payer":              r.payer,
                    "carc_code":          r.carc_code,
                    "affected_cpt":       r.affected_cpt,
                    "denial_count":       r.denial_count,
                    "revenue_impact":     r.revenue_impact,
                    "recommendation":     r.recommendation,
                    "config_change":      r.config_change,
                }
                for r in sorted(recommendations, key=lambda x: -x.revenue_impact)
            ]
        }

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.output_dir, f"feedback_recommendations_{ts}.json")
        with open(path, "w") as f:
            json.dump(output, f, indent=2)
        logger.info(f"Feedback recommendations saved: {path}")
        return path

    def print_summary(self, results: List[ReconciliationResult],
                      recommendations: List[FeedbackRecommendation]):
        """Console summary."""
        total = len(results)
        by_status = {}
        for r in results:
            k = r.status.value
            by_status[k] = by_status.get(k, {"count": 0, "billed": 0.0})
            by_status[k]["count"] += 1
            by_status[k]["billed"] += r.billed_amount

        total_billed = sum(r.billed_amount for r in results)
        total_paid = sum(r.paid_amount or 0 for r in results)
        total_recovery = sum(r.recovery_amount for r in results)
        underpaid = [r for r in results if r.status == ReconciliationStatus.UNDERPAYMENT]
        denials = [r for r in results if r.status == ReconciliationStatus.DENIAL]

        print("
" + "="*65)
        print("  835/837 REMITTANCE RECONCILIATION SUMMARY")
        print("="*65)
        print(f"  Total Claims:          {total}")
        print(f"  Total Billed:          ${total_billed:>12,.2f}")
        print(f"  Total Paid:            ${total_paid:>12,.2f}")
        print(f"  Collection Rate:       {round(total_paid/total_billed*100,1) if total_billed else 0}%")
        print(f"
  RECONCILIATION STATUS:")
        for status, data in sorted(by_status.items()):
            pct = round(data['count'] / total * 100, 1)
            print(f"    {status:<22} {data['count']:>4} ({pct:>5.1f}%)  ${data['billed']:>12,.2f}")
        print(f"
  RECOVERY PIPELINE:")
        print(f"    Underpaid claims:    {len(underpaid)}")
        print(f"    Recovery amount:     ${total_recovery:>12,.2f}")
        print(f"    Denied claims:       {len(denials)}")
        print(f"    Denied revenue:      ${sum(r.billed_amount for r in denials):>12,.2f}")
        print(f"
  FEEDBACK LOOP:")
        print(f"    Recommendations:     {len(recommendations)}")
        print(f"    Affected revenue:    ${sum(r.revenue_impact for r in recommendations):>12,.2f}")
        print("="*65 + "
")
