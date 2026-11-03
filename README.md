# ==============================================================================
# CLINICAL-CAPSULE COMPLETE SOURCE IMPLEMENTATION
# ==============================================================================

# --- clinical-capsule/src/wad18.py ---
"""
WAD-18 Fixed-Point Arithmetic Module
Eliminates IEEE 754 floating-point non-determinism via 18-decimal integer scaling.
"""

SCALE = 10**18

def to_wad(value: float | int | str) -> int:
    """Convert a float, int, or string representation to a WAD-18 integer."""
    if isinstance(value, int):
        return value * SCALE
    if isinstance(value, float):
        s = f"{value:.18f}"
        parts = s.split(".")
        integer_part = int(parts[0]) * SCALE
        fractional_part = int(parts[1][:18].ljust(18, '0'))
        return integer_part + (fractional_part if integer_part >= 0 else -fractional_part)
    raise TypeError(f"Unsupported type for WAD conversion: {type(value)}")

def from_wad(wad_value: int) -> float:
    """Convert a WAD-18 integer back to a standard float for display/logging."""
    return wad_value / SCALE

def wad_add(a: int, b: int) -> int:
    return a + b

def wad_sub(a: int, b: int) -> int:
    return a - b

def wad_mul(a: int, b: int) -> int:
    return (a * b) // SCALE

def wad_div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("Division by zero in WAD-18 arithmetic.")
    return (a * SCALE) // b


# --- clinical-capsule/src/csl.py ---
"""
Cognitive State Ledger (CSL) Module
Maintains an immutable, cryptographically verifiable state ledger and audit trail.
"""

import json
import hashlib
from datetime import datetime

class CognitiveStateLedger:
    def __init__(self, ledger_path: str = "clinical-capsule/audit/csl_ledger.json"):
        self.ledger_path = ledger_path
        self.entries = []
        self.load_ledger()

    def load_ledger(self):
        try:
            with open(self.ledger_path, "r") as f:
                self.entries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.entries = []

    def record_transition(self, event_type: str, payload: dict) -> dict:
        prev_hash = self.entries[-1]["hash"] if self.entries else "0" * 64
        timestamp = datetime.utcnow().isoformat()
        
        record = {
            "index": len(self.entries),
            "timestamp": timestamp,
            "event_type": event_type,
            "payload": payload,
            "prev_hash": prev_hash
        }
        
        record_string = json.dumps(record, sort_keys=True)
        record["hash"] = hashlib.sha256(record_string.encode("utf-8")).hexdigest()
        
        self.entries.append(record)
        self.save_ledger()
        return record

    def save_ledger(self):
        with open(self.ledger_path, "w") as f:
            json.dump(self.entries, f, indent=2)


# --- clinical-capsule/src/clinical_ranges.py ---
"""
Clinical Ranges Module
Defines normative boundaries for physiological and clinical verification parameters.
"""

NORM_RANGES = {
    "heart_rate": (60.0, 100.0),          # bpm
    "blood_pressure_systolic": (90.0, 140.0), # mmHg
    "blood_pressure_diastolic": (60.0, 90.0), # mmHg
    "blood_glucose": (70.0, 99.0),        # mg/dL
    "oxygen_saturation": (95.0, 100.0)    # %
}


# --- clinical-capsule/src/patient_record.py ---
"""
Patient Record Module
Manages patient data encapsulation and validation parsing.
"""

class PatientRecord:
    def __init__(self, patient_id: str, data: dict):
        self.patient_id = patient_id
        self.data = data

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            **self.data
        }


# --- clinical-capsule/src/verification_engine.py ---
"""
Verification Engine Module
Validates clinical records against normative bounds using WAD-18 precision.
"""

from .wad18 import to_wad, from_wad
from .clinical_ranges import NORM_RANGES

class VerificationEngine:
    def __init__(self):
        pass

    def verify_parameter(self, param_name: str, raw_value: float | int) -> dict:
        if param_name not in NORM_RANGES:
            raise ValueError(f"Unknown clinical parameter: {param_name}")

        min_val, max_val = NORM_RANGES[param_name]
        val_wad = to_wad(raw_value)
        min_wad = to_wad(min_val)
        max_wad = to_wad(max_val)

        is_valid = min_wad <= val_wad <= max_wad
        status = "NORMAL" if is_valid else ("LOW" if val_wad < min_wad else "HIGH")

        return {
            "parameter": param_name,
            "value": raw_value,
            "wad_value": val_wad,
            "status": status,
            "passed": is_valid
        }

    def verify_record(self, record: dict) -> dict:
        results = {}
        all_passed = True
        
        for param, value in record.items():
            if param in NORM_RANGES:
                res = self.verify_parameter(param, value)
                results[param] = res
                if not res["passed"]:
                    all_passed = False

        return {
            "overall_passed": all_passed,
            "evaluations": results
        }


# --- clinical-capsule/src/pipeline.py ---
"""
Pipeline Execution Module
Orchestrates data ingestion, verification, ledger logging, and audit output.
"""

import json
from .verification_engine import VerificationEngine
from .csl import CognitiveStateLedger

class ClinicalPipeline:
    def __init__(self):
        self.engine = VerificationEngine()
        self.ledger = CognitiveStateLedger()

    def execute(self, patient_record: dict) -> dict:
        verification_result = self.engine.verify_record(patient_record)
        
        transition_payload = {
            "patient_id": patient_record.get("patient_id", "UNKNOWN"),
            "verification_passed": verification_result["overall_passed"],
            "evaluations": verification_result["evaluations"]
        }
        
        ledger_entry = self.ledger.record_transition("CLINICAL_VERIFICATION", transition_payload)
        
        return {
            "verification": verification_result,
            "audit_ledger_hash": ledger_entry["hash"],
            "ledger_index": ledger_entry["index"]
        }
