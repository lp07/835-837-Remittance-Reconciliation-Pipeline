# 835/837 Remittance Reconciliation Pipeline — Analysis

**Run Date:** 2026-03-23
**Engine:** 835/837 Remittance Reconciliation Pipeline (Project 3 of 3)
**Input:** 1,200 submitted claims (837) + 1,141 remittance records (835)
**Processing Time:** < 1 second

---

## Executive Summary

1,200 submitted claims were reconciled against 1,141 payer remittance records across 5 payers. **631 claims (52.6%) were matched and paid as contracted.** 259 claims (21.6%) were denied, representing **$598,735.75 in denied revenue.** 111 claims (9.2%) were underpaid vs. contracted rates, surfacing a **$26,687.56 recovery pipeline.**

The feedback loop generated **77 rule change recommendations** for Projects 1 and 2, with **$578,533.03 in revenue impact** — giving the upstream validation and routing engines specific, evidence-based improvements to prevent these denials in future submission cycles.

---

## Reconciliation Status Distribution

| Status | Claims | % of Total | Total Billed | Total Paid |
|--------|--------|-----------|-------------|-----------|
| MATCHED | 631 | 52.6% | $1,141,497.26 | $381,333.53 |
| DENIAL | 259 | 21.6% | $598,735.75 | $0.00 |
| UNDERPAYMENT | 111 | 9.2% | $301,043.93 | $72,093.44 |
| CONTRACTUAL_ADJUSTMENT | 85 | 7.1% | $103,013.03 | $27,319.96 |
| PENDING | 59 | 4.9% | $72,835.43 | $0.00 |
| REVERSAL | 55 | 4.6% | $116,109.68 | $37,388.00 |
| **TOTAL** | **1,200** | **100%** | **$2,333,235.08** | **$518,134.93** |

**Overall Collection Rate: 22.2%**

The collection rate reflects the realistic gap between billed charges and actual reimbursement in healthcare — billed amounts are typically 2–4x contracted rates by design. The metrics that matter are underpayment detection and denial recovery, not the billed-to-paid ratio.

---

## Denial Analysis

### 259 Claims Denied — $598,735.75 in Denied Revenue

| Denial Category | Count | % of Denials | Revenue Impact |
|----------------|-------|-------------|----------------|
| TIMELY_FILING | 101 | 39.0% | ~$234,000 |
| DUPLICATE | 36 | 13.9% | ~$83,000 |
| BUNDLING | 34 | 13.1% | ~$79,000 |
| COVERAGE | 33 | 12.7% | ~$76,000 |
| MEDICAL_NECESSITY | 31 | 12.0% | ~$72,000 |
| PRIOR_AUTH | 24 | 9.3% | ~$56,000 |

### Why Timely Filing Dominates

Timely filing is the largest denial category (39% of all denials) because Cigna's 90-day filing window drives a disproportionate share of CO-29 denials. Claims submitted 85–95 days after DOS hit the wall on Cigna while the same claims would have 270+ days remaining with BCBS or Medicare.

This is a systemic, preventable pattern — not a coding error. The feedback loop recommendation: increase Cigna's timely filing urgency warning threshold in Project 2's routing configuration from 30 to 45 days, giving billing teams more advance warning before the window closes.

### Top CARC Codes

| CARC Code | Description | Count | Recoverable? |
|-----------|-------------|-------|-------------|
| CO-29 | Timely filing limit exceeded | 101 | No — write off |
| OA-18 | Duplicate claim | 36 | No — verify original |
| CO-97 | Bundled with another service | 34 | Yes — appeal with modifier -59 |
| CO-96 | Not covered under plan | 33 | No — bill patient |
| CO-50 | Not medically necessary | 31 | Yes — appeal with clinical notes |
| CO-15 | Prior authorization missing | 24 | Yes — obtain retro auth |

---

## Underpayment Recovery Pipeline

### 111 Claims Underpaid — $26,687.56 Recoverable

Underpayment is defined as: **paid amount < contracted rate** (beyond $10 / 3% tolerance threshold). This is distinct from contractual write-offs (CO-45) which represent expected reductions.

| Payer | Underpaid Claims | Recovery Amount |
|-------|-----------------|----------------|
| HUMANA | — | $8,885.58 |
| BCBS | — | $7,277.26 |
| AETNA | — | $6,954.35 |
| CIGNA | — | $2,449.10 |
| MEDICARE | — | $1,121.27 |
| **TOTAL** | **111** | **$26,687.56** |

**Humana and BCBS drive the most underpayment volume** — consistent with their higher contracted rates for complex procedures. When a payer pays $90 for a CPT code contracted at $142, the $52 variance exceeds both the $10 dollar tolerance and 3% percentage tolerance, triggering the underpayment flag.

### Recovery Methodology

Each underpayment generates a specific recovery action:

- **>30% below contract:** Formal appeal with contract rate documentation + pattern review for systematic payer misconfiguration
- **10-30% below contract:** Standard appeal referencing contracted rate + fee schedule page from payer contract
- **<10% below contract:** Corrected claim or informal appeal + verify fee schedule loaded correctly in billing system

---

## Payment Timing Analysis

Average days from claim submission to remittance receipt:

| Payer | Avg Days to Payment |
|-------|-------------------|
| BCBS | 30.2 days |
| CIGNA | 30.0 days |
| MEDICARE | 29.9 days |
| AETNA | 29.2 days |
| HUMANA | 28.9 days |

Industry benchmark: **Clean claims should be paid within 30 days.** All payers in this dataset are within the standard window, indicating no systematic payment delay issues.

---

## Feedback Loop — Rule Change Recommendations

**77 recommendations generated for Projects 1 and 2.**
**$578,533.03 in revenue impact addressed.**

This is the feature that closes the loop between outcome data and upstream prevention. Every denial pattern observed in the 835 becomes a specific recommendation to update validation or routing rules.

### Top 5 Recommendations by Revenue Impact

| Pattern | Target | Change | Revenue Impact |
|---------|--------|--------|----------------|
| CO-29 + CIGNA + CPT 22612 × 9 | Project 2 thresholds.json | Increase Cigna warning threshold to 45 days | $101,446.95 |
| CO-29 + CIGNA + CPT 27447 × 7 | Project 2 thresholds.json | Increase Cigna warning threshold to 45 days | $76,640.55 |
| CO-29 + CIGNA + CPT 43239 × 7 | Project 2 thresholds.json | Increase Cigna warning threshold to 45 days | $35,507.00 |
| CO-97 + BCBS + CPT 22612 × 2 | Project 2 cpt_risk.json | Add 22612 to bundling_risk codes | $30,527.04 |
| CO-96 + AETNA + CPT 22612 × 2 | Project 1 payer configs | Add coverage verification for AETNA + 22612 | $28,426.85 |

### How the Feedback Loop Works

```
835 Remittance Data
        ↓
Denial Pattern Analysis (feedback.py)
        ↓
Pattern: CO-97 (bundling) + CPT 93005 + BCBS × 23 claims
        ↓
Recommendation:
  Target: Project 2 — routing_configs/cpt_risk.json
  Change: Add '93005' to bundling_risk.codes array
  Effect: Claims with CPT 93005 now route to REVIEW queue
          Billing rep checks for modifier -59 before submission
          Bundling denials prevented upstream
        ↓
Next submission cycle: fewer CO-97 denials for CPT 93005
```

This is the mechanism that makes the three-project pipeline self-improving — not just reactive accounting, but evidence-based upstream rule refinement.

---

## Technical Architecture

### Matching Strategy

835s do NOT match 837s one-to-one — multiple 835 transactions may respond to a single 837, or one 835 may address multiple 837 submissions.

The engine handles this with a two-tier matching approach:
- **Primary match:** `claim_id` exact match — most reliable when IDs are consistent
- **Fallback match:** `patient_id + date_of_service + payer` composite key — handles ID mismatches common in production clearinghouse workflows

**Match rate this run: 95.1%** (1,141 of 1,200 claims matched). 59 claims remain PENDING — no 835 received, sitting in A/R queue.

### Classification Logic

Based on CARC group code semantics from CMS X12 835 standards:

| Group Code | Meaning | Classification Impact |
|-----------|---------|----------------------|
| CO | Contractual Obligation | Provider write-off — expected |
| PR | Patient Responsibility | Bill patient — separate from payer payment |
| OA | Other Adjustments | Reversals, duplicates |
| PI | Payer Initiated | Payer policy reduction |

### Underpayment Detection Thresholds

Tolerance applied before flagging underpayment: **$10 absolute OR 3% of contracted rate** (whichever is larger). Below this threshold, variance is considered normal rounding/adjustment noise. Above it, the claim enters the recovery pipeline with a specific appeal action.

---

## Connection to Projects 1 and 2

This is **Project 3** of a three-part RCM data pipeline:

```
EDI 837 Claims
      ↓
Project 1: Healthcare Claims DQ Platform
  → Validates fields, EDI 837 rules, payer-specific requirements
  → Output: validation_report.csv (status, error codes, revenue at risk)
      ↓
Project 2: Intelligent Claim Routing Engine
  → Scores denial risk (0-100), assigns queues, generates action worklist
  → Output: routed_claims.csv, action_worklist.csv
      ↓
Submit to Payer
      ↓
Project 3: 835/837 Remittance Reconciliation Pipeline (this project)
  → Matches payments to claims, classifies outcomes, detects underpayments
  → Output: reconciliation_report.csv, underpayment_pipeline.csv
      ↓
Feedback Loop → Updates Project 1 validation rules + Project 2 routing configs
  → Fewer denials in next submission cycle
```

---

*Generated by 835/837 Remittance Reconciliation Pipeline*
*github.com/lp07/835-837-Remittance-Reconciliation-Pipeline*

*All data is synthetically generated. No real patient, provider, or payer data is used.*
