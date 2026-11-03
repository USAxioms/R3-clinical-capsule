"""Clinical Verification Capsule Pipeline."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from patient_record    import PatientRecord, ClinicalObservation
from verification_engine import verify, verification_summary
from csl               import CSL

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA   = os.path.join(ROOT, "data", "reference_records.json")
LEDGER = os.path.join(ROOT, "audit", "csl_ledger.json")
LOGS   = os.path.join(ROOT, "logs")


def run():
    os.makedirs(LOGS, exist_ok=True)
    csl = CSL(LEDGER)
    raw = json.load(open(DATA))

    # Build patient registry
    patients = {}
    for pd in raw["patients"]:
        p = PatientRecord.from_dict(pd)
        patients[p.patient_id] = p

    csl.append({
        "capsule":    "clinical-capsule", "version": "1.0.0",
        "arithmetic": "WAD-18 exact integer — zero floating-point drift",
        "model":      "Patient→Observation binding via SHA-256 identity hash",
        "n_patients": len(patients),
    }, label="GENESIS")
    print(f"[CSL 0] Genesis.  H={csl.root_hash()[:20]}...")

    results = []
    for od in raw["observations"]:
        patient = patients[od["patient_id"]]
        patient_hash = (patient.identity_hash() if not od.get("tamper_patient_hash")
                        else "0" * 64)
        obs = ClinicalObservation(
            obs_id=od["obs_id"], patient_id=od["patient_id"],
            patient_hash=patient_hash,
            loinc_code=od["loinc_code"], display_name=od["display_name"],
            value_wad18=od["value_wad18"], unit=od["unit"],
            ref_low_wad18=od["ref_low_wad18"], ref_high_wad18=od["ref_high_wad18"],
            crit_low_wad18=od.get("crit_low_wad18"),
            crit_high_wad18=od.get("crit_high_wad18"),
            timestamp=od["timestamp"])

        result     = verify(patient, obs)
        label      = od.get("label", obs.obs_id)
        exp_status = od.get("expected_status")
        exp_sev    = od.get("expected_severity")
        pass_s     = result["status"]   == exp_status
        pass_v     = result["severity"] == exp_sev
        all_pass   = pass_s and pass_v

        csl.append({
            "obs_id":   result["obs_id"],
            "status":   result["status"],
            "severity": result["severity"],
            "flags":    result["flags"],
            "obs_hash": result["obs_hash"][:16],
            "pass":     all_pass,
        }, label=label)

        result["expected_status"]   = exp_status
        result["expected_severity"] = exp_sev
        result["pass"]              = all_pass
        results.append(result)

        mark = "✓" if all_pass else "✗"
        print(f"  {mark} [{obs.obs_id}] {result['status']:<26} "
              f"sev={str(result['severity']):<14} "
              f"{od.get('display_name','?')}={od['value_wad18']//10**18} {od['unit']}")

    summary    = verification_summary(results)
    all_pass_f = all(r["pass"] for r in results)
    csl.append({"all_pass": all_pass_f, "summary": summary,
                "H_final": csl.root_hash()}, label="FINALIZATION")

    json.dump({"results": results, "summary": summary},
              open(os.path.join(LOGS, "verifications.json"), "w"),
              indent=2, sort_keys=True)
    print(f"\n{'='*60}")
    print(f"  Verified: {summary['verified']}  Flags: {summary['verified_flags']}"
          f"  Failed: {summary['failed']}")
    print(f"  Critical alerts: {summary['critical_alerts']}")
    print(f"  All pass: {all_pass_f}  |  H_final: {csl.root_hash()[:28]}...")
    print(f"{'='*60}")
    return results


if __name__ == "__main__":
    run()
