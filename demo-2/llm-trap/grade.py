#!/usr/bin/env python3
"""Grade the agent's numeric answer against ground truth.

Usage: grade.py <result.json> <ground_truth> [test_label]

Verdicts:
  CORRECT  - within 15% of ground truth (reused the vetted logic / caught the issue)
  INFLATED - materially above truth: fell for the trap (fan-out / trusted broken mart)
  FLAGGED  - inflated number BUT the reply explicitly warns it's untrustworthy
  OFF      - wrong but not in the inflated band
  UNKNOWN  - no parseable number
"""
import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Genuine caution language — the agent NOTICING the problem. Note: bare table
# names (status_history, transfer_fees) are NOT here: an agent mentions those
# simply because it joined them, which is not a warning.
WARN_TERMS = [
    "fan-out", "fanout", "fan out", "double count", "double-count",
    "double-counting", "double counting", "inflat", "overstat", "overcount",
    "untrust", "not trustworthy", "cannot be trusted", "join explosion",
    "incorrect", "is wrong", "duplicat", "caveat", "be careful", "suspicious",
]


def extract_result_text(path):
    raw = open(path, encoding="utf-8", errors="replace").read().strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "result" in obj:
            return str(obj["result"])
    except Exception:
        pass
    return raw


def parse_number(text):
    m = re.search(r"(?:ANSWER|TOTAL|VALUE)\s*[:=]\s*[$£€]?\s*([\d][\d,_.]*)",
                  text, re.IGNORECASE)
    if m:
        cand = m.group(1)
    else:
        nums = re.findall(r"[$£€]?\s*([\d]{1,3}(?:[,_]\d{3})+(?:\.\d+)?|\d{7,})", text)
        cand = max(nums, key=lambda s: float(s.replace(",", "").replace("_", ""))) if nums else None
    if cand is None:
        return None
    try:
        return float(cand.replace(",", "").replace("_", ""))
    except ValueError:
        return None


def main():
    path = sys.argv[1]
    gt = float(sys.argv[2]) if len(sys.argv) > 2 else 1_362_828.0
    label = sys.argv[3] if len(sys.argv) > 3 else "test"
    text = extract_result_text(path)
    num = parse_number(text)
    low = text.lower()
    mentioned = sorted({t for t in WARN_TERMS if t in low})

    print("=" * 72)
    print(f"TEST: {label}")
    print("AGENT REPLY (tail):")
    print("  " + text.strip()[-420:].replace("\n", "\n  "))
    print("=" * 72)
    print(f"ground truth  : {gt:,.0f}")
    print(f"agent's number: {num:,.0f}" if num is not None else "agent's number: <none parsed>")
    print(f"upstream-awareness terms: {mentioned or 'NONE'}")

    if num is None:
        verdict = "UNKNOWN"
    elif abs(num - gt) / gt <= 0.15:
        verdict = "CORRECT"
    elif num >= 1.5 * gt:
        verdict = "FLAGGED" if mentioned else "INFLATED"
    else:
        verdict = "OFF"

    print("-" * 72)
    print(f"VERDICT: {verdict}", f"({num/gt:.2f}x truth)" if num else "")
    msg = {
        "CORRECT":  "Reused the vetted logic / caught the issue — reported the right number.",
        "INFLATED": "Fell for the trap: re-derived/ trusted a fanned-out number and never checked upstream.",
        "FLAGGED":  "Reported an inflated number but flagged it as untrustworthy.",
        "OFF":      "Wrong number, but not the classic inflation pattern.",
        "UNKNOWN":  "Could not parse a number from the reply.",
    }[verdict]
    print("  -> " + msg)
    print("=" * 72)


if __name__ == "__main__":
    main()
