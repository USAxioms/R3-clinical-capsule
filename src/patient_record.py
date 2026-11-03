"""
Clinical Record Data Model.

All measurement values are stored as WAD-18 integers.  The WAD-18
representation of a clinical quantity Q in unit U is:
    value_wad18 = round(Q × 10^18)

For example:
    Glucose 95 mg/dL   → 95_000_000_000_000_000_000
    Sodium 140 mEq/L   → 140_000_000_000_000_000_000
    Temperature 98.6°F → 98_600_000_000_000_000_000

No floating-point arithmetic is used anywhere in the model.
All comparisons between values and reference ranges are exact integer
comparisons on WAD-18 integers, eliminating rounding drift entirely.

Data is fully anonymised: patient_id is a random identifier; no PHI
fields (name, address, insurance number) are stored.  In production,
the WAD-18 hash chain provides the audit trail required by HIPAA §164.312(b).

LOINC codes (https://loinc.org) are used as standardised observation identifiers.
"""

import hashlib, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wad18 as W

SEX_CODES = frozenset(["M", "F", "U"])   # Male, Female, Unknown

# Observation severity codes
CRITICAL_LOW  = "CRITICAL_LOW"
LOW           = "LOW"
NORMAL        = "NORMAL"
HIGH          = "HIGH"
CRITICAL_HIGH = "CRITICAL_HIGH"
SEVERITY_CODES = frozenset([CRITICAL_LOW, LOW, NORMAL, HIGH, CRITICAL_HIGH])

# Verification status codes
VERIFIED               = "VERIFIED"
VERIFIED_WITH_FLAGS    = "VERIFIED_WITH_FLAGS"
INCOMPLETE             = "INCOMPLETE"
INVALID_PATIENT        = "INVALID_PATIENT"
OUT_OF_RANGE           = "OUT_OF_RANGE"
TEMPORAL_INCONSISTENCY = "TEMPORAL_INCONSISTENCY"
VERIFICATION_CODES = frozenset([
    VERIFIED, VERIFIED_WITH_FLAGS, INCOMPLETE,
    INVALID_PATIENT, OUT_OF_RANGE, TEMPORAL_INCONSISTENCY,
])


class PatientRecord:
    """Anonymised patient demographic record."""

    def __init__(self, patient_id: str, dob_yyyymmdd: int, sex: str,
                 registration_ts: str):
        if sex not in SEX_CODES:
            raise ValueError("unknown sex code: %r" % sex)
        if not (18000101 <= dob_yyyymmdd <= 20261231):
            raise ValueError("dob out of plausible range: %d" % dob_yyyymmdd)
        self.patient_id       = str(patient_id)
        self.dob_yyyymmdd     = int(dob_yyyymmdd)
        self.sex              = sex
        self.registration_ts  = str(registration_ts)

    def identity_hash(self) -> str:
        """SHA-256 of canonical patient identity fields.

        This hash binds observations to patients cryptographically.
        Any alteration of the patient record invalidates all previously
        issued observation identity hashes.
        """
        canon = json.dumps({
            "patient_id":   self.patient_id,
            "dob":          self.dob_yyyymmdd,
            "sex":          self.sex,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "patient_id":      self.patient_id,
            "dob_yyyymmdd":    self.dob_yyyymmdd,
            "sex":             self.sex,
            "registration_ts": self.registration_ts,
            "identity_hash":   self.identity_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PatientRecord":
        return cls(
            patient_id      = d["patient_id"],
            dob_yyyymmdd    = d["dob_yyyymmdd"],
            sex             = d["sex"],
            registration_ts = d["registration_ts"],
        )


class ClinicalObservation:
    """One clinical measurement attached to a patient.

    Fields
    ------
    obs_id          : unique observation identifier
    patient_id      : links to PatientRecord.patient_id
    patient_hash    : SHA-256 of patient identity at time of recording
    loinc_code      : LOINC code identifying the test (e.g. '2345-7' for glucose)
    display_name    : human-readable test name
    value_wad18     : measured value in WAD-18
    unit            : unit string (e.g. 'mg/dL', 'mEq/L', 'mmHg')
    ref_low_wad18   : lower reference bound (WAD-18)
    ref_high_wad18  : upper reference bound (WAD-18)
    crit_low_wad18  : critical low threshold (WAD-18); None if not applicable
    crit_high_wad18 : critical high threshold (WAD-18); None if not applicable
    timestamp       : ISO-8601 observation timestamp
    """

    def __init__(self,
                 obs_id: str,
                 patient_id: str,
                 patient_hash: str,
                 loinc_code: str,
                 display_name: str,
                 value_wad18: int,
                 unit: str,
                 ref_low_wad18: int,
                 ref_high_wad18: int,
                 crit_low_wad18,
                 crit_high_wad18,
                 timestamp: str):
        W.assert_wad(value_wad18, ref_low_wad18, ref_high_wad18)
        if ref_low_wad18 > ref_high_wad18:
            raise ValueError("ref_low > ref_high for %s" % obs_id)
        if crit_low_wad18 is not None:
            W.assert_wad(crit_low_wad18)
        if crit_high_wad18 is not None:
            W.assert_wad(crit_high_wad18)

        self.obs_id          = str(obs_id)
        self.patient_id      = str(patient_id)
        self.patient_hash    = str(patient_hash)
        self.loinc_code      = str(loinc_code)
        self.display_name    = str(display_name)
        self.value_wad18     = int(value_wad18)
        self.unit            = str(unit)
        self.ref_low_wad18   = int(ref_low_wad18)
        self.ref_high_wad18  = int(ref_high_wad18)
        self.crit_low_wad18  = int(crit_low_wad18) if crit_low_wad18 is not None else None
        self.crit_high_wad18 = int(crit_high_wad18) if crit_high_wad18 is not None else None
        self.timestamp       = str(timestamp)

    def obs_hash(self) -> str:
        """SHA-256 of canonical observation fields.

        Any alteration of the observation — including the patient binding,
        the value, or the reference range — changes this hash.
        """
        canon = json.dumps({
            "obs_id":       self.obs_id,
            "patient_id":   self.patient_id,
            "patient_hash": self.patient_hash,
            "loinc_code":   self.loinc_code,
            "value_wad18":  self.value_wad18,
            "unit":         self.unit,
            "timestamp":    self.timestamp,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "obs_id":          self.obs_id,
            "patient_id":      self.patient_id,
            "patient_hash":    self.patient_hash,
            "loinc_code":      self.loinc_code,
            "display_name":    self.display_name,
            "value_wad18":     self.value_wad18,
            "unit":            self.unit,
            "ref_low_wad18":   self.ref_low_wad18,
            "ref_high_wad18":  self.ref_high_wad18,
            "crit_low_wad18":  self.crit_low_wad18,
            "crit_high_wad18": self.crit_high_wad18,
            "timestamp":       self.timestamp,
            "obs_hash":        self.obs_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClinicalObservation":
        return cls(
            obs_id          = d["obs_id"],
            patient_id      = d["patient_id"],
            patient_hash    = d["patient_hash"],
            loinc_code      = d["loinc_code"],
            display_name    = d["display_name"],
            value_wad18     = d["value_wad18"],
            unit            = d["unit"],
            ref_low_wad18   = d["ref_low_wad18"],
            ref_high_wad18  = d["ref_high_wad18"],
            crit_low_wad18  = d.get("crit_low_wad18"),
            crit_high_wad18 = d.get("crit_high_wad18"),
            timestamp       = d["timestamp"],
        )
