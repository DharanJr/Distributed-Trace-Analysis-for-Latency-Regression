"""
Module 10: Evidence-driven RCA agent.

Deterministic template agent (no LLM required for the core demo) that turns
the structured attribution output into a readable root-cause note carrying
the full evidence chain from symptom to span. Confidence is rule-based:
  HIGH   - statistically significant, on critical path >=50% of the time,
           AND deployment evidence present
  MEDIUM - significant and (on critical path OR deployment evidence)
  LOW    - significant only, no strong corroborating signal
"""


def _confidence(attribution):
    sig = attribution["adjusted_p_value"] <= 0.05
    on_path = attribution["on_path_rate"] >= 0.5
    has_deploy = attribution["has_deploy_evidence"]
    if sig and on_path and has_deploy:
        return "HIGH"
    if sig and (on_path or has_deploy):
        return "MEDIUM"
    return "LOW"


def generate_rca_note(attribution, symptom_service="api-gateway", symptom_operation="checkout",
                       symptom_before_p99=None, symptom_after_p99=None):
    if attribution is None:
        return "No statistically significant regression (after FDR correction) was detected in the current data."

    confidence = _confidence(attribution)
    chain_str = "\n  ↓\n".join(attribution["chain"] + (["Latency Regression"]))

    symptom_line = f"{symptom_service}/{symptom_operation}"
    if symptom_before_p99 is not None and symptom_after_p99 is not None:
        symptom_line += f" P99 increased from {symptom_before_p99:.0f}ms to {symptom_after_p99:.0f}ms."
    else:
        symptom_line += " P99 latency regressed."

    evidence_lines = "\n".join(f"{i+1}. {e}" for i, e in enumerate(attribution["evidence"]))

    note = f"""
--------------------------------------------------
ROOT CAUSE ANALYSIS
--------------------------------------------------

Symptom:
{symptom_line}

Primary contributor (root cause candidate):
{attribution['root_cause_candidate']} / {attribution['operation']}

Evidence:

{evidence_lines}

Evidence chain:

{chain_str}

Confidence: {confidence}

Note: Deployment timing, where present, is evidence of temporal association
and a contributing signal only -- it does NOT by itself prove causation.
--------------------------------------------------
""".strip("\n")
    return note


def build_evidence_chain_json(attribution):
    """Structured version of the same evidence, for the dashboard / API."""
    if attribution is None:
        return None
    return {
        "root_cause_candidate": attribution["root_cause_candidate"],
        "operation": attribution["operation"],
        "evidence": attribution["evidence"],
        "chain": attribution["chain"],
        "confidence": _confidence(attribution),
    }
