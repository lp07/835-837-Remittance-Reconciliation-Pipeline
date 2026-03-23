# 835/837 Remittance Reconciliation Pipeline

A production-grade reconciliation engine that matches EDI 837 claim submissions to EDI 835 remittance payments, classifies each outcome using CARC group code semantics, detects underpayments against contracted rates, and feeds denial patterns back upstream to improve validation and routing rules.

This is **Project 3 of a three-part integrated RCM data pipeline.** It closes the loop between what was submitted (Project 1), what was routed for action (Project 2), and what payers actually paid or denied.

---

## The Problem This Solves

After claims are submitted to payers, three problems arise that most RCM systems handle poorly:

**1. Reconciliation is manual and slow.**
Matching 835 remittance files to 837 claims is complex — 835s don't match 837s one-to-one. Payers bundle multiple claim payments into single deposits. Manual reconciliation takes hundreds of staff hours per week.

**2. Underpayments go undetected.**
Payers routinely pay less than the contracted rate. Without automated comparison against contracted rates (not billed amounts), these variances are silently written off. A practice with $80M in collections losing 3% to underpayments loses $2.4M annually in fully recoverable revenue.

**3. Denial patterns don't improve upstream rules.**
Every CO-97 bundling denial, every CO-29 timely filing violation — these are data points that should make the next submission cycle cleaner. Without a feedback loop, the same denials repeat indefinitely.

This engine solves all three.

---

## Full Pipeline Architecture

```
Project 1: Healthcare Claims DQ Platform
  → Validates EDI 837 fields before submission
  → Output: validation_report.csv
         ↓
Project 2: Intelligent Claim Routing Engine
  → Scores denial risk, assigns queues, generates action worklist
  → Output: routed_claims.csv, action_worklist.csv
         ↓
  Submit to Payer
         ↓
Project 3: 835/837 Remittance Reconciliation Pipeline (this repo)
  → Matches 837 to 835, classifies outcomes, detects underpayments
  → Output: reconciliation_report.csv, underpayment_pipeline.csv
         ↓
  Feedback Loop → Updates Project 1 + Project 2 configs
  → Fewer denials next cycle
```

---

## Architecture

```
┌─────────────────────────┐  ┌─────────────────────────┐
│   837 Claims CSV         │  │   835 Remittance CSV      │
│  (what was submitted)    │  │  (what payer paid/denied) │
└──────────┬──────────────┘  └──────────┬──────────────┘
           │                            │
           └──────────┬─────────────────┘
                      ▼
           ┌─────────────────────┐
           │    ClaimMatcher      │  ← Primary: claim_id match
           │                     │    Fallback: patient+DOS+payer
           └──────────┬──────────┘
                      ▼
           ┌─────────────────────┐
           │ RemittanceClassifier │  ← CARC group codes → 6 status categories
           └──────────┬──────────┘
                      ▼
           ┌─────────────────────┐
           │ UnderpaymentDetector │  ← paid vs contracted rate → variance
           └──────────┬──────────┘
                      ▼
           ┌─────────────────────┐
           │  DenialFeedbackEngine│  ← denial patterns → Project 1/2 recommendations
           └──────────┬──────────┘
                      ▼
           ┌─────────────────────┐
           │  ReconciliationReporter│ ← 4 output files
           └─────────────────────┘
```

---

## Six Reconciliation Classifications

Based on CARC group code semantics from CMS X12 835 standards:

| Status | CARC Group | Meaning | Action |
|--------|-----------|---------|--------|
| MATCHED | CO only | Paid per contracted rate | Post payment |
| UNDERPAYMENT | CO + variance | Paid less than contracted rate | Appeal with contract |
| CONTRACTUAL_ADJUSTMENT | CO + PR | Expected patient responsibility | Bill patient |
| DENIAL | CO/OA (zero paid) | Claim denied — CARC explains why | Correct and resubmit / appeal |
| REVERSAL | PR/OA negative | Previously paid, taken back | Investigate |
| PENDING | None | No 835 received yet | Follow up |

---

## Sample Run Results

1,200 claims reconciled across BCBS, Aetna, Cigna, Humana, Medicare:

```
=================================================================
  835/837 REMITTANCE RECONCILIATION SUMMARY
=================================================================
  Total Claims:          1,200
  Total Billed:          $2,333,235.08
  Total Paid:            $  518,134.93
  Collection Rate:       22.2%

  RECONCILIATION STATUS:
    MATCHED                  631 ( 52.6%)  $1,141,497.26
    DENIAL                   259 ( 21.6%)  $  598,735.75
    UNDERPAYMENT             111 (  9.2%)  $  301,043.93
    CONTRACTUAL_ADJUSTMENT    85 (  7.1%)  $  103,013.03
    PENDING                   59 (  4.9%)  $   72,835.43
    REVERSAL                  55 (  4.6%)  $  116,109.68

  RECOVERY PIPELINE:
    Underpaid claims:    111
    Recovery amount:     $   26,687.56
    Denied claims:       259
    Denied revenue:      $  598,735.75

  FEEDBACK LOOP:
    Recommendations:     77
    Affected revenue:    $  578,533.03
=================================================================
```

---

## Project Structure

```
835-837-remittance-reconciliation-pipeline/
│
├── reconciliation_engine/
│   ├── __init__.py          # Package exports
│   ├── models.py            # ReconciliationResult, PaymentVariance, FeedbackRecommendation
│   ├── matcher.py           # 837-to-835 matching (primary + fallback logic)
│   ├── classifier.py        # CARC-based 6-category classification
│   ├── underpayment.py      # Contracted rate comparison + variance detection
│   ├── feedback.py          # Denial pattern analysis → Project 1/2 recommendations
│   └── reporter.py          # 4-format output generation
│
├── rate_configs/
│   ├── bcbs.json            # BCBS contracted rates per CPT
│   ├── aetna.json           # Aetna contracted rates
│   ├── cigna.json           # Cigna contracted rates
│   ├── humana.json          # Humana contracted rates
│   └── medicare.json        # Medicare Fee Schedule 2026
│
├── carc_configs/
│   └── carc_classifications.json  # CARC code → denial category mapping
│
├── data/
│   ├── generate_sample_data.py    # Generates 837 claims + 835 remittance
│   └── sample_output/             # 4 output files + analysis
│
├── tests/
│   └── test_reconciliation.py     # 14 unit tests
│
├── main.py                  # CLI entry point
└── requirements.txt
```

---

## Tech Stack and Why

| Technology | Why Used |
|------------|----------|
| **Python** | Industry standard for RCM data pipelines |
| **Pandas** | Efficient batch processing and aggregation of 1,200+ claim/remittance records |
| **Dataclasses** | Typed, auditable models — ReconciliationResult carries full audit trail |
| **Enums** | Type-safe status and category values — no string typos in production |
| **JSON configs** | Contracted rates and CARC classifications updatable without code changes |
| **pytest** | 14 unit tests covering matching, classification, and underpayment detection |

---

## How to Run

```bash
git clone https://github.com/lp07/835-837-Remittance-Reconciliation-Pipeline.git
cd 835-837-Remittance-Reconciliation-Pipeline
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Generate sample data and reconcile
python main.py --generate

# Use specific input files
python main.py --claims data/claims_837.csv --remittance data/remittance_835.csv

# Run tests
python -m pytest tests/test_reconciliation.py -v
```

---

## Design Decisions

**Why CARC group codes for classification:**
The difference between CO and PR adjustments is the difference between a provider write-off and patient billing. CO-45 = write off. PR-1 = bill the patient. Getting this wrong means billing patients for amounts they don't owe. The CARC group code logic is from CMS X12 835 standards — this is how production clearinghouses classify payments.

**Why compare paid vs contracted (not billed):**
Billed amounts are intentionally inflated 2–4x the contracted rate. A $450 bill paid at $142 is correct if the contract says $142. A $450 bill paid at $90 is an underpayment of $52 — not $308. Without contracted rates, you can't detect the $52 — you'd just write off the entire $360 difference. MD Clarity's research confirms this is the core problem most practices miss.

**Why a feedback loop:**
Reconciliation without feedback is just accounting. The same denials repeat in the next submission cycle. The feedback loop converts observed denial patterns (CARC codes + payer + CPT combinations) into specific, actionable configuration changes for Projects 1 and 2. This mirrors what production platforms like MD Clarity RevFind and Waystar do — treating the revenue cycle as a learning system, not a static workflow.

**Why two-tier matching:**
Production 835 files frequently have claim ID mismatches — clearinghouse systems sometimes alter or truncate the claim control number between submission and remittance. The fallback composite match (patient_id + DOS + payer) handles this without requiring perfect ID consistency. This is documented in the CMS Medicare Claims Processing Manual Chapter 22.

---

## Part of a Three-Project RCM Pipeline

| Project | Repo | What It Does |
|---------|------|-------------|
| 1 — Claims DQ Platform | [Healthcare-Claims-Data-Quality-Intelligent-Platform](https://github.com/lp07/Healthcare-Claims-Data-Quality-Intelligent-Platform) | Pre-submission EDI 837 validation |
| 2 — Routing Engine | [intelligent-claim-routing-engine](https://github.com/lp07/intelligent-claim-routing-engine) | Denial risk scoring and queue assignment |
| 3 — Remittance Reconciliation | This repo | 835/837 matching + underpayment detection + feedback loop |

---

*All data is synthetically generated. No real patient, provider, or payer data is used.*

MIT License — Copyright (c) 2026 Lisa Patel
