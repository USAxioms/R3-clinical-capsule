"""
Clinical Verification Engine — WAD-18 exact arithmetic throughout.

Verification pipeline for a single ClinicalObservation:

  Step 0: Completeness — all required fields present and non-empty
  Step 1: Patient binding — obs.patient_hash matches registered patient
  Step 2: LOINC known — observation loinc_code is in the registry
  Step 3: Range validity — value within physiologically possible bounds
  Step 4: Severity classification — CRITICAL_LOW/LOW/NORMAL/HIGH/CRITICAL_HIGH
  Step 5: Temporal consistency — timestamp ≥ patient.registration_ts

All range comparisons are WAD-18 exact integer comparisons.
No floating-point arithmetic is constructed at any step.

Verification codes:
  VERIFIED               — all checks pass, severity NORMAL
  VERIFIED_WITH_FLAGS    — all checks pass, severity is CRITICAL or abnormal
  INCOMPLETE             — missing or empty required field
  INVALID_PATIENT        — patient hash mismatch
  OUT_OF_RANGE           — value outside the physiological bounds
  TEMPORAL_INCONSISTENCY — observation predates patient registration
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wad18 as W
from patient_record  import (PatientRecord, ClinicalObservation,
                              CRITICAL_LOW, LOW, NORMAL, HIGH, CRITICAL_HIGH,
                              VERIFIED, VERIFIED_WITH_FLAGS, INCOMPLETE,
                              INVALID_PATIENT, OUT_OF_RANGE,
                              TEMPORAL_INCONSISTENCY, VERIFICATION_CODES)
from clinical_ranges import lookup, RangeEntry


# ── Severity classifier (WAD-18 only) ────────────────────────────────────

def classify_severity(value: int, entry: RangeEntry) -> str:
    """
    Classify the severity of a measurement against reference ranges.

    All comparisons are WAD-18 exact integer comparisons.
    Boundary conditions are explicitly defined: boundaries are inclusive.

      crit_low ≤ value < ref_low                    → LOW  (or CRITICAL_LOW)
      ref_low  ≤ value ≤ ref_high                   → NORMAL
      ref_high < value ≤ crit_high (or no crit_high)→ HIGH (or CRITICAL_HIGH)

    The critical thresholds take priority: a value below crit_low is
    CRITICAL_LOW even if it is below ref_low.
    """
    W.assert_wad(value)

    # Critical low (highest priority for low values)
    if entry.crit_low is not None and value < entry.crit_low:
        return CRITICAL_LOW

    # Critical high (highest priority for high values)
    if entry.crit_high is not None and value > entry.crit_high:
        return CRITICAL_HIGH

    # Normal range (inclusive on both ends)
    if entry.ref_low <= value <= entry.ref_high:
        return NORMAL

    # Low (below reference, above or equal to crit_low)
    if value < entry.ref_low:
        return LOW

    # High (above reference, at or below crit_high)
    return HIGH


# ── Completeness check ────────────────────────────────────────────────────

_REQUIRED_OBS_FIELDS = [
    "obs_id", "patient_id", "patient_hash", "loinc_code",
    "value_wad18", "unit", "timestamp",
]

def _is_complete(obs: ClinicalObservation) -> tuple:
    """Return (ok: bool, missing_field: str or None)."""
    for field in _REQUIRED_OBS_FIELDS:
        v = getattr(obs, field, None)
        if v is None or v == "":
            return False, field
    return True, None


# ── Main verification function ────────────────────────────────────────────

def verify(patient: PatientRecord, obs: ClinicalObservation) -> dict:
    """
    Verify one clinical observation against a registered patient.

    Parameters
    ----------
    patient : registered PatientRecord
    obs     : ClinicalObservation to verify

    Returns
    -------
    dict with keys:
      obs_id, patient_id, loinc_code, status, severity,
      flags, value_wad18, ref_low_wad18, ref_high_wad18,
      obs_hash, patient_hash_matches, arithmetic
    """
    flags = []

    # ── Step 0: Completeness ─────────────────────────────────────────────
    ok, missing = _is_complete(obs)
    if not ok:
        return _result(INCOMPLETE, obs, patient, None, flags,
                       note="missing field: %s" % missing)

    # ── Step 1: Patient binding ───────────────────────────────────────────
    expected_hash = patient.identity_hash()
    if obs.patient_hash != expected_hash:
        flags.append("PATIENT_HASH_MISMATCH")
        return _result(INVALID_PATIENT, obs, patient, None, flags,
                       note="hash mismatch")

    # ── Step 2: LOINC known ───────────────────────────────────────────────
    entry = lookup(obs.loinc_code)
    if entry is None:
        flags.append("UNKNOWN_LOINC")
        # Unknown LOINC: cannot range-check; treat as incomplete
        return _result(INCOMPLETE, obs, patient, None, flags,
                       note="unregistered LOINC: %s" % obs.loinc_code)

    # ── Step 3: Range validity (physiological plausibility) ───────────────
    # Value must be within the physiological envelope [crit_low, crit_high].
    # Values outside the critical thresholds are physiologically implausible
    # (measurement error or impossible state) and are flagged as OUT_OF_RANGE.
    if entry.crit_low is not None and obs.value_wad18 < entry.crit_low:
        if obs.value_wad18 < W.ZERO:
            flags.append("PHYSIOLOGICALLY_IMPOSSIBLE")
            return _result(OUT_OF_RANGE, obs, patient, CRITICAL_LOW, flags,
                           note="value below zero")
        # Below critical low but non-negative: still a valid (critical) result
        # — fall through to severity classification
    if entry.crit_high is not None and obs.value_wad18 > entry.crit_high:
        # Above critical high: valid critical result, not an error
        pass   # fall through to severity

    # ── Step 4: Severity classification ───────────────────────────────────
    severity = classify_severity(obs.value_wad18, entry)
    if severity in (CRITICAL_LOW, CRITICAL_HIGH):
        flags.append("CRITICAL_VALUE_ALERT")
    if severity in (LOW, HIGH):
        flags.append("ABNORMAL_VALUE")

    # ── Step 5: Temporal consistency ──────────────────────────────────────
    if obs.timestamp < patient.registration_ts:
        flags.append("PREDATES_REGISTRATION")
        return _result(TEMPORAL_INCONSISTENCY, obs, patient, severity, flags,
                       note="obs before patient registration")

    # ── Decision ─────────────────────────────────────────────────────────
    if flags:
        status = VERIFIED_WITH_FLAGS
    else:
        status = VERIFIED

    return _result(status, obs, patient, severity, flags,
                   ref_low=entry.ref_low, ref_high=entry.ref_high)


def _result(status, obs, patient, severity, flags,
            note="", ref_low=None, ref_high=None):
    assert status in VERIFICATION_CODES, "invalid status: %r" % status
    return {
        "obs_id":              obs.obs_id,
        "patient_id":          obs.patient_id,
        "loinc_code":          obs.loinc_code,
        "display_name":        obs.display_name,
        "status":              status,
        "severity":            severity,
        "flags":               flags,
        "value_wad18":         obs.value_wad18,
        "unit":                obs.unit,
        "ref_low_wad18":       ref_low  if ref_low  is not None else obs.ref_low_wad18,
        "ref_high_wad18":      ref_high if ref_high is not None else obs.ref_high_wad18,
        "obs_hash":            obs.obs_hash(),
        "patient_hash_matches":obs.patient_hash == patient.identity_hash(),
        "note":                note,
        "arithmetic":          "WAD-18 exact integer throughout",
    }


# ── Batch verification ────────────────────────────────────────────────────

def verify_batch(patients: dict, observations: list) -> list:
    """
    Verify a list of observations against a registry of patients.

    Parameters
    ----------
    patients     : dict mapping patient_id → PatientRecord
    observations : list of ClinicalObservation

    Returns
    -------
    list of verification result dicts, one per observation
    """
    results = []
    for obs in observations:
        patient = patients.get(obs.patient_id)
        if patient is None:
            results.append({
                "obs_id": obs.obs_id, "patient_id": obs.patient_id,
                "status": INVALID_PATIENT, "severity": None,
                "flags": ["PATIENT_NOT_REGISTERED"],
                "arithmetic": "WAD-18 exact integer throughout",
            })
        else:
            results.append(verify(patient, obs))
    return results


# ── Summary ───────────────────────────────────────────────────────────────

def verification_summary(results: list) -> dict:
    """Aggregate counts over a batch of verification results."""
    by_status   = {}
    by_severity = {}
    critical    = 0
    for r in results:
        by_status[r.get("status","?")] = by_status.get(r.get("status","?"), 0) + 1
        sev = r.get("severity")
        if sev:
            by_severity[sev] = by_severity.get(sev, 0) + 1
        if sev in (CRITICAL_LOW, CRITICAL_HIGH):
            critical += 1
    return {
        "total":           len(results),
        "by_status":       by_status,
        "by_severity":     by_severity,
        "critical_alerts": critical,
        "verified":        by_status.get(VERIFIED, 0),
        "verified_flags":  by_status.get(VERIFIED_WITH_FLAGS, 0),
        "failed":          len(results) - by_status.get(VERIFIED, 0)
                           - by_status.get(VERIFIED_WITH_FLAGS, 0),
    }
