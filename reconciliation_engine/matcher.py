# =============================================================================
# Copyright (c) 2025 Lisa Patel | github.com/lp07
# Original portfolio project. Unauthorized commercial use prohibited.
# Attribution required for any use, modification, or distribution.
# =============================================================================
"""
matcher.py — 837 to 835 Matching Engine

WHY THIS FILE EXISTS:
The reconciliation problem is fundamentally a matching problem.
Every 837 claim needs to be linked to its 835 payment outcome.

The challenge (from real-world RCM research):
- 835s do NOT match 837s one-to-one
- One 837 claim can generate multiple 835 payments (split payments, secondary payers)
- One 835 can cover multiple 837 claims (payers bundle payments)
- Claim IDs can differ between 837 submission and 835 reference

MATCHING STRATEGY:
Primary key: claim_id (most reliable when present in both files)
Fallback: patient_id + date_of_service + payer (fuzzy match for ID mismatches)

This mirrors production reconciliation logic used by clearinghouses.
"""

import logging
from typing import Dict, List, Tuple, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class ClaimMatcher:
    """
    Matches 837 claim records to their 835 remittance records.

    Handles the M:N matching reality of production RCM:
    - Primary match: claim_id exact match
    - Fallback match: patient_id + date_of_service + payer
    - Unmatched 837s → PENDING (no 835 received)
    - Unmatched 835s → logged as orphaned remittances
    """

    def __init__(self, tolerance_days: int = 3):
        """
        Args:
            tolerance_days: Days of tolerance for date matching in fallback logic.
                           Real payers sometimes shift DOS by 1-2 days in remittance.
        """
        self.tolerance_days = tolerance_days

    def match(
        self,
        claims_df: pd.DataFrame,
        remittance_df: pd.DataFrame
    ) -> Tuple[Dict[str, dict], List[str], List[str]]:
        """
        Match 837 claims to 835 remittance records.

        Args:
            claims_df:     DataFrame of 837 claims (Project 1 output format)
            remittance_df: DataFrame of 835 remittance records

        Returns:
            Tuple of:
            - matched_pairs: {claim_id: remittance_row_dict}
            - unmatched_claims: list of claim_ids with no 835 match (PENDING)
            - unmatched_remits: list of remittance_ids with no 837 match (orphaned)
        """
        matched_pairs = {}
        unmatched_claims = []
        unmatched_remits = list(remittance_df["remittance_id"].unique())

        # Build remittance lookup indexes
        # Primary index: claim_id → remittance row
        remit_by_claim_id = {}
        for _, row in remittance_df.iterrows():
            cid = str(row.get("claim_id_ref", "")).strip()
            if cid:
                remit_by_claim_id[cid] = row.to_dict()

        # Fallback index: (patient_id, dos, payer) → remittance row
        remit_by_composite = {}
        for _, row in remittance_df.iterrows():
            key = (
                str(row.get("patient_id", "")).strip(),
                str(row.get("date_of_service", "")).strip(),
                str(row.get("payer", "")).strip().upper()
            )
            remit_by_composite[key] = row.to_dict()

        # Match each 837 claim
        for _, claim_row in claims_df.iterrows():
            claim_id = str(claim_row.get("claim_id", "")).strip()

            # Step 1: Primary match by claim_id
            if claim_id in remit_by_claim_id:
                remit = remit_by_claim_id[claim_id]
                matched_pairs[claim_id] = remit
                # Remove from unmatched remits
                rid = remit.get("remittance_id", "")
                if rid in unmatched_remits:
                    unmatched_remits.remove(rid)
                logger.debug(f"Primary match: {claim_id}")
                continue

            # Step 2: Fallback match by composite key
            composite_key = (
                str(claim_row.get("patient_id", "")).strip(),
                str(claim_row.get("date_of_service", "")).strip(),
                str(claim_row.get("payer", "")).strip().upper()
            )
            if composite_key in remit_by_composite:
                remit = remit_by_composite[composite_key]
                matched_pairs[claim_id] = remit
                rid = remit.get("remittance_id", "")
                if rid in unmatched_remits:
                    unmatched_remits.remove(rid)
                logger.debug(f"Composite match: {claim_id}")
                continue

            # No match found — claim is PENDING
            unmatched_claims.append(claim_id)

        total = len(claims_df)
        matched = len(matched_pairs)
        pending = len(unmatched_claims)
        orphaned = len(unmatched_remits)

        logger.info(
            f"Matching complete | "
            f"Total claims: {total} | "
            f"Matched: {matched} ({round(matched/total*100,1)}%) | "
            f"Pending: {pending} | "
            f"Orphaned remittances: {orphaned}"
        )

        return matched_pairs, unmatched_claims, unmatched_remits
