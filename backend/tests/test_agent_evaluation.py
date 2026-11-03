from app.evals.policy_evaluator import assert_policy_cases


def test_policy_evaluation_cases_pass():
    results = assert_policy_cases()
    assert results
    assert all(item["passed"] for item in results)
