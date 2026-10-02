from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

import main


class RKOSAPITestCase(unittest.TestCase):
    def setUp(self):
        self.original_db_path = main.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        main.DB_PATH = Path(self.temp_directory.name) / "rk_os_test.db"
        main.init_db()
        main.ensure_habits_table()
        main.ensure_habit_history_table()
        main.ensure_goals_table()
        main.ensure_activity_history_table()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.DB_PATH = self.original_db_path
        self.temp_directory.cleanup()

    def test_task_crud_updates_progress_dashboard_and_snapshot(self):
        created = self.client.post("/api/tasks", json={"title": "Study"})
        self.assertEqual(created.status_code, 200)
        task_id = created.json()["id"]

        self.assertEqual(self.client.get("/api/dashboard").json()["tasks"], 1)
        self.assertEqual(self.client.get("/api/progress").json()["tasks"]["completed"], 0)

        updated = self.client.put(
            f"/api/tasks/{task_id}",
            json={"completed": True},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.get("/api/progress").json()["tasks"]["completed"], 1)
        self.assertEqual(
            self.client.get("/api/activity-history/today").json()["tasks_completed"],
            1,
        )

        self.client.put(f"/api/tasks/{task_id}", json={"completed": False})
        self.assertEqual(self.client.get("/api/progress").json()["tasks"]["completed"], 0)
        self.assertEqual(self.client.delete(f"/api/tasks/{task_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard").json()["tasks"], 0)
        self.assertEqual(
            self.client.get("/api/activity-history/today").json()["tasks_total"],
            0,
        )
        self.assertEqual(self.client.delete("/api/tasks/999").status_code, 404)

    def test_habit_daily_history_and_deleted_record_preservation(self):
        created = self.client.post("/api/habits", json={"name": "Read"})
        self.assertEqual(created.status_code, 200)
        habit_id = created.json()["id"]
        today = date.today().isoformat()

        self.assertEqual(self.client.put(f"/api/habits/{habit_id}", json={"completed": True}).status_code, 200)
        self.assertEqual(self.client.get("/api/activity-history/today").json()["habits_completed"], 1)

        self.client.put(f"/api/habits/{habit_id}", json={"completed": False})
        self.assertEqual(self.client.get("/api/progress").json()["habits"]["completed"], 0)

        connection = main.get_db()
        completion = connection.execute(
            "SELECT completed FROM habit_history WHERE habit_id = ? AND activity_date = ?",
            (habit_id, today),
        ).fetchone()
        connection.close()
        self.assertEqual(completion[0], 0)

        self.client.put(f"/api/habits/{habit_id}", json={"completed": True})
        deleted = self.client.delete(f"/api/habits/{habit_id}")
        self.assertEqual(deleted.status_code, 200)

        connection = main.get_db()
        preserved = connection.execute(
            "SELECT completed FROM habit_history WHERE habit_id = ? AND activity_date = ?",
            (habit_id, today),
        ).fetchone()
        connection.close()
        self.assertEqual(preserved[0], 1)
        self.assertEqual(self.client.get("/api/dashboard").json()["habits"], 0)
        self.assertEqual(self.client.delete(f"/api/habits/{habit_id}").status_code, 404)

    def test_date_rollover_excludes_yesterdays_completion(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        connection = main.get_db()
        connection.execute(
            "INSERT INTO habits (name, completed, last_completed_date) VALUES (?, 1, ?)",
            ("Yesterday", yesterday),
        )
        connection.execute(
            "INSERT INTO habits (name, completed, last_completed_date) VALUES (?, 1, ?)",
            ("Today", today),
        )
        connection.commit()
        connection.close()

        progress = self.client.get("/api/progress").json()
        snapshot = self.client.post("/api/activity-history/snapshot").json()
        self.assertEqual((progress["habits"]["total"], progress["habits"]["completed"]), (2, 1))
        self.assertEqual((snapshot["habits_total"], snapshot["habits_completed"]), (2, 1))

    def test_snapshot_reconciles_today_without_rewriting_prior_day(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        connection = main.get_db()
        habit_id = connection.execute(
            "INSERT INTO habits (name, completed, last_completed_date) VALUES (?, 0, NULL)",
            ("Read",),
        ).lastrowid
        connection.execute(
            "INSERT INTO habit_history (habit_id, activity_date, completed) VALUES (?, ?, 1)",
            (habit_id, today),
        )
        connection.execute(
            """INSERT INTO activity_history (
                activity_date, tasks_total, tasks_completed, habits_total,
                habits_completed, goals_total, goal_progress, overall_score
            ) VALUES (?, 9, 4, 3, 2, 2, 45, 39)""",
            (yesterday,),
        )
        connection.commit()
        connection.close()

        snapshot = self.client.post("/api/activity-history/snapshot").json()
        self.assertEqual((snapshot["habits_total"], snapshot["habits_completed"]), (1, 0))

        connection = main.get_db()
        current_completion = connection.execute(
            "SELECT completed FROM habit_history WHERE habit_id = ? AND activity_date = ?",
            (habit_id, today),
        ).fetchone()[0]
        prior_day = tuple(connection.execute(
            """SELECT tasks_total, tasks_completed, habits_total, habits_completed,
                goals_total, goal_progress, overall_score
                FROM activity_history WHERE activity_date = ?""",
            (yesterday,),
        ).fetchone())
        connection.close()

        self.assertEqual(current_completion, 0)
        self.assertEqual(prior_day, (9, 4, 3, 2, 2, 45, 39))

    def test_goal_crud_refreshes_snapshot_and_progress(self):
        created = self.client.post(
            "/api/goals",
            json={"title": "Launch", "target_date": "2026-12-31", "progress": 10},
        )
        self.assertEqual(created.status_code, 200)
        goal_id = created.json()["id"]

        updated = self.client.put(
            f"/api/goals/{goal_id}",
            json={"title": "Launch RK OS", "target_date": "2027-01-31", "progress": 65},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["progress"], 65)
        self.assertEqual(self.client.get("/api/progress").json()["goals"]["progress"], 65)
        self.assertEqual(self.client.get("/api/activity-history/today").json()["goal_progress"], 65)

        self.assertEqual(self.client.delete(f"/api/goals/{goal_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard").json()["goals"], 0)
        self.assertEqual(self.client.get("/api/activity-history/today").json()["goals_total"], 0)
        self.assertEqual(self.client.put("/api/goals/999", json={"progress": 30}).status_code, 404)

    def test_progress_score_dashboard_counts_and_historical_write_guard(self):
        first_task = self.client.post("/api/tasks", json={"title": "One"}).json()["id"]
        self.client.post("/api/tasks", json={"title": "Two"})
        self.client.put(f"/api/tasks/{first_task}", json={"completed": True})

        first_habit = self.client.post("/api/habits", json={"name": "Read"}).json()["id"]
        self.client.post("/api/habits", json={"name": "Walk"})
        self.client.put(f"/api/habits/{first_habit}", json={"completed": True})
        self.client.post("/api/goals", json={"title": "Goal", "progress": 60})

        progress = self.client.get("/api/progress").json()
        self.assertEqual(progress["tasks"], {"total": 2, "completed": 1, "completion": 50})
        self.assertEqual(progress["habits"], {"total": 2, "completed": 1, "completion": 50})
        self.assertEqual(progress["goals"], {"total": 1, "progress": 60})
        self.assertEqual(progress["overall_score"], 53)
        self.assertEqual(progress["total_items"], 5)
        self.assertEqual(self.client.get("/api/dashboard").json(), {"tasks": 2, "habits": 2, "goals": 1})

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        connection = main.get_db()
        connection.execute(
            """INSERT INTO activity_history (
                activity_date, tasks_total, tasks_completed, habits_total,
                habits_completed, goals_total, goal_progress, overall_score
            ) VALUES (?, 8, 3, 4, 2, 2, 45, 39)""",
            (yesterday,),
        )
        connection.commit()
        connection.close()

        rejected = self.client.post(
            "/api/activity-history",
            json={"activity_date": yesterday, "habits_total": 100},
        )
        self.assertEqual(rejected.status_code, 409)
        history = self.client.get("/api/activity-history?limit=7").json()
        previous_day = next(item for item in history if item["activity_date"] == yesterday)
        self.assertEqual(
            (previous_day["tasks_total"], previous_day["habits_total"], previous_day["goal_progress"]),
            (8, 4, 45),
        )

    def test_study_subjects_topics_and_notes_seed_data(self):
        main.ensure_study_tables()

        subjects = self.client.get("/api/study/subjects").json()
        self.assertGreaterEqual(len(subjects), 4)
        self.assertEqual({item["name"] for item in subjects}, {
            "Quantitative Aptitude",
            "General Intelligence & Reasoning",
            "English Language & Comprehension",
            "General Awareness",
        })

        topics = self.client.get("/api/study/topics").json()
        self.assertGreater(len(topics), 30)
        self.assertTrue(any(topic["name"] == "Percentage" for topic in topics))
        self.assertTrue(any(topic["name"] == "Coding-Decoding" for topic in topics))

        quant_subject = next(item for item in subjects if item["name"] == "Quantitative Aptitude")
        quant_topics = self.client.get(f"/api/study/topics?subject_id={quant_subject['id']}").json()
        self.assertTrue(any(topic["name"] == "Number System" for topic in quant_topics))
        seeded_notes = self.client.get("/api/study/notes").json()
        self.assertTrue(any(item["title"].startswith("Demo:") for item in seeded_notes))
        self.assertTrue(any("not verified" in item["content"] for item in seeded_notes))

        note = self.client.post(
            "/api/study/notes",
            json={
                "subject_id": quant_subject["id"],
                "topic_id": quant_topics[0]["id"],
                "title": "Quick Percentage Tips",
                "content": "Practice base-value conversions and percent-change formulas.",
                "active": True,
            },
        )
        self.assertEqual(note.status_code, 200)
        note_id = note.json()["id"]
        self.assertEqual(self.client.get(f"/api/study/notes/{note_id}").status_code, 200)
        self.assertGreater(len(self.client.get("/api/study/notes").json()), 0)

    def test_study_session_flow_and_dashboard_summary(self):
        main.ensure_study_tables()

        subject = self.client.get("/api/study/subjects").json()[0]
        topic = self.client.get(f"/api/study/topics?subject_id={subject['id']}").json()[0]

        response = self.client.post(
            "/api/study/sessions",
            json={
                "subject_id": subject["id"],
                "topic_id": topic["id"],
                "session_type": "study",
                "duration_minutes": 45,
            },
        )
        self.assertEqual(response.status_code, 200)
        session_id = response.json()["id"]

        saved = self.client.get("/api/study/sessions").json()
        self.assertTrue(any(item["id"] == session_id for item in saved))
        saved_session = next(item for item in saved if item["id"] == session_id)
        self.assertEqual(saved_session["subject_name"], subject["name"])
        self.assertEqual(saved_session["topic_name"], topic["name"])

        summary = self.client.get("/api/study/overview").json()
        self.assertEqual(summary["total_subjects"], 4)
        self.assertGreaterEqual(summary["total_topics"], 1)
        self.assertEqual(summary["today_sessions"], 1)
        self.assertEqual(summary["today_study_minutes"], 45)
        self.assertEqual(summary["topics_studied_today"], 1)
        self.assertEqual(summary["recent_sessions"][0]["topic_name"], topic["name"])

        dashboard = self.client.get("/api/dashboard").json()
        self.assertIn("study", dashboard)
        self.assertEqual(dashboard["study"]["sessions"], 1)
        self.assertEqual(dashboard["study"]["study_minutes"], 45)
        self.assertEqual(dashboard["study"]["topics_studied"], 1)

        progress = self.client.get("/api/progress").json()
        self.assertEqual(progress["study"], {
            "sessions": 1,
            "study_minutes": 45,
            "topics_studied": 1,
        })

    def test_practice_attempt_statistics_weak_topics_and_revision_reviews(self):
        subjects = self.client.get("/api/study/subjects").json()
        quant = next(item for item in subjects if item["name"] == "Quantitative Aptitude")
        topics = self.client.get(f"/api/study/topics?subject_id={quant['id']}").json()
        percentage = next(item for item in topics if item["name"] == "Percentage")

        questions_response = self.client.get(
            f"/api/practice/questions?subject_id={quant['id']}&topic_id={percentage['id']}&difficulty=Mixed"
        )
        self.assertEqual(questions_response.status_code, 200)
        questions = questions_response.json()
        self.assertGreaterEqual(len(questions), 2)
        self.assertTrue(all("Demo question — replace with verified SSC source" == item["source"] for item in questions))
        self.assertNotIn("correct_option", questions[0])
        self.assertGreater(
            len(self.client.get(
                f"/api/practice/questions?subject_id={quant['id']}&topic_id={percentage['id']}&difficulty=Easy"
            ).json()),
            0,
        )

        connection = main.get_db()
        answers = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT id, correct_option FROM questions WHERE topic_id = ? ORDER BY id LIMIT 2",
                (percentage["id"],),
            ).fetchall()
        }
        connection.close()
        question_ids = list(answers)

        correct = self.client.post(
            "/api/practice/attempts",
            json={"question_id": question_ids[0], "selected_option": answers[question_ids[0]]},
        )
        incorrect_option = next(option for option in "ABCD" if option != answers[question_ids[1]])
        incorrect = self.client.post(
            "/api/practice/attempts",
            json={"question_id": question_ids[1], "selected_option": incorrect_option},
        )
        self.assertEqual(correct.status_code, 200)
        self.assertTrue(correct.json()["is_correct"])
        self.assertEqual(incorrect.status_code, 200)
        self.assertFalse(incorrect.json()["is_correct"])
        self.assertTrue(incorrect.json()["explanation"])

        stats = self.client.get("/api/practice/statistics").json()
        self.assertEqual((stats["total_questions"], stats["correct"], stats["incorrect"], stats["accuracy"]), (2, 1, 1, 50))
        topic_detail = self.client.get(f"/api/study/topics/{percentage['id']}").json()
        self.assertEqual(topic_detail["practice_questions"], 2)
        self.assertEqual(topic_detail["practice_accuracy"], 50)
        dashboard = self.client.get("/api/dashboard").json()
        self.assertEqual(dashboard["practice"]["today_questions"], 2)
        self.assertEqual(dashboard["practice"]["today_accuracy"], 50)
        progress = self.client.get("/api/progress").json()
        self.assertEqual(progress["practice"], {
            "questions": 2,
            "correct": 1,
            "accuracy": 50,
            "weak_topics": 1,
        })
        weak_topics = self.client.get("/api/practice/weak-topics").json()
        weak = next(item for item in weak_topics if item["topic_id"] == percentage["id"])
        self.assertEqual(weak["accuracy"], 50)
        self.assertEqual(weak["questions_attempted"], 2)

        revision = self.client.get("/api/revision/topics").json()
        self.assertEqual(revision["today_revision_count"], 0)
        self.assertTrue(any(item["topic_id"] == percentage["id"] for item in revision["weak_areas"]))
        reviewed = self.client.post("/api/revision/reviews", json={"topic_id": percentage["id"]})
        self.assertEqual(reviewed.status_code, 200)
        refreshed_revision = self.client.get("/api/revision/topics").json()
        self.assertEqual(refreshed_revision["today_revision_count"], 1)
        self.assertTrue(any(
            item["topic_id"] == percentage["id"] and item["reviewed_today"]
            for item in refreshed_revision["recent_topics"]
        ))

    def test_quiz_session_answers_results_statistics_and_revision_weak_area(self):
        subjects = self.client.get("/api/study/subjects").json()
        quant = next(item for item in subjects if item["name"] == "Quantitative Aptitude")
        topics = self.client.get(f"/api/study/topics?subject_id={quant['id']}").json()
        percentage = next(item for item in topics if item["name"] == "Percentage")

        configuration = self.client.get(f"/api/quiz/configuration?subject_id={quant['id']}")
        self.assertEqual(configuration.status_code, 200)
        config = configuration.json()
        self.assertEqual(config["question_counts"], [5, 10, 15, 20])
        self.assertIn("All Topics", [item["name"] for item in config["topics"]])

        started = self.client.post(
            "/api/quiz/sessions",
            json={
                "subject_id": quant["id"],
                "topic_id": percentage["id"],
                "difficulty": "Mixed",
                "total_questions": 10,
            },
        )
        self.assertEqual(started.status_code, 200)
        session = started.json()
        self.assertEqual(session["total_questions"], 2)
        self.assertEqual(len(session["questions"]), 2)
        self.assertTrue(all("Demo question — replace with verified SSC source" == item["source"] for item in session["questions"]))
        self.assertNotIn("correct_option", session["questions"][0])

        question_ids = [item["id"] for item in session["questions"]]
        connection = main.get_db()
        answers = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT id, correct_option FROM questions WHERE id IN (?, ?)",
                tuple(question_ids),
            ).fetchall()
        }
        connection.close()

        first_answer = self.client.post(
            f"/api/quiz/sessions/{session['id']}/answers",
            json={"question_id": question_ids[0], "selected_option": answers[question_ids[0]]},
        )
        self.assertEqual(first_answer.status_code, 200)
        self.assertTrue(first_answer.json()["is_correct"])
        duplicate = self.client.post(
            f"/api/quiz/sessions/{session['id']}/answers",
            json={"question_id": question_ids[0], "selected_option": answers[question_ids[0]]},
        )
        self.assertEqual(duplicate.status_code, 409)

        wrong_option = next(option for option in "ABCD" if option != answers[question_ids[1]])
        second_answer = self.client.post(
            f"/api/quiz/sessions/{session['id']}/answers",
            json={"question_id": question_ids[1], "selected_option": wrong_option},
        )
        self.assertEqual(second_answer.status_code, 200)
        self.assertFalse(second_answer.json()["is_correct"])
        self.assertTrue(second_answer.json()["explanation"])

        completed = self.client.post(f"/api/quiz/sessions/{session['id']}/complete")
        self.assertEqual(completed.status_code, 200)
        result = completed.json()
        self.assertEqual((result["total_questions"], result["correct_answers"], result["incorrect_answers"], result["accuracy"]), (2, 1, 1, 50))
        self.assertGreaterEqual(result["time_taken_seconds"], 0)

        statistics = self.client.get("/api/quiz/statistics").json()
        self.assertEqual((statistics["attempts"], statistics["questions"], statistics["correct"], statistics["accuracy"], statistics["best_accuracy"]), (1, 2, 1, 50, 50))
        history = self.client.get("/api/quiz/history").json()
        self.assertEqual(history[0]["id"], session["id"])

        dashboard = self.client.get("/api/dashboard").json()
        self.assertEqual(dashboard["quiz"]["accuracy"], 50)
        progress = self.client.get("/api/progress").json()
        self.assertEqual(progress["quiz"]["attempts"], 1)
        self.assertEqual(progress["quiz"]["questions"], 2)
        revision = self.client.get("/api/revision/topics").json()
        percentage_weak_area = next(item for item in revision["weak_areas"] if item["topic_id"] == percentage["id"])
        self.assertLess(percentage_weak_area["accuracy"], 70)

    def test_profile_persistence_routines_summary_and_assistant_actions(self):
        profile = self.client.get("/api/profile").json()
        self.assertEqual(profile["name"], "RK User")
        saved_profile = self.client.put(
            "/api/profile",
            json={
                "name": "Siva",
                "bio": "SSC CGL aspirant",
                "study_target": 150,
                "exam_target": "SSC CGL 2027",
                "preferences": "Morning study",
                "assistant_preferences": "Concise responses",
            },
        )
        self.assertEqual(saved_profile.status_code, 200)
        self.assertEqual(self.client.get("/api/profile").json()["name"], "Siva")

        task = self.client.post("/api/assistant/command", json={"command": "Add a task to study percentages"}).json()
        habit = self.client.post("/api/assistant/command", json={"command": "Create a habit called Morning Exercise"}).json()
        goal = self.client.post("/api/assistant/command", json={"command": "Create a goal to complete SSC CGL preparation"}).json()
        self.assertEqual(task["action"], "create_task")
        self.assertEqual(habit["action"], "create_habit")
        self.assertEqual(goal["action"], "create_goal")

        completed_task = self.client.post("/api/assistant/command", json={"command": "Complete task study percentages"}).json()
        completed_habit = self.client.post("/api/assistant/command", json={"command": "Complete habit Morning Exercise"}).json()
        updated_goal = self.client.post("/api/assistant/command", json={"command": "Update goal complete SSC CGL preparation to 40%"}).json()
        self.assertEqual(completed_task["action"], "complete_task")
        self.assertEqual(completed_habit["action"], "complete_habit")
        self.assertEqual(updated_goal["action"], "update_goal")

        routines = self.client.get("/api/routines/summary").json()
        self.assertEqual((routines["tasks"]["completed"], routines["habits"]["completed_today"]), (1, 1))
        self.assertEqual(routines["goals"]["total"], 1)
        today = self.client.post("/api/assistant/command", json={"command": "Show my routines for today"}).json()
        self.assertEqual(today["action"], "show_today")
        unsupported = self.client.post("/api/assistant/command", json={"command": "Send a message in another app"}).json()
        self.assertIsNone(unsupported["action"])
        self.assertEqual(unsupported["response"], "That capability isn't connected yet.")
        history = self.client.get("/api/assistant/history").json()
        self.assertGreaterEqual(len(history), 8)
        self.assertFalse(self.client.get("/api/automation/capabilities").json()["connected"])


if __name__ == "__main__":
    unittest.main()
