from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

import main
import assistant_actions


class AssistantActionLayerTestCase(unittest.TestCase):
    def setUp(self):
        self.original_db_path = main.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        main.DB_PATH = Path(self.temp_directory.name) / "rk_os_action_test.db"
        main.init_db()
        main.ensure_habits_table()
        main.ensure_habit_history_table()
        main.ensure_goals_table()
        main.ensure_activity_history_table()
        main.ensure_quiz_tables()
        assistant_actions.dispatcher._active_practice = None
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.DB_PATH = self.original_db_path
        self.temp_directory.cleanup()

    def action(self, payload):
        return self.client.post("/api/assistant/action", json=payload).json()

    # 1. Valid READ action
    def test_read_action_succeeds(self):
        result = self.action({"action": "routines.list"})
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "routines.list")
        self.assertEqual(result["permission"], "read")
        self.assertIn("tasks", result["data"])

        study = self.action({"action": "study.subjects"})
        self.assertTrue(study["success"])
        self.assertGreaterEqual(len(study["data"]), 4)

    # 2. Valid SAFE_WRITE action
    def test_safe_write_action_succeeds(self):
        created = self.action({"action": "routines.task.create", "args": {"title": "Revise"}})
        self.assertTrue(created["success"])
        task_id = created["data"]["id"]

        completed = self.action({"action": "routines.task.complete", "args": {"id": task_id}})
        self.assertTrue(completed["success"])
        self.assertEqual(completed["permission"], "safe_write")
        self.assertEqual(completed["data"]["completed"], 1)

    # 3. Valid WRITE action
    def test_write_action_succeeds(self):
        created = self.action({"action": "routines.habit.create", "args": {"name": "Morning Run"}})
        self.assertTrue(created["success"])
        self.assertEqual(created["permission"], "write")
        self.assertEqual(created["data"]["name"], "Morning Run")

    # 4. Destructive action without confirmation is rejected
    def test_destructive_action_without_confirmation_is_rejected(self):
        created = self.action({"action": "routines.task.create", "args": {"title": "Delete me"}})
        task_id = created["data"]["id"]

        rejected = self.action({"action": "routines.task.delete", "args": {"id": task_id}})
        self.assertFalse(rejected["success"])
        self.assertEqual(rejected["error"]["code"], "confirmation_required")
        self.assertTrue(rejected["confirmation_required"])

        still_there = [t for t in self.action({"action": "routines.list", "args": {"type": "tasks"}})["data"]["tasks"]]
        self.assertTrue(any(item["id"] == task_id for item in still_there))

    # 5. Destructive action with confirmation succeeds
    def test_destructive_action_with_confirmation_succeeds(self):
        created = self.action({"action": "routines.task.create", "args": {"title": "Delete me too"}})
        task_id = created["data"]["id"]

        deleted = self.action({
            "action": "routines.task.delete",
            "args": {"id": task_id},
            "confirmation_required": True,
        })
        self.assertTrue(deleted["success"])
        self.assertEqual(deleted["permission"], "destructive")
        tasks = self.action({"action": "routines.list", "args": {"type": "tasks"}})["data"]["tasks"]
        self.assertFalse(any(item["id"] == task_id for item in tasks))

    # 6. Unknown action is rejected
    def test_unknown_action_is_rejected(self):
        for action in ("os.system", "eval", "main.delete_task", "routines.task.remove"):
            result = self.action({"action": action, "args": {}})
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "unknown_action")

    # 7. Extra unexpected fields are rejected
    def test_extra_unexpected_fields_are_rejected(self):
        top_level = self.action({"action": "routines.list", "args": {}, "evil": "payload"})
        self.assertFalse(top_level["success"])
        self.assertEqual(top_level["error"]["code"], "invalid_args")

        nested = self.action({"action": "routines.task.create", "args": {"title": "x", "id": 5}})
        self.assertFalse(nested["success"])
        self.assertEqual(nested["error"]["code"], "invalid_args")

    # 8. Invalid arguments are rejected
    def test_invalid_arguments_are_rejected(self):
        cases = [
            {"action": "routines.task.create", "args": {}},  # missing required title
            {"action": "routines.task.create", "args": {"title": ""}},  # minLength
            {"action": "routines.goal.progress", "args": {"id": 1, "progress": 150}},  # maximum
            {"action": "routines.goal.progress", "args": {"id": 0, "progress": 10}},  # minimum
            {"action": "quiz.start", "args": {"subject_id": 1, "difficulty": "Impossible"}},  # enum
            {"action": "practice.submit", "args": {"question_id": 1, "selected_option": "Z"}},  # enum
            {"action": "routines.task.create", "args": {"title": 123}},  # type
            {"action": "routines.get", "args": {"type": "habits"}},  # missing id
        ]
        for payload in cases:
            result = self.action(payload)
            self.assertFalse(result["success"], payload)
            self.assertEqual(result["error"]["code"], "invalid_args", payload)

    # 9. Arbitrary function execution is impossible
    def test_arbitrary_function_execution_is_impossible(self):
        dispatcher = assistant_actions.dispatcher
        self.assertNotIn("__import__", dispatcher._handlers)
        self.assertNotIn("eval", dispatcher._handlers)
        self.assertNotIn("exec", dispatcher._handlers)

        result = self.action({"action": "eval", "args": {"expression": "__import__('os').system('id')"}})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "unknown_action")

        # Even a legitimate action cannot smuggle a callable name through args.
        smuggled = self.action({
            "action": "routines.task.create",
            "args": {"title": "x", "function": "os.system"},
        })
        self.assertFalse(smuggled["success"])
        self.assertEqual(smuggled["error"]["code"], "invalid_args")

    # 10. Arbitrary SQL execution is impossible
    def test_arbitrary_sql_execution_is_impossible(self):
        sql_action = self.action({"action": "sql.execute", "args": {"query": "DROP TABLE tasks"}})
        self.assertFalse(sql_action["success"])
        self.assertEqual(sql_action["error"]["code"], "unknown_action")

        # SQL text supplied as data is stored verbatim, not executed.
        payload = "x'); DROP TABLE tasks;--"
        created = self.action({"action": "routines.task.create", "args": {"title": payload}})
        self.assertTrue(created["success"])
        self.assertEqual(created["data"]["title"], payload)

        # The tasks table still exists and the value is intact.
        tasks = self.action({"action": "routines.list", "args": {"type": "tasks"}})["data"]["tasks"]
        self.assertTrue(any(item["title"] == payload for item in tasks))

    # 11. Existing assistant functionality still works
    def test_existing_assistant_natural_language_still_works(self):
        created = self.client.post(
            "/api/assistant/command", json={"command": "Add a task to study percentages"}
        ).json()
        self.assertEqual(created["action"], "create_task")

        routines = self.client.post(
            "/api/assistant/command", json={"command": "Show my routines for today"}
        ).json()
        self.assertEqual(routines["action"], "show_today")

        unsupported = self.client.post(
            "/api/assistant/command", json={"command": "Send a message in another app"}
        ).json()
        self.assertIsNone(unsupported["action"])

    # 12. Existing API behavior is unaffected
    def test_existing_api_endpoints_still_work(self):
        self.assertEqual(self.client.get("/api/status").json()["status"], "online")
        created = self.client.post("/api/tasks", json={"title": "Direct API"}).json()
        self.assertEqual(created["title"], "Direct API")
        self.assertEqual(self.client.get("/api/dashboard").json()["tasks"], 1)

    # Structured envelope through the existing command endpoint (backwards compatible)
    def test_structured_envelope_via_command_endpoint(self):
        result = self.client.post(
            "/api/assistant/command", json={"action": "routines.list"}
        ).json()
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "routines.list")
        self.assertEqual(result["permission"], "read")

    # Permission model + schema integrity
    def test_permission_model_and_schema_are_complete(self):
        catalog = assistant_actions.get_action_catalog()
        total = sum(len(items) for items in catalog.values())
        self.assertEqual(total, len(assistant_actions.ALLOWED_ACTIONS))
        self.assertEqual(set(assistant_actions.PERMISSIONS), assistant_actions.ALLOWED_ACTION_SET)

        for action in assistant_actions.ALLOWED_ACTIONS:
            self.assertIn(action, assistant_actions.dispatcher._handlers)
            self.assertIn(assistant_actions.PERMISSIONS[action],
                          {assistant_actions.READ, assistant_actions.SAFE_WRITE,
                           assistant_actions.WRITE, assistant_actions.DESTRUCTIVE})

        listed = self.client.get("/api/assistant/actions").json()
        self.assertEqual(len(listed["actions"]), len(assistant_actions.ALLOWED_ACTIONS))

    # Non-destructive actions ignore the confirmation flag
    def test_non_destructive_action_ignores_confirmation_flag(self):
        result = self.action({"action": "routines.list", "confirmation_required": True})
        self.assertTrue(result["success"])

    # Failures never expose raw database errors
    def test_failures_do_not_leak_internal_errors(self):
        result = self.action({
            "action": "routines.task.delete",
            "args": {"id": 424242},
            "confirmation_required": True,
        })
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "not_found")
        self.assertNotIn("sqlite", result["error"]["message"].lower())
        self.assertNotIn("select", result["error"]["message"].lower())

    # External automation is not reachable through the action layer
    def test_external_automation_requires_confirmation_and_is_not_allow_listed(self):
        self.assertFalse(self.client.get("/api/automation/capabilities").json()["connected"])
        self.assertFalse(any(
            "automation" in action or action.startswith("external")
            for action in assistant_actions.ALLOWED_ACTIONS
        ))

    # Envelope must be an object
    def test_non_object_envelope_is_rejected(self):
        result = assistant_actions.dispatch_action(["routines.list"])
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "invalid_envelope")


if __name__ == "__main__":
    unittest.main()
