"""Run deterministic policy evaluations without calling an LLM."""

import json
from pathlib import Path
from typing import Any

from app.domain.agent.policy import PolicyService


DEFAULT_CASES_PATH = Path(__file__).with_name("policy_cases.json")


def evaluate_policy_cases(
    cases_path: Path = DEFAULT_CASES_PATH,
    policy: PolicyService | None = None,
) -> list[dict[str, Any]]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    service = policy or PolicyService()
    results: list[dict[str, Any]] = []

    for case in cases:
        error = None
        try:
            service.assert_tool_allowed(case["state"], case["tool"])
            allowed = True
        except Exception as exception:
            allowed = False
            error = type(exception).__name__

        expected = bool(case["expected_allowed"])
        results.append({
            "name": case["name"],
            "tool": case["tool"],
            "allowed": allowed,
            "expected_allowed": expected,
            "passed": allowed == expected,
            "error": error,
        })

    return results


def assert_policy_cases(
    cases_path: Path = DEFAULT_CASES_PATH,
) -> list[dict[str, Any]]:
    results = evaluate_policy_cases(cases_path)
    failures = [item for item in results if not item["passed"]]
    if failures:
        raise AssertionError(f"Policy evaluation failed: {failures}")
    return results
