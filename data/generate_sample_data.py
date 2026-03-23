"""
generate_sample_data.py — Synthetic 837 Claims + 835 Remittance Generator

Generates two matching datasets:
1. claims_837.csv     — submitted claims (837 format, from Project 1)
2. remittance_835.csv — payer payment responses (835 format)

REALISTIC DATA PATTERNS:
- ~55% fully matched and paid (MATCHED)
- ~12% underpaid vs contracted rate (UNDERPAYMENT)
- ~8%  contractual adjustment (deductible/copay) (CONTRACTUAL_ADJUST)
- ~18% denied with CARC codes (DENIAL)
- ~5%  reversed (REVERSAL)
- ~2%  no 835 received yet (PENDING)

CARC code distribution reflects real-world RCM denial patterns:
- CO-29: timely filing (most common for Cigna)
- CO-97: bundling
- CO-45: contractual adjustment
- CO-50: medical necessity
- CO-15: prior auth
- CO-4:  late filing/bundling
- PR-1:  deductible
"""

import pandas as pd
import random
from datetime import datetime, timedelta

random.seed(42)

PAYERS = ["BCBS", "AETNA", "CIGNA", "HUMANA", "MEDICARE"]

CPT_CODES = [
    "99213", "99214", "99215", "99232", "99283",
    "93000", "71046", "80053", "85025", "36415",
    "G0438", "27447", "90837", "22612", "43239"
]

# CARC scenarios with group codes
CARC_SCENARIOS = {
    "MATCHED":             ("45", "CO", 0.92),   # CO-45 contractual write-off, full pay
    "UNDERPAYMENT":        ("45", "CO", 0.75),   # CO-45 but paid less than contract
    "CONTRACTUAL_PR":      ("45|1", "CO", 0.80), # CO-45 + PR-1 deductible
    "DENIAL_TF":           ("29", "CO", 0.0),    # Timely filing
    "DENIAL_BUNDLING":     ("97", "CO", 0.0),    # Bundling
    "DENIAL_AUTH":         ("15", "CO", 0.0),    # Prior auth
    "DENIAL_MED_NEC":      ("50", "CO", 0.0),    # Medical necessity
    "DENIAL_DUPLICATE":    ("18", "OA", 0.0),    # Duplicate
    "DENIAL_COVERAGE":     ("96", "CO", 0.0),    # Not covered
    "REVERSAL":            ("72", "PR", -1.0),   # Reversal — negative payment
}

# Contracted rates per payer per CPT (simplified)
CONTRACTED_RATES = {
    "BCBS":     {"99213": 95, "99214": 142, "99215": 195, "99232": 115,
                 "93000": 48, "71046": 185, "80053": 32, "85025": 24,
                 "36415": 18, "G0438": 165, "27447": 3850, "90837": 125,
                 "22612": 4200, "43239": 1850, "99283": 210, "DEFAULT": 85},
    "AETNA":    {"99213": 88, "99214": 131, "99215": 178, "99232": 105,
                 "93000": 44, "71046": 172, "80053": 29, "85025": 21,
                 "36415": 16, "G0438": 155, "27447": 3650, "90837": 118,
                 "22612": 3950, "43239": 1750, "99283": 195, "DEFAULT": 78},
    "CIGNA":    {"99213": 91, "99214": 136, "99215": 183, "99232": 110,
                 "93000": 46, "71046": 178, "80053": 30, "85025": 22,
                 "36415": 17, "G0438": 158, "27447": 3720, "90837": 121,
                 "22612": 4050, "43239": 1790, "99283": 200, "DEFAULT": 81},
    "HUMANA":   {"99213": 87, "99214": 129, "99215": 175, "99232": 102,
                 "93000": 43, "71046": 168, "80053": 28, "85025": 20,
                 "36415": 15, "G0438": 152, "27447": 3580, "90837": 115,
                 "22612": 3880, "43239": 1710, "99283": 190, "DEFAULT": 76},
    "MEDICARE": {"99213": 76, "99214": 111, "99215": 148, "99232": 89,
                 "93000": 37, "71046": 142, "80053": 22, "85025": 16,
                 "36415": 12, "G0438": 168, "27447": 1285, "90837": 98,
                 "22612": 1420, "43239": 892, "99283": 160, "DEFAULT": 65},
}


def get_contracted(payer, cpt):
    rates = CONTRACTED_RATES.get(payer, {})
    return rates.get(cpt, rates.get("DEFAULT", 85))


def generate_billed(contracted):
    """Billed is typically 2-4x contracted rate."""
    return round(contracted * random.uniform(2.0, 4.0), 2)


def generate_datasets(n=1200):
    claims = []
    remittances = []

    for i in range(n):
        payer = random.choice(PAYERS)
        cpt = random.choice(CPT_CODES)
        contracted = get_contracted(payer, cpt)
        billed = generate_billed(contracted)
        dos_days_ago = random.randint(5, 320)

        # Cigna gets more timely filing issues (90-day window)
        if payer == "CIGNA":
            dos_days_ago = random.randint(70, 100)

        dos = datetime.today() - timedelta(days=dos_days_ago)
        submitted = dos + timedelta(days=random.randint(1, 14))

        claim_id = f"CLM{str(i+1).zfill(6)}"
        patient_id = f"PAT{random.randint(10000, 99999)}"

        claim = {
            "claim_id":       claim_id,
            "patient_id":     patient_id,
            "payer":          payer,
            "procedure_code": cpt,
            "date_of_service": dos.strftime("%Y-%m-%d"),
            "date_submitted":  submitted.strftime("%Y-%m-%d"),
            "billed_amount":   billed,
        }
        claims.append(claim)

        # Determine reconciliation scenario
        roll = random.random()

        if payer == "CIGNA" and dos_days_ago > 90:
            scenario = "DENIAL_TF"
        elif roll < 0.55:
            scenario = "MATCHED"
        elif roll < 0.67:
            scenario = "UNDERPAYMENT"
        elif roll < 0.75:
            scenario = "CONTRACTUAL_PR"
        elif roll < 0.82:
            scenario = random.choice(["DENIAL_TF", "DENIAL_BUNDLING", "DENIAL_AUTH"])
        elif roll < 0.87:
            scenario = random.choice(["DENIAL_MED_NEC", "DENIAL_COVERAGE"])
        elif roll < 0.90:
            scenario = "DENIAL_DUPLICATE"
        elif roll < 0.95:
            scenario = "REVERSAL"
        else:
            # PENDING — no remittance generated
            claims[-1]["status"] = "PENDING"
            continue

        # Generate remittance
        carc_str, group_code, pay_ratio = CARC_SCENARIOS[scenario]
        remit_date = submitted + timedelta(days=random.randint(14, 45))

        if scenario == "UNDERPAYMENT":
            # Pay 65-85% of contracted rate (underpayment)
            paid = round(contracted * random.uniform(0.65, 0.84), 2)
            allowed = contracted
            adj_amount = round(billed - paid, 2)
        elif scenario == "CONTRACTUAL_PR":
            # Pay contracted - deductible
            deductible = round(contracted * random.uniform(0.15, 0.35), 2)
            paid = round(contracted - deductible, 2)
            allowed = contracted
            adj_amount = round(billed - paid, 2)
        elif scenario == "REVERSAL":
            paid = round(-contracted * pay_ratio * -1, 2) * -1
            allowed = 0.0
            adj_amount = abs(paid)
        elif scenario == "MATCHED":
            paid = contracted
            allowed = contracted
            adj_amount = round(billed - paid, 2)
        else:
            # Denial
            paid = 0.0
            allowed = 0.0
            adj_amount = billed

        remittances.append({
            "remittance_id":   f"REM{str(i+1).zfill(6)}",
            "claim_id_ref":    claim_id,
            "patient_id":      patient_id,
            "payer":           payer,
            "date_of_service": dos.strftime("%Y-%m-%d"),
            "remittance_date": remit_date.strftime("%Y-%m-%d"),
            "billed_amount":   billed,
            "allowed_amount":  allowed,
            "paid_amount":     paid,
            "adjustment_amount": adj_amount,
            "carc_codes":      carc_str,
            "rarc_codes":      "N30" if "29" in carc_str else "",
            "carc_group_code": group_code,
            "check_number":    f"CHK{random.randint(100000,999999)}",
        })

    return pd.DataFrame(claims), pd.DataFrame(remittances)


if __name__ == "__main__":
    claims_df, remit_df = generate_datasets(1200)
    claims_df.to_csv("data/claims_837.csv", index=False)
    remit_df.to_csv("data/remittance_835.csv", index=False)
    print(f"Generated {len(claims_df)} claims → data/claims_837.csv")
    print(f"Generated {len(remit_df)} remittances → data/remittance_835.csv")
    print(f"\nClaims with remittance: {len(remit_df)}")
    print(f"Pending (no remittance): {len(claims_df) - len(remit_df)}")
