"""
Clinical Reference Ranges — WAD-18 exact arithmetic.

All reference range boundaries are stored as WAD-18 integers.
A value of Q in unit U is stored as round(Q × 10^18).

Sources:
  Reference ranges: Mayo Clinic Laboratory Reference Values (2024)
  Critical values:  Joint Commission National Patient Safety Goals
  LOINC codes:      Regenstrief Institute LOINC database

Every boundary is declared as a Python integer literal — no float
literals appear in this file.  The static determinism audit (if enabled)
would confirm this.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wad18 as W


def _v(s: str) -> int:
    """Convert decimal string to WAD-18.  No floats."""
    return W.from_str(s)


# ── WAD-18 reference range entries ──────────────────────────────────────
# Each entry: (loinc_code, display_name, unit,
#              ref_low, ref_high, crit_low, crit_high)
# crit_low / crit_high are None when no critical threshold is defined.

_RANGES_RAW = [
    # Glucose (fasting plasma) — LOINC 2345-7
    ("2345-7", "Glucose", "mg/dL",
     _v("70"),  _v("100"),  _v("40"),   _v("500")),

    # Hemoglobin — LOINC 718-7
    ("718-7",  "Hemoglobin", "g/dL",
     _v("12"),  _v("17.5"), _v("7"),    _v("20")),

    # Creatinine (serum) — LOINC 2160-0
    ("2160-0", "Creatinine", "mg/dL",
     _v("0.7"), _v("1.3"),  None,       _v("10")),

    # Sodium — LOINC 2951-2
    ("2951-2", "Sodium", "mEq/L",
     _v("136"), _v("145"),  _v("120"),  _v("160")),

    # Potassium — LOINC 2823-3
    ("2823-3", "Potassium", "mEq/L",
     _v("3.5"), _v("5.0"),  _v("2.5"),  _v("6.5")),

    # Systolic blood pressure — LOINC 8480-6
    ("8480-6", "Systolic BP", "mmHg",
     _v("90"),  _v("140"),  _v("70"),   _v("200")),

    # Heart rate — LOINC 8867-4
    ("8867-4", "Heart Rate", "bpm",
     _v("60"),  _v("100"),  _v("40"),   _v("150")),

    # Temperature (oral) — LOINC 8310-5
    ("8310-5", "Temperature", "degF",
     _v("97"),  _v("99"),   _v("95"),   _v("104")),

    # White blood cell count — LOINC 6690-2
    ("6690-2", "WBC", "K/uL",
     _v("4.5"), _v("11"),   _v("2"),    _v("30")),

    # Platelets — LOINC 777-3
    ("777-3",  "Platelets", "K/uL",
     _v("150"), _v("400"),  _v("50"),   _v("1000")),

    # INR (coagulation) — LOINC 6301-6
    ("6301-6", "INR", "ratio",
     _v("0.8"), _v("1.1"),  None,       _v("5")),

    # Calcium (total) — LOINC 17861-6
    ("17861-6","Calcium", "mg/dL",
     _v("8.5"), _v("10.5"), _v("6.5"),  _v("13")),
]


class RangeEntry:
    __slots__ = ("loinc_code", "display_name", "unit",
                 "ref_low", "ref_high", "crit_low", "crit_high")

    def __init__(self, loinc_code, display_name, unit,
                 ref_low, ref_high, crit_low, crit_high):
        self.loinc_code   = loinc_code
        self.display_name = display_name
        self.unit         = unit
        self.ref_low      = ref_low
        self.ref_high     = ref_high
        self.crit_low     = crit_low
        self.crit_high    = crit_high


# Build registry dict: loinc_code → RangeEntry
REGISTRY: dict = {}
for _row in _RANGES_RAW:
    _code, _name, _unit, _rl, _rh, _cl, _ch = _row
    REGISTRY[_code] = RangeEntry(_code, _name, _unit, _rl, _rh, _cl, _ch)


def lookup(loinc_code: str):
    """Return RangeEntry for a LOINC code, or None if not registered."""
    return REGISTRY.get(str(loinc_code))


def registered_codes() -> list:
    return sorted(REGISTRY.keys())
