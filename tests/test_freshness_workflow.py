"""Static contract tests for the live freshness workflow."""

from pathlib import Path
import unittest


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "freshness-gate.yml"


class FreshnessWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_installs_live_runtime_dependency(self) -> None:
        self.assertIn('python -m pip install "pandas>=2.2"', self.text)

    def test_exports_failure_classification(self) -> None:
        self.assertIn("failure_kind: ${{ steps.classify.outputs.failure_kind }}", self.text)
        self.assertIn('kind="freshness"', self.text)
        self.assertIn('kind="infrastructure"', self.text)
        self.assertIn('kind="none"', self.text)

    def test_data_freshness_alert_is_policy_only(self) -> None:
        self.assertIn(
            "needs.live-gate.outputs.failure_kind == 'freshness'",
            self.text,
        )
        self.assertEqual(self.text.count("labels: ['data-freshness']"), 1)
        self.assertIn("<!-- freshness-gate:TP.FG.J0 -->", self.text)

    def test_infrastructure_failures_use_a_distinct_marker(self) -> None:
        self.assertIn("alert-on-live-infrastructure-failure:", self.text)
        self.assertIn("<!-- freshness-gate-infrastructure:TP.FG.J0 -->", self.text)

    def test_success_closes_open_freshness_issue(self) -> None:
        self.assertIn("resolve-on-live-success:", self.text)
        self.assertIn("Freshness gate recovered.", self.text)
        self.assertIn("state_reason: 'completed'", self.text)


if __name__ == "__main__":
    unittest.main()
