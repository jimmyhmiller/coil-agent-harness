import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_observer.py"
SPEC = importlib.util.spec_from_file_location("run_observer", SCRIPT)
OBSERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = OBSERVER
SPEC.loader.exec_module(OBSERVER)


class RunObserverTest(unittest.TestCase):
    def event(self, sequence, kind, timestamp, operation="root", parent=""):
        return {
            "version": 1, "sequence": sequence, "timestamp_ms": timestamp,
            "event": kind, "run_id": "run-1", "agent_id": "agent-1",
            "operation_id": operation, "parent_operation_id": parent,
            "provider": "fixture", "model": "fixture-model", "payload": None,
        }

    def test_projects_elapsed_and_open_operation(self):
        events = [
            self.event(1, "run.created", 1000),
            self.event(2, "run.started", 1100),
            self.event(3, "tool.call.started", 1500, "tool-1", "model-1"),
        ]
        run = OBSERVER.run_projection(events, 2500)[0]
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["elapsed_ms"], 1400)
        self.assertEqual(run["in_flight"][0]["operation_id"], "tool-1")
        self.assertEqual(run["in_flight"][0]["elapsed_ms"], 1000)

    def test_completed_operation_and_run_are_not_in_flight(self):
        events = [
            self.event(1, "run.created", 1000),
            self.event(2, "run.started", 1100),
            self.event(3, "model.request.started", 1200, "model-1"),
            self.event(4, "model.request.completed", 1800, "model-1"),
            self.event(5, "run.completed", 1900),
        ]
        run = OBSERVER.run_projection(events, 9000)[0]
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["elapsed_ms"], 800)
        self.assertEqual(run["in_flight"], [])

    def test_reader_ignores_a_torn_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            complete = self.event(1, "run.created", 1000)
            path.write_text(__import__("json").dumps(complete) + "\n{\"sequence\":2")
            self.assertEqual(OBSERVER.read_journal(path), [complete])

    def test_filters_independent_action_dimensions(self):
        item = self.event(1, "tool.call.started", 1000, "tool-1", "model-1")
        self.assertTrue(OBSERVER.Filters(operation_id="tool-1").matches(item))
        self.assertTrue(OBSERVER.Filters(parent_operation_id="model-1").matches(item))
        self.assertFalse(OBSERVER.Filters(agent_id="someone-else").matches(item))

    def test_action_filter_retains_full_run_for_projection(self):
        events = [
            self.event(1, "run.created", 1000),
            self.event(2, "run.started", 1100),
            self.event(3, "tool.call.started", 1200, "tool-1", "model-1"),
        ]
        scoped = OBSERVER.inspection_scope(events, OBSERVER.Filters(operation_id="tool-1"))
        self.assertEqual(scoped, events)


if __name__ == "__main__":
    unittest.main()
