"""
Targeted survivor tests — Clinical Verification Capsule.

Kills:
  patient_record:L58   '<=→<' ×2    — DOB exact-boundary validity
  patient_record:L133  'not→'        — crit_low=None handling
  patient_record:L135  'not→'        — crit_high=None handling
  verification_engine:L60 '>→>='    — crit_high exact boundary → HIGH not CRITICAL_HIGH
  wad18:L46 '+→-'                   — from_str arithmetic coverage

All other survivors are documented as equivalent in spec/mutation_equivalents.json.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wad18 as W
from patient_record import PatientRecord, ClinicalObservation
from clinical_ranges import lookup
from verification_engine import classify_severity, verify

SCALE = W.SCALE


def _v(s): return W.from_str(str(s))

def _patient(pid="P", dob=19650315, sex="M", reg="2026-01-01T00:00:00Z"):
    return PatientRecord(pid, dob, sex, reg)

def _obs_raw(patient, loinc, value_str, crit_low=None, crit_high=None,
             obs_id="O", ts="2026-06-01T10:00:00Z"):
    e = lookup(loinc)
    cl = e.crit_low  if crit_low  is None else crit_low
    ch = e.crit_high if crit_high is None else crit_high
    return ClinicalObservation(
        obs_id=obs_id, patient_id=patient.patient_id,
        patient_hash=patient.identity_hash(),
        loinc_code=loinc, display_name=e.display_name,
        value_wad18=_v(value_str), unit=e.unit,
        ref_low_wad18=e.ref_low, ref_high_wad18=e.ref_high,
        crit_low_wad18=cl, crit_high_wad18=ch,
        timestamp=ts)


# ══════════════════════════════════════════════════════════
# patient_record:L58 '<=→<' (×2) — DOB boundary validity
# ══════════════════════════════════════════════════════════

class TestDOBBoundaries(unittest.TestCase):

    def test_minimum_valid_dob_is_accepted(self):
        """Kills patient_record:L58 first '<=→<':
        dob=18000101 is the lower boundary and must NOT raise.
        With '<' mutant, dob=18000101 would fail the 18000101 < dob check."""
        p = PatientRecord("X", 18000101, "M", "2026-01-01T00:00:00Z")
        self.assertEqual(p.dob_yyyymmdd, 18000101)

    def test_maximum_valid_dob_is_accepted(self):
        """Kills patient_record:L58 second '<=→<':
        dob=20261231 is the upper boundary and must NOT raise.
        With '<' mutant, dob=20261231 would fail the dob < 20261231 check."""
        p = PatientRecord("X", 20261231, "F", "2026-01-01T00:00:00Z")
        self.assertEqual(p.dob_yyyymmdd, 20261231)

    def test_below_minimum_dob_rejected(self):
        """Complementary: one day below minimum must raise."""
        with self.assertRaises(ValueError):
            PatientRecord("X", 17991231, "M", "2026-01-01T00:00:00Z")

    def test_above_maximum_dob_rejected(self):
        """Complementary: one day above maximum must raise."""
        with self.assertRaises(ValueError):
            PatientRecord("X", 20270101, "M", "2026-01-01T00:00:00Z")


# ══════════════════════════════════════════════════════════
# patient_record:L133/L135 'not→' — crit=None handling
# ══════════════════════════════════════════════════════════

class TestCritNoneHandling(unittest.TestCase):

    def test_crit_low_none_does_not_raise(self):
        """Kills patient_record:L133 'not→':
        crit_low=None must NOT call assert_wad(None).
        With 'not' removed: 'if crit_low is None:' → assert_wad(None) → TypeError."""
        p = _patient()
        # Creatinine has crit_low=None in the registry
        e = lookup("2160-0")
        obs = ClinicalObservation(
            obs_id="O1", patient_id=p.patient_id,
            patient_hash=p.identity_hash(),
            loinc_code="2160-0", display_name="Creatinine",
            value_wad18=_v("1.0"), unit="mg/dL",
            ref_low_wad18=e.ref_low, ref_high_wad18=e.ref_high,
            crit_low_wad18=None,             # <-- explicitly None
            crit_high_wad18=e.crit_high,
            timestamp="2026-06-01T10:00:00Z")
        # Must not raise; store should be None
        self.assertIsNone(obs.crit_low_wad18)

    def test_crit_high_none_does_not_raise(self):
        """Kills patient_record:L135 'not→':
        crit_high=None must NOT call assert_wad(None).
        With 'not' removed: 'if crit_high is None:' → assert_wad(None) → TypeError."""
        p = _patient()
        e = lookup("2160-0")
        obs = ClinicalObservation(
            obs_id="O2", patient_id=p.patient_id,
            patient_hash=p.identity_hash(),
            loinc_code="2160-0", display_name="Creatinine",
            value_wad18=_v("1.0"), unit="mg/dL",
            ref_low_wad18=e.ref_low, ref_high_wad18=e.ref_high,
            crit_low_wad18=e.crit_low,
            crit_high_wad18=None,            # <-- explicitly None
            timestamp="2026-06-01T10:00:00Z")
        self.assertIsNone(obs.crit_high_wad18)

    def test_both_crit_none_observation_verifies(self):
        """Observation with both crit thresholds None must verify correctly."""
        p = _patient()
        e = lookup("2160-0")
        obs = ClinicalObservation(
            obs_id="O3", patient_id=p.patient_id,
            patient_hash=p.identity_hash(),
            loinc_code="2160-0", display_name="Creatinine",
            value_wad18=_v("1.0"), unit="mg/dL",
            ref_low_wad18=e.ref_low, ref_high_wad18=e.ref_high,
            crit_low_wad18=None, crit_high_wad18=None,
            timestamp="2026-06-01T10:00:00Z")
        r = verify(p, obs)
        self.assertNotEqual(r["status"], "INCOMPLETE")


# ══════════════════════════════════════════════════════════
# verification_engine:L60 '>→>=' — crit_high exact boundary
# ══════════════════════════════════════════════════════════

class TestCritHighBoundary(unittest.TestCase):

    def test_exactly_at_crit_high_is_high_not_critical(self):
        """Kills verification_engine:L60 '>→>=':
        value == crit_high must be HIGH, not CRITICAL_HIGH.
        The check is 'value > crit_high'; with '>=', value==crit_high fires."""
        glucose = lookup("2345-7")
        # crit_high for glucose is 500 mg/dL
        at_crit_high = glucose.crit_high   # exactly 500 in WAD-18
        severity = classify_severity(at_crit_high, glucose)
        self.assertEqual(severity, HIGH,
            f"At exactly crit_high ({at_crit_high//SCALE} mg/dL) severity should be HIGH, got {severity}")

    def test_one_unit_above_crit_high_is_critical(self):
        """Complementary: one unit above crit_high → CRITICAL_HIGH."""
        glucose = lookup("2345-7")
        above   = glucose.crit_high + 1
        severity = classify_severity(above, glucose)
        self.assertEqual(severity, CRITICAL_HIGH)

    def test_crit_high_boundary_all_registered_codes(self):
        """Every registered LOINC code must classify crit_high exactly as HIGH."""
        from clinical_ranges import REGISTRY
        from verification_engine import classify_severity
        for code, entry in REGISTRY.items():
            if entry.crit_high is None:
                continue
            sev = classify_severity(entry.crit_high, entry)
            self.assertEqual(sev, HIGH,
                f"{code}: at crit_high={entry.crit_high//SCALE} should be HIGH, got {sev}")


# ══════════════════════════════════════════════════════════
# wad18:L46 '+→-' — from_str arithmetic coverage
# ══════════════════════════════════════════════════════════

class TestFromStrArithmetic(unittest.TestCase):

    def test_decimal_with_fractional_part_exact(self):
        """Kills wad18:L46 '+→-': the concatenation 'whole + frac' must be
        addition, not subtraction. '17.5' → whole='17', frac='5'.
        With '+→-', 'whole - frac' is a TypeError on strings."""
        self.assertEqual(W.from_str("17.5"),
                         17 * W.SCALE + 5 * (W.SCALE // 10))

    def test_from_str_zero_point_seven(self):
        """Kills wad18:L46: '0.7' → int('0') * SCALE + int('7' + '0'*17)."""
        result = W.from_str("0.7")
        expected = 7 * (W.SCALE // 10)   # 7 * 10^17
        self.assertEqual(result, expected)

    def test_from_str_three_point_five(self):
        """Kills wad18:L46: '3.5' → 3*SCALE + 5*SCALE//10."""
        result   = W.from_str("3.5")
        expected = 3 * W.SCALE + 5 * (W.SCALE // 10)
        self.assertEqual(result, expected)

    def test_from_str_integer_string(self):
        """Kills wad18:L46: '100' → 100 * SCALE with no decimal handling."""
        self.assertEqual(W.from_str("100"), 100 * W.SCALE)


# ══════════════════════════════════════════════════════════
# Import the missing constant used in tests above
# ══════════════════════════════════════════════════════════

from patient_record import HIGH, CRITICAL_HIGH


if __name__ == "__main__":
    unittest.main(verbosity=2)
