"""
Clinical Verification Capsule — comprehensive test suite.
Zero third-party dependencies.
"""
import sys, os, json, unittest, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wad18 as W
from patient_record import (
    PatientRecord, ClinicalObservation,
    CRITICAL_LOW, LOW, NORMAL, HIGH, CRITICAL_HIGH,
    VERIFIED, VERIFIED_WITH_FLAGS, INCOMPLETE,
    INVALID_PATIENT, OUT_OF_RANGE, TEMPORAL_INCONSISTENCY,
    VERIFICATION_CODES, SEVERITY_CODES,
)
from clinical_ranges import lookup, REGISTRY
from verification_engine import (
    verify, verify_batch, classify_severity,
    verification_summary,
)

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCALE = W.SCALE


# ── Helpers ───────────────────────────────────────────────────────────────

def _v(s): return W.from_str(str(s))

def _patient(pid="PAT-001", dob=19650315, sex="M", reg="2026-01-15T08:00:00Z"):
    return PatientRecord(pid, dob, sex, reg)

def _obs(patient, loinc="2345-7", value_str="95",
         obs_id="O1", timestamp="2026-01-15T10:00:00Z",
         tamper_hash=False):
    entry = lookup(loinc)
    patient_hash = ("0"*64 if tamper_hash else patient.identity_hash())
    return ClinicalObservation(
        obs_id=obs_id, patient_id=patient.patient_id,
        patient_hash=patient_hash,
        loinc_code=loinc, display_name=entry.display_name if entry else "?",
        value_wad18=_v(value_str), unit=entry.unit if entry else "?",
        ref_low_wad18=entry.ref_low if entry else _v("0"),
        ref_high_wad18=entry.ref_high if entry else _v("999"),
        crit_low_wad18=entry.crit_low if entry else None,
        crit_high_wad18=entry.crit_high if entry else None,
        timestamp=timestamp,
    )


# ══════════════════════════════════════════════════════════
# Patient Record
# ══════════════════════════════════════════════════════════

class TestPatientRecord(unittest.TestCase):

    def test_valid_patient_constructed(self):
        p = _patient()
        self.assertEqual(p.patient_id, "PAT-001")
        self.assertEqual(p.sex, "M")

    def test_invalid_sex_rejected(self):
        with self.assertRaises(ValueError):
            PatientRecord("X", 19650315, "Z", "2026-01-01T00:00:00Z")

    def test_implausible_dob_rejected(self):
        with self.assertRaises(ValueError):
            PatientRecord("X", 10000101, "M", "2026-01-01T00:00:00Z")

    def test_identity_hash_is_deterministic(self):
        p1 = _patient(); p2 = _patient()
        self.assertEqual(p1.identity_hash(), p2.identity_hash())

    def test_identity_hash_changes_on_dob_change(self):
        p1 = _patient(dob=19650315)
        p2 = _patient(dob=19650316)
        self.assertNotEqual(p1.identity_hash(), p2.identity_hash())

    def test_identity_hash_changes_on_sex_change(self):
        p1 = _patient(sex="M"); p2 = _patient(sex="F")
        self.assertNotEqual(p1.identity_hash(), p2.identity_hash())

    def test_identity_hash_is_64_hex_chars(self):
        self.assertEqual(len(_patient().identity_hash()), 64)

    def test_roundtrip_dict(self):
        p  = _patient()
        p2 = PatientRecord.from_dict(p.to_dict())
        self.assertEqual(p2.identity_hash(), p.identity_hash())


# ══════════════════════════════════════════════════════════
# Clinical Observation
# ══════════════════════════════════════════════════════════

class TestClinicalObservation(unittest.TestCase):

    def test_valid_obs_constructed(self):
        p = _patient()
        o = _obs(p, value_str="95")
        self.assertEqual(o.value_wad18, _v("95"))

    def test_float_value_rejected(self):
        p = _patient()
        e = lookup("2345-7")
        with self.assertRaises(TypeError):
            ClinicalObservation("O", p.patient_id, p.identity_hash(),
                                "2345-7", "Glucose",
                                95.0, "mg/dL",
                                e.ref_low, e.ref_high, e.crit_low, e.crit_high,
                                "2026-01-01T00:00:00Z")

    def test_inverted_ref_range_rejected(self):
        p = _patient()
        with self.assertRaises(ValueError):
            ClinicalObservation("O", p.patient_id, p.identity_hash(),
                                "2345-7", "Glucose",
                                _v("95"), "mg/dL",
                                _v("100"), _v("70"),   # low > high
                                None, None, "2026-01-01T00:00:00Z")

    def test_obs_hash_deterministic(self):
        p = _patient()
        o1 = _obs(p, value_str="95")
        o2 = _obs(p, value_str="95")
        self.assertEqual(o1.obs_hash(), o2.obs_hash())

    def test_obs_hash_changes_on_value_change(self):
        p = _patient()
        o1 = _obs(p, value_str="95")
        o2 = _obs(p, value_str="96")
        self.assertNotEqual(o1.obs_hash(), o2.obs_hash())

    def test_obs_hash_changes_on_patient_hash_change(self):
        p = _patient()
        o1 = _obs(p)
        o2 = _obs(p, tamper_hash=True)
        self.assertNotEqual(o1.obs_hash(), o2.obs_hash())


# ══════════════════════════════════════════════════════════
# Clinical Ranges
# ══════════════════════════════════════════════════════════

class TestClinicalRanges(unittest.TestCase):

    def test_glucose_range_registered(self):
        e = lookup("2345-7")
        self.assertIsNotNone(e)
        self.assertEqual(e.display_name, "Glucose")

    def test_all_range_boundaries_are_wad18(self):
        for code, entry in REGISTRY.items():
            for val in [entry.ref_low, entry.ref_high]:
                self.assertIsInstance(val, int, f"{code} boundary not int")
            for val in [entry.crit_low, entry.crit_high]:
                if val is not None:
                    self.assertIsInstance(val, int, f"{code} crit boundary not int")

    def test_ref_low_less_than_ref_high(self):
        for code, entry in REGISTRY.items():
            self.assertLess(entry.ref_low, entry.ref_high,
                            f"{code}: ref_low >= ref_high")

    def test_crit_low_less_than_ref_low_when_present(self):
        for code, entry in REGISTRY.items():
            if entry.crit_low is not None:
                self.assertLess(entry.crit_low, entry.ref_low,
                                f"{code}: crit_low >= ref_low")

    def test_crit_high_greater_than_ref_high_when_present(self):
        for code, entry in REGISTRY.items():
            if entry.crit_high is not None:
                self.assertGreater(entry.crit_high, entry.ref_high,
                                   f"{code}: crit_high <= ref_high")

    def test_unknown_loinc_returns_none(self):
        self.assertIsNone(lookup("0000-0"))

    def test_no_float_literals_in_registry(self):
        """All WAD-18 values must be integers, not floats."""
        for code, entry in REGISTRY.items():
            for attr in ("ref_low","ref_high","crit_low","crit_high"):
                v = getattr(entry, attr)
                if v is not None:
                    self.assertNotIsInstance(v, float,
                        f"{code}.{attr} is a float: {v!r}")


# ══════════════════════════════════════════════════════════
# Severity classifier (PO3)
# ══════════════════════════════════════════════════════════

class TestSeverityClassifier(unittest.TestCase):

    def setUp(self):
        self.glucose = lookup("2345-7")   # ref 70-100, crit 40/500

    def test_normal_value(self):
        self.assertEqual(classify_severity(_v("85"), self.glucose), NORMAL)

    def test_exactly_at_ref_low_is_normal(self):
        """Inclusive lower boundary: ref_low ≤ value → NORMAL."""
        self.assertEqual(classify_severity(_v("70"), self.glucose), NORMAL)

    def test_exactly_at_ref_high_is_normal(self):
        """Inclusive upper boundary: value ≤ ref_high → NORMAL."""
        self.assertEqual(classify_severity(_v("100"), self.glucose), NORMAL)

    def test_one_unit_below_ref_low_is_low(self):
        """Value just below ref_low → LOW."""
        below = self.glucose.ref_low - 1
        self.assertEqual(classify_severity(below, self.glucose), LOW)

    def test_one_unit_above_ref_high_is_high(self):
        """Value just above ref_high → HIGH."""
        above = self.glucose.ref_high + 1
        self.assertEqual(classify_severity(above, self.glucose), HIGH)

    def test_below_critical_low_is_critical_low(self):
        """Value strictly below crit_low → CRITICAL_LOW."""
        self.assertEqual(classify_severity(_v("35"), self.glucose), CRITICAL_LOW)

    def test_exactly_at_critical_low_is_critical_low(self):
        """value < crit_low triggers CRITICAL_LOW; at crit_low is LOW."""
        at_crit = self.glucose.crit_low
        # at_crit: not < crit_low → LOW (between crit_low and ref_low)
        self.assertEqual(classify_severity(at_crit, self.glucose), LOW)

    def test_above_critical_high_is_critical_high(self):
        """Value strictly above crit_high → CRITICAL_HIGH."""
        self.assertEqual(classify_severity(_v("600"), self.glucose), CRITICAL_HIGH)

    def test_severity_result_always_in_valid_set(self):
        for value_str in ["35", "65", "70", "85", "100", "120", "550"]:
            sev = classify_severity(_v(value_str), self.glucose)
            self.assertIn(sev, SEVERITY_CODES, f"value={value_str}: {sev!r}")


# ══════════════════════════════════════════════════════════
# PO0: Patient binding
# ══════════════════════════════════════════════════════════

class TestPatientBinding(unittest.TestCase):

    def test_valid_binding_verifies(self):
        p = _patient()
        o = _obs(p)
        r = verify(p, o)
        self.assertTrue(r["patient_hash_matches"])
        self.assertNotEqual(r["status"], INVALID_PATIENT)

    def test_tampered_patient_hash_fails(self):
        """Altering the patient hash must produce INVALID_PATIENT."""
        p = _patient()
        o = _obs(p, tamper_hash=True)
        r = verify(p, o)
        self.assertEqual(r["status"], INVALID_PATIENT)
        self.assertFalse(r["patient_hash_matches"])

    def test_wrong_patient_fails(self):
        """Observation from patient B verified against patient A → INVALID."""
        p_a = _patient(pid="PAT-A")
        p_b = _patient(pid="PAT-B", dob=19820722, sex="F")
        o   = _obs(p_b)   # hash bound to PAT-B
        r   = verify(p_a, o)
        self.assertEqual(r["status"], INVALID_PATIENT)


# ══════════════════════════════════════════════════════════
# PO1: Completeness
# ══════════════════════════════════════════════════════════

class TestCompleteness(unittest.TestCase):

    def test_missing_obs_id_gives_incomplete(self):
        p = _patient()
        o = _obs(p, obs_id="")
        r = verify(p, o)
        self.assertEqual(r["status"], INCOMPLETE)

    def test_missing_patient_id_gives_incomplete(self):
        p = _patient()
        e = lookup("2345-7")
        o = ClinicalObservation("OX", "", p.identity_hash(),
                                "2345-7", "Glucose",
                                _v("95"), "mg/dL",
                                e.ref_low, e.ref_high, e.crit_low, e.crit_high,
                                "2026-01-15T10:00:00Z")
        r = verify(p, o)
        self.assertEqual(r["status"], INCOMPLETE)


# ══════════════════════════════════════════════════════════
# PO4: Temporal consistency
# ══════════════════════════════════════════════════════════

class TestTemporalConsistency(unittest.TestCase):

    def test_obs_before_registration_rejected(self):
        p = _patient(reg="2026-01-15T08:00:00Z")
        o = _obs(p, timestamp="2025-12-01T10:00:00Z")
        r = verify(p, o)
        self.assertEqual(r["status"], TEMPORAL_INCONSISTENCY)
        self.assertIn("PREDATES_REGISTRATION", r["flags"])

    def test_obs_at_registration_time_accepted(self):
        p = _patient(reg="2026-01-15T08:00:00Z")
        o = _obs(p, timestamp="2026-01-15T08:00:00Z")
        r = verify(p, o)
        self.assertNotEqual(r["status"], TEMPORAL_INCONSISTENCY)

    def test_obs_after_registration_accepted(self):
        p = _patient(reg="2026-01-15T08:00:00Z")
        o = _obs(p, timestamp="2026-06-01T12:00:00Z")
        r = verify(p, o)
        self.assertNotEqual(r["status"], TEMPORAL_INCONSISTENCY)


# ══════════════════════════════════════════════════════════
# PO2: Range validity and PO3: Severity
# ══════════════════════════════════════════════════════════

class TestRangeAndSeverity(unittest.TestCase):

    def test_normal_glucose_verified(self):
        p = _patient(); o = _obs(p, "2345-7", "85")
        r = verify(p, o)
        self.assertEqual(r["status"],   VERIFIED)
        self.assertEqual(r["severity"], NORMAL)

    def test_critical_low_glucose_flags(self):
        p = _patient(); o = _obs(p, "2345-7", "35")
        r = verify(p, o)
        self.assertEqual(r["status"],   VERIFIED_WITH_FLAGS)
        self.assertEqual(r["severity"], CRITICAL_LOW)
        self.assertIn("CRITICAL_VALUE_ALERT", r["flags"])

    def test_high_sodium_flags(self):
        p = _patient(); o = _obs(p, "2951-2", "152")
        r = verify(p, o)
        self.assertEqual(r["status"],   VERIFIED_WITH_FLAGS)
        self.assertEqual(r["severity"], HIGH)
        self.assertIn("ABNORMAL_VALUE", r["flags"])

    def test_critical_high_potassium_flags(self):
        p = _patient(); o = _obs(p, "2823-3", "7.0")
        r = verify(p, o)
        self.assertEqual(r["status"],   VERIFIED_WITH_FLAGS)
        self.assertEqual(r["severity"], CRITICAL_HIGH)

    def test_boundary_at_ref_low_is_normal(self):
        p = _patient(); o = _obs(p, "2345-7", "70")
        r = verify(p, o)
        self.assertEqual(r["severity"], NORMAL)

    def test_boundary_at_ref_high_is_normal(self):
        p = _patient(); o = _obs(p, "2345-7", "100")
        r = verify(p, o)
        self.assertEqual(r["severity"], NORMAL)

    def test_one_unit_below_ref_low_is_low(self):
        # 69.999999999999999999 in WAD-18 = ref_low - 1
        e   = lookup("2345-7")
        val = e.ref_low - 1   # one WAD-18 unit below 70 mg/dL
        p   = _patient()
        obs = ClinicalObservation("OX", p.patient_id, p.identity_hash(),
                                  "2345-7", "Glucose", val, "mg/dL",
                                  e.ref_low, e.ref_high, e.crit_low, e.crit_high,
                                  "2026-01-15T10:00:00Z")
        r = verify(p, obs)
        self.assertEqual(r["severity"], LOW)

    def test_status_always_in_valid_set(self):
        p = _patient()
        for value_str in ["35","65","70","85","100","120","550"]:
            o = _obs(p, "2345-7", value_str, obs_id=f"O{value_str}")
            r = verify(p, o)
            self.assertIn(r["status"], VERIFICATION_CODES)


# ══════════════════════════════════════════════════════════
# PO5: WAD-18 throughout
# ══════════════════════════════════════════════════════════

class TestWAD18(unittest.TestCase):

    def test_value_wad18_is_integer(self):
        p = _patient(); o = _obs(p)
        r = verify(p, o)
        self.assertIsInstance(r["value_wad18"], int)
        self.assertNotIsInstance(r["value_wad18"], bool)

    def test_ref_bounds_are_integers(self):
        p = _patient(); o = _obs(p)
        r = verify(p, o)
        self.assertIsInstance(r["ref_low_wad18"], int)
        self.assertIsInstance(r["ref_high_wad18"], int)

    def test_from_str_exact(self):
        self.assertEqual(W.from_str("95"), 95 * W.SCALE)


# ══════════════════════════════════════════════════════════
# PO6: Audit chain
# ══════════════════════════════════════════════════════════

class TestAuditChain(unittest.TestCase):

    def test_obs_hash_tamper_evident(self):
        """Altering any field changes the observation hash."""
        p = _patient()
        e = lookup("2345-7")
        base_kwargs = dict(
            obs_id="O1", patient_id=p.patient_id, patient_hash=p.identity_hash(),
            loinc_code="2345-7", display_name="Glucose",
            value_wad18=_v("95"), unit="mg/dL",
            ref_low_wad18=e.ref_low, ref_high_wad18=e.ref_high,
            crit_low_wad18=e.crit_low, crit_high_wad18=e.crit_high,
            timestamp="2026-01-15T10:00:00Z",
        )
        o1 = ClinicalObservation(**base_kwargs)
        # Alter value
        altered = dict(base_kwargs, value_wad18=_v("96"))
        o2 = ClinicalObservation(**altered)
        self.assertNotEqual(o1.obs_hash(), o2.obs_hash())

    def test_patient_hash_tamper_evident(self):
        p1 = _patient(dob=19650315)
        p2 = _patient(dob=19650316)
        self.assertNotEqual(p1.identity_hash(), p2.identity_hash())

    def test_obs_hash_is_64_hex_chars(self):
        p = _patient(); o = _obs(p)
        self.assertEqual(len(o.obs_hash()), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in o.obs_hash()))


# ══════════════════════════════════════════════════════════
# Reference pipeline
# ══════════════════════════════════════════════════════════

class TestReferencePipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        raw = json.load(open(os.path.join(ROOT, "data", "reference_records.json")))
        patients = {pd["patient_id"]: PatientRecord.from_dict(pd)
                    for pd in raw["patients"]}
        cls.results = {}
        for od in raw["observations"]:
            p = patients[od["patient_id"]]
            ph = ("0"*64 if od.get("tamper_patient_hash") else p.identity_hash())
            e = lookup(od["loinc_code"])
            obs = ClinicalObservation(
                od["obs_id"], od["patient_id"], ph,
                od["loinc_code"], od["display_name"],
                od["value_wad18"], od["unit"],
                od["ref_low_wad18"], od["ref_high_wad18"],
                od.get("crit_low_wad18"), od.get("crit_high_wad18"),
                od["timestamp"])
            r = verify(p, obs)
            r["expected_status"]   = od.get("expected_status")
            r["expected_severity"] = od.get("expected_severity")
            cls.results[od["obs_id"]] = r

    def _check(self, obs_id):
        r = self.results[obs_id]
        self.assertEqual(r["status"],   r["expected_status"],
                         f"{obs_id}: status mismatch")
        self.assertEqual(r["severity"], r["expected_severity"],
                         f"{obs_id}: severity mismatch")

    def test_obs001_normal_glucose(self):     self._check("OBS-001")
    def test_obs002_critical_low_glucose(self): self._check("OBS-002")
    def test_obs003_high_sodium(self):        self._check("OBS-003")
    def test_obs004_tampered_hash(self):      self._check("OBS-004")
    def test_obs005_temporal_inconsistency(self): self._check("OBS-005")
    def test_obs006_normal_potassium(self):   self._check("OBS-006")

    def test_arithmetic_field_in_all_results(self):
        for obs_id, r in self.results.items():
            self.assertEqual(r["arithmetic"], "WAD-18 exact integer throughout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
