"""
main.py — 835/837 Remittance Reconciliation Pipeline Entry Point

HOW TO RUN:
    python main.py --generate                           # Generate data + reconcile
    python main.py                                      # Reconcile existing data
    python main.py --claims data/claims_837.csv \\
                   --remittance data/remittance_835.csv # Use specific files

PIPELINE FLOW:
1. Load 837 claims + 835 remittance files
2. Match claims to remittance (primary: claim_id, fallback: patient_id+DOS+payer)
3. Classify each matched pair (MATCHED/UNDERPAYMENT/DENIAL/etc.)
4. Detect underpayments vs contracted rates
5. Analyze denial patterns → generate Project 1/2 feedback recommendations
6. Output 4 report files + console summary
"""

import argparse
import logging
import os
import sys
import pandas as pd

from reconciliation_engine.matcher import ClaimMatcher
from reconciliation_engine.classifier import RemittanceClassifier
from reconciliation_engine.underpayment import UnderpaymentDetector
from reconciliation_engine.feedback import DenialFeedbackEngine
from reconciliation_engine.reporter import ReconciliationReporter
from reconciliation_engine.models import ReconciliationResult, ReconciliationStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(
        description="835/837 Remittance Reconciliation Pipeline"
    )
    p.add_argument("--claims",      default="data/claims_837.csv")
    p.add_argument("--remittance",  default="data/remittance_835.csv")
    p.add_argument("--output-dir",  default="data/sample_output")
    p.add_argument("--carc-config", default="carc_configs")
    p.add_argument("--rate-config", default="rate_configs")
    p.add_argument("--generate",    action="store_true")
    return p.parse_args()


def main():
    args = parse_args()

    # Generate sample data if needed
    if args.generate or not os.path.exists(args.claims):
        logger.info("Generating synthetic 837 claims and 835 remittance data...")
        from data.generate_sample_data import generate_datasets
        claims_df, remit_df = generate_datasets(1200)
        os.makedirs("data", exist_ok=True)
        claims_df.to_csv(args.claims, index=False)
        remit_df.to_csv(args.remittance, index=False)
        logger.info(f"Claims: {args.claims} | Remittance: {args.remittance}")

    # Load data
    try:
        claims_df    = pd.read_csv(args.claims)
        remittance_df = pd.read_csv(args.remittance)
        logger.info(f"Loaded {len(claims_df)} claims, {len(remittance_df)} remittances")
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        logger.error("Run with --generate to create sample data.")
        sys.exit(1)

    # Initialize engines
    matcher      = ClaimMatcher()
    classifier   = RemittanceClassifier(carc_config_dir=args.carc_config)
    underpayment = UnderpaymentDetector(rate_config_dir=args.rate_config)
    feedback     = DenialFeedbackEngine()
    reporter     = ReconciliationReporter(output_dir=args.output_dir)

    # Step 1: Match 837 to 835
    matched_pairs, unmatched_claims, orphaned_remits = matcher.match(
        claims_df, remittance_df
    )

    # Step 2: Classify each claim
    results = []
    for _, claim_row in claims_df.iterrows():
        claim_id = str(claim_row.get("claim_id", ""))

        # Build base result from 837 fields
        result = ReconciliationResult(
            claim_id=claim_id,
            patient_id=str(claim_row.get("patient_id", "")),
            payer=str(claim_row.get("payer", "")),
            billed_amount=float(claim_row.get("billed_amount", 0)),
            date_of_service=str(claim_row.get("date_of_service", "")),
            procedure_code=str(claim_row.get("procedure_code", "")),
            date_submitted=str(claim_row.get("date_submitted", "")),
        )

        if claim_id in matched_pairs:
            # Classify matched claim
            remit_data = matched_pairs[claim_id]
            result = classifier.classify(result, remit_data)
            result = underpayment.detect(result)
        else:
            # No 835 match — PENDING
            result.status = ReconciliationStatus.PENDING

        results.append(result)

    # Step 3: Analyze denial patterns → feedback recommendations
    recommendations = feedback.analyze(results)

    # Step 4: Generate reports
    recon_path     = reporter.generate_reconciliation_report(results)
    underpay_path  = reporter.generate_underpayment_pipeline(results)
    denial_path    = reporter.generate_denial_analysis(results)
    feedback_path  = reporter.generate_feedback_report(recommendations)

    # Step 5: Print summary
    reporter.print_summary(results, recommendations)

    print(f"Reports saved to: {args.output_dir}/")
    print(f"  Reconciliation:       {os.path.basename(recon_path)}")
    if underpay_path:
        print(f"  Underpayment pipeline:{os.path.basename(underpay_path)}")
    if denial_path:
        print(f"  Denial analysis:      {os.path.basename(denial_path)}")
    if feedback_path:
        print(f"  Feedback recs:        {os.path.basename(feedback_path)}")


if __name__ == "__main__":
    main()
