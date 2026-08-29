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

    def test_dispatch_scenarios_are_explicit_and_closed(self) -> None:
        for scenario in (
            "live",
            "simulate-freshness",
            "simulate-infrastructure",
            "simulate-recovery",
        ):
            self.assertIn(f"- {scenario}", self.text)
        self.assertIn("required: true", self.text)
        self.assertIn("Unsupported or empty dispatch scenario", self.text)

    def test_schedule_cannot_select_a_simulation(self) -> None:
        self.assertIn('if [ "$EVENT_NAME" = "schedule" ]; then', self.text)
        self.assertIn('github.event_name == \'workflow_dispatch\' && inputs.scenario != \'live\'', self.text)
        self.assertIn("Controlled infrastructure failure; no credential was read.", self.text)

    def test_all_issue_mutations_share_a_non_cancelling_lock(self) -> None:
        self.assertIn("group: freshness-gate-TP.FG.J0-lifecycle", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_exports_fail_closed_classification(self) -> None:
        self.assertIn("failure_kind: ${{ steps.classify.outputs.failure_kind }}", self.text)
        self.assertIn('kind="freshness"', self.text)
        self.assertIn('kind="infrastructure"', self.text)
        self.assertIn('kind="none"', self.text)
        self.assertIn("Preserve fail-closed job status", self.text)

    def test_production_and_rehearsal_markers_are_distinct(self) -> None:
        for marker in (
            "<!-- freshness-gate:TP.FG.J0 -->",
            "<!-- freshness-gate-test:TP.FG.J0 -->",
            "<!-- freshness-gate-infrastructure:TP.FG.J0 -->",
            "<!-- freshness-gate-infrastructure-test:TP.FG.J0 -->",
        ):
            self.assertIn(marker, self.text)
        self.assertEqual(self.text.count("labels: ['data-freshness']"), 1)

    def test_issue_searches_paginate_and_exclude_pull_requests(self) -> None:
        self.assertGreaterEqual(self.text.count("github.paginate(github.rest.issues.listForRepo"), 3)
        self.assertGreaterEqual(self.text.count("!issue.pull_request"), 3)
        self.assertIn("per_page: 100", self.text)

    def test_run_order_and_rerun_guards_are_present(self) -> None:
        self.assertIn("RUN_ATTEMPT: ${{ github.run_attempt }}", self.text)
        self.assertIn("freshness-gate-observation:", self.text)
        self.assertGreaterEqual(self.text.count("BigInt(id) > BigInt(context.runId)"), 3)
        self.assertGreaterEqual(self.text.count("Number(match[3]) === attempt"), 3)

    def test_infrastructure_route_requires_explicit_classification(self) -> None:
        self.assertIn("needs.live-gate.outputs.failure_kind == 'infrastructure'", self.text)
        self.assertNotIn("needs.live-gate.outputs.failure_kind != 'freshness'", self.text)

    def test_success_is_explicit_and_closes_only_matching_issue(self) -> None:
        self.assertIn("needs.live-gate.outputs.failure_kind == 'none'", self.text)
        self.assertIn("Freshness gate recovered.", self.text)
        self.assertIn("state_reason: 'completed'", self.text)
        self.assertIn("process.env.SCENARIO === 'simulate-recovery'", self.text)


if __name__ == "__main__":
    unittest.main()
