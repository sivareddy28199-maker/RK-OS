from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import json
import re
import sqlite3
from pathlib import Path

# Project location
BASE_DIR = Path(__file__).resolve().parent

# SQLite database
DB_PATH = BASE_DIR / "rk_os.db"

# Create FastAPI application
app = FastAPI(title="RK OS v0.1")


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():

    conn = get_db()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            completed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            completed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            progress INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        );
    """)

    conn.commit()
    conn.close()


# Create database tables when server starts
init_db()


# =========================
# TEST API
# =========================

@app.get("/api/status")
def status():

    return {
        "status": "online",
        "app": "RK OS",
        "version": "0.1"
    }

# =========================================================
# DASHBOARD API
# =========================================================

@app.get("/api/dashboard")
def dashboard():
    conn = get_db()

    tasks_count = conn.execute(
        "SELECT COUNT(*) FROM tasks"
    ).fetchone()[0]

    habits_count = conn.execute(
        "SELECT COUNT(*) FROM habits"
    ).fetchone()[0]

    goals_count = conn.execute(
        "SELECT COUNT(*) FROM goals"
    ).fetchone()[0]

    conn.close()

    payload = {
        "tasks": tasks_count,
        "habits": habits_count,
        "goals": goals_count
    }

    study_summary = rk_get_study_dashboard_summary()
    if study_summary["sessions"] > 0 or study_summary["study_minutes"] > 0:
        payload["study"] = study_summary

    practice_summary = rk_get_practice_dashboard_summary()
    if practice_summary["today_questions"] > 0:
        payload["practice"] = practice_summary

    quiz_summary = rk_get_quiz_statistics()
    if quiz_summary["attempts"] > 0:
        payload["quiz"] = quiz_summary

    return payload


# =====================================================
# TASKS API
# =====================================================

@app.get("/api/tasks")
def get_tasks():
    conn = get_db()

    tasks = conn.execute(
        "SELECT id, title, completed FROM tasks ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return [
        {
            "id": task[0],
            "title": task[1],
            "completed": task[2]
        }
        for task in tasks
    ]


@app.post("/api/tasks")
def create_task(task: dict):
    title = str(task.get("title") or "").strip()

    if not title:
        raise HTTPException(status_code=422, detail="Task title is required")

    conn = get_db()

    cursor = conn.execute(
        "INSERT INTO tasks (title, completed) VALUES (?, ?)",
        (title, 0)
    )

    conn.commit()

    task_id = cursor.lastrowid

    conn.close()

    # Refresh today's activity snapshot
    rk_create_daily_snapshot()

    return {
        "id": task_id,
        "title": title,
        "completed": 0
    }


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, task: dict):
    completed = 1 if task.get("completed") else 0

    conn = get_db()

    cursor = conn.execute(
        "UPDATE tasks SET completed = ? WHERE id = ?",
        (completed, task_id)
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    conn.commit()
    conn.close()

    # Refresh today's activity snapshot
    rk_create_daily_snapshot()

    return {
        "id": task_id,
        "completed": completed
    }


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM tasks WHERE id = ?",
        (task_id,)
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    conn.commit()
    conn.close()
    
    # Refresh today's activity snapshot
    rk_create_daily_snapshot()

    return {
        "deleted": True,
        "id": task_id
    }


# ============================================================
# RK OS - HABITS API
# ============================================================

def ensure_habits_table():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            last_completed_date TEXT
        )
    """)

    columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(habits)").fetchall()
    ]

    if "last_completed_date" not in columns:
        conn.execute(
            "ALTER TABLE habits ADD COLUMN last_completed_date TEXT"
        )

    conn.commit()
    conn.close()


def ensure_habit_history_table():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS habit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            activity_date TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            UNIQUE (habit_id, activity_date)
        )
    """)

    conn.commit()
    conn.close()


@app.get("/api/habits")
def rk_get_habits():
    ensure_habits_table()

    today = date.today().isoformat()

    conn = get_db()
    habits = conn.execute(
        """
        SELECT id, name, completed, last_completed_date
        FROM habits
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()

    result = []

    for habit in habits:
        completed_today = (
            habit[2] == 1 and
            habit[3] == today
        )

        result.append({
            "id": habit[0],
            "name": habit[1],
            "completed": 1 if completed_today else 0,
            "last_completed_date": habit[3]
        })

    return result


@app.post("/api/habits")
def rk_create_habit(habit: dict):
    ensure_habits_table()
    ensure_habit_history_table()

    name = str(habit.get("name") or "").strip()

    if not name:
        raise HTTPException(status_code=422, detail="Habit name is required")

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO habits (name, completed, last_completed_date)
        VALUES (?, 0, NULL)
        """,
        (name,)
    )

    habit_id = cursor.lastrowid

    today = date.today().isoformat()
    conn.execute(
        """
        INSERT INTO habit_history (habit_id, activity_date, completed)
        VALUES (?, ?, 0)
        """,
        (habit_id, today)
    )
    conn.commit()
    conn.close()

    rk_create_daily_snapshot()

    return {
        "id": habit_id,
        "name": name,
        "completed": 0
    }


@app.put("/api/habits/{habit_id}")
def rk_update_habit(habit_id: int, habit: dict):
    ensure_habits_table()
    ensure_habit_history_table()

    completed = 1 if habit.get("completed") else 0

    today = date.today().isoformat()

    last_completed_date = today if completed else None

    conn = get_db()

    cursor = conn.execute(
        """
        UPDATE habits
        SET completed = ?,
            last_completed_date = ?
        WHERE id = ?
        """,
        (
            completed,
            last_completed_date,
            habit_id
        )
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Habit not found")

    conn.execute(
        """
        INSERT INTO habit_history (habit_id, activity_date, completed)
        VALUES (?, ?, ?)
        ON CONFLICT(habit_id, activity_date)
        DO UPDATE SET completed = excluded.completed
        """,
        (habit_id, today, completed)
    )

    conn.commit()
    conn.close()

    rk_create_daily_snapshot()

    return {
        "id": habit_id,
        "completed": completed
    }


@app.delete("/api/habits/{habit_id}")
def rk_delete_habit(habit_id: int):
    ensure_habits_table()

    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM habits WHERE id = ?",
        (habit_id,)
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Habit not found")

    conn.commit()
    conn.close()

    rk_create_daily_snapshot()

    return {
        "deleted": True,
        "id": habit_id
    }


# ============================================================
# RK OS - GOALS API
# ============================================================

def ensure_goals_table():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            target_date TEXT,
            progress INTEGER NOT NULL DEFAULT 0
        )
    """)

    columns = [
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(goals)"
        ).fetchall()
    ]

    if "target_date" not in columns:
        conn.execute(
            "ALTER TABLE goals ADD COLUMN target_date TEXT"
        )

    if "progress" not in columns:
        conn.execute(
            "ALTER TABLE goals ADD COLUMN progress INTEGER DEFAULT 0"
        )

    conn.commit()
    conn.close()


def ensure_activity_history_table():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_date TEXT NOT NULL UNIQUE,
            tasks_total INTEGER NOT NULL DEFAULT 0,
            tasks_completed INTEGER NOT NULL DEFAULT 0,
            habits_total INTEGER NOT NULL DEFAULT 0,
            habits_completed INTEGER NOT NULL DEFAULT 0,
            goals_total INTEGER NOT NULL DEFAULT 0,
            goal_progress INTEGER NOT NULL DEFAULT 0,
            overall_score INTEGER NOT NULL DEFAULT 0
        )
    """)

    columns = [
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(activity_history)"
        ).fetchall()
    ]

    required_columns = {
        "activity_date": "TEXT NOT NULL DEFAULT ''",
        "tasks_total": "INTEGER NOT NULL DEFAULT 0",
        "tasks_completed": "INTEGER NOT NULL DEFAULT 0",
        "habits_total": "INTEGER NOT NULL DEFAULT 0",
        "habits_completed": "INTEGER NOT NULL DEFAULT 0",
        "goals_total": "INTEGER NOT NULL DEFAULT 0",
        "goal_progress": "INTEGER NOT NULL DEFAULT 0",
        "overall_score": "INTEGER NOT NULL DEFAULT 0",
    }

    for column_name, definition in required_columns.items():
        if column_name not in columns:
            conn.execute(
                f"ALTER TABLE activity_history ADD COLUMN {column_name} {definition}"
            )

    conn.commit()
    conn.close()


@app.get("/api/goals")
def rk_get_goals():
    ensure_goals_table()

    conn = get_db()

    goals = conn.execute(
        """
        SELECT id, title, target_date, progress
        FROM goals
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    result = []

    for goal in goals:

        progress = goal[3]

        if progress is None:
            progress = 0

        progress = max(
            0,
            min(100, int(progress))
        )

        result.append({
            "id": goal[0],
            "title": goal[1],
            "target_date": goal[2],
            "progress": progress
        })

    return result


@app.post("/api/goals")
def rk_create_goal(goal: dict):
    ensure_goals_table()

    title = str(goal.get("title") or "").strip()
    target_date = goal.get("target_date")

    if not title:
        raise HTTPException(status_code=422, detail="Goal title is required")

    progress = goal.get("progress", 0)

    try:
        progress = int(progress)
    except (TypeError, ValueError):
        progress = 0

    progress = max(
        0,
        min(100, progress)
    )

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO goals
        (title, target_date, progress)
        VALUES (?, ?, ?)
        """,
        (
            title,
            target_date,
            progress
        )
    )

    conn.commit()

    goal_id = cursor.lastrowid

    conn.close()

    rk_create_daily_snapshot()

    return {
        "id": goal_id,
        "title": title,
        "target_date": target_date,
        "progress": progress
    }


@app.put("/api/goals/{goal_id}")
def rk_update_goal(
    goal_id: int,
    goal: dict
):
    ensure_goals_table()

    conn = get_db()

    existing = conn.execute(
        """
        SELECT title, target_date, progress
        FROM goals
        WHERE id = ?
        """,
        (goal_id,)
    ).fetchone()

    if existing is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found")

    title = goal.get(
        "title",
        existing[0]
    )

    target_date = goal.get(
        "target_date",
        existing[1]
    )

    progress = goal.get(
        "progress",
        existing[2]
    )

    title = str(title).strip()

    if not title:
        conn.close()
        raise HTTPException(status_code=422, detail="Goal title is required")

    try:
        progress = int(progress)
    except (TypeError, ValueError):
        progress = 0

    progress = max(
        0,
        min(100, progress)
    )

    conn.execute(
        """
        UPDATE goals
        SET title = ?,
            target_date = ?,
            progress = ?
        WHERE id = ?
        """,
        (
            title,
            target_date,
            progress,
            goal_id
        )
    )

    conn.commit()
    conn.close()

    rk_create_daily_snapshot()

    return {
        "id": goal_id,
        "title": title,
        "target_date": target_date,
        "progress": progress
    }


@app.delete("/api/goals/{goal_id}")
def rk_delete_goal(goal_id: int):
    ensure_goals_table()

    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM goals WHERE id = ?",
        (goal_id,)
    )

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found")

    conn.commit()
    conn.close()

    rk_create_daily_snapshot()

    return {
        "deleted": True,
        "id": goal_id
    }


# ============================================================
# BK OS - STUDY CONTENT FOUNDATION
# ============================================================

def ensure_study_tables():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(subject_id, name),
            FOREIGN KEY(subject_id) REFERENCES study_subjects(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            topic_id INTEGER,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(subject_id) REFERENCES study_subjects(id),
            FOREIGN KEY(topic_id) REFERENCES study_topics(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            topic_id INTEGER,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            duration_minutes INTEGER NOT NULL DEFAULT 0,
            session_type TEXT NOT NULL DEFAULT 'study',
            FOREIGN KEY(subject_id) REFERENCES study_subjects(id),
            FOREIGN KEY(topic_id) REFERENCES study_topics(id)
        )
    """)

    for table_name, column_name, column_def in [
        ("study_subjects", "description", "TEXT"),
        ("study_subjects", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
        ("study_subjects", "active", "INTEGER NOT NULL DEFAULT 1"),
        ("study_topics", "description", "TEXT"),
        ("study_topics", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
        ("study_topics", "active", "INTEGER NOT NULL DEFAULT 1"),
        ("study_notes", "topic_id", "INTEGER"),
        ("study_notes", "created_at", "TEXT NOT NULL DEFAULT ''"),
        ("study_notes", "updated_at", "TEXT NOT NULL DEFAULT ''"),
        ("study_notes", "active", "INTEGER NOT NULL DEFAULT 1"),
        ("study_sessions", "topic_id", "INTEGER"),
        ("study_sessions", "completed_at", "TEXT"),
        ("study_sessions", "duration_minutes", "INTEGER NOT NULL DEFAULT 0"),
        ("study_sessions", "session_type", "TEXT NOT NULL DEFAULT 'study'"),
    ]:
        columns = [
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        ]
        if column_name not in columns:
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
            )

    conn.commit()

    subject_count = conn.execute(
        "SELECT COUNT(*) FROM study_subjects"
    ).fetchone()[0]

    if subject_count == 0:
        default_subjects = [
            ("Quantitative Aptitude", "Core arithmetic, algebra, geometry, and data interpretation skills."),
            ("General Intelligence & Reasoning", "Verbal and non-verbal reasoning patterns, logic, and analytical thinking."),
            ("English Language & Comprehension", "Grammar, vocabulary, comprehension, and sentence improvement."),
            ("General Awareness", "Static GK, polity, history, economy, and current affairs."),
        ]

        for order_index, (name, description) in enumerate(default_subjects):
            conn.execute(
                "INSERT INTO study_subjects (name, description, sort_order, active) VALUES (?, ?, ?, 1)",
                (name, description, order_index),
            )

        subject_map = {
            row[1]: row[0]
            for row in conn.execute(
                "SELECT id, name FROM study_subjects ORDER BY sort_order, id"
            ).fetchall()
        }

        default_topics = {
            "Quantitative Aptitude": [
                "Number System", "Percentage", "Ratio & Proportion", "Average", "Profit & Loss",
                "Simple Interest", "Compound Interest", "Time & Work", "Time, Speed & Distance",
                "Algebra", "Geometry", "Mensuration", "Trigonometry", "Data Interpretation"
            ],
            "General Intelligence & Reasoning": [
                "Analogy", "Classification", "Series", "Coding-Decoding", "Blood Relations",
                "Direction & Distance", "Syllogism", "Venn Diagram", "Mathematical Operations",
                "Ranking", "Seating Arrangement", "Statement & Conclusion", "Non-Verbal Reasoning"
            ],
            "English Language & Comprehension": [
                "Grammar", "Error Detection", "Sentence Improvement", "Fill in the Blanks",
                "Vocabulary", "Synonyms", "Antonyms", "Idioms & Phrases", "One Word Substitution",
                "Cloze Test", "Reading Comprehension", "Active & Passive Voice", "Direct & Indirect Speech"
            ],
            "General Awareness": [
                "Indian History", "Indian Geography", "Indian Polity", "Indian Economy",
                "General Science", "Physics", "Chemistry", "Biology", "Static GK", "Current Affairs"
            ],
        }

        for subject_name, topic_names in default_topics.items():
            subject_id = subject_map[subject_name]
            for order_index, topic_name in enumerate(topic_names):
                conn.execute(
                    "INSERT OR IGNORE INTO study_topics (subject_id, name, description, sort_order, active) VALUES (?, ?, ?, ?, 1)",
                    (
                        subject_id,
                        topic_name,
                        f"Core revision and practice focus for {topic_name}.",
                        order_index,
                    ),
                )

    note_count = conn.execute(
        "SELECT COUNT(*) FROM study_notes"
    ).fetchone()[0]
    if note_count == 0:
        demo_notes = [
            (
                "Quantitative Aptitude",
                "Percentage",
                "Demo: Understanding percentages",
                "Demo content - foundational explanation only; not verified SSC exam material.\n\nA percentage expresses a quantity as parts per hundred. To convert a fraction to a percentage, multiply it by 100. To find p percent of a value, multiply the value by p/100.\n\nWhen comparing a change with an original value, use the original value as the base: percentage change = (change / original value) x 100.",
            ),
            (
                "Quantitative Aptitude",
                "Number System",
                "Demo: Number system study outline",
                "Demo content - a study outline, not verified SSC exam material.\n\nReview the different sets of numbers, place value, divisibility, factors and multiples. For each rule, note its conditions and test it with a small example.\n\nThis outline is a structure for personal revision; it does not claim to cover a particular exam syllabus or question.",
            ),
            (
                "English Language & Comprehension",
                "Grammar",
                "Demo: Grammar revision outline",
                "Demo content - a study outline, not verified SSC exam material.\n\nOrganize revision by concept: parts of speech, agreement, tense, modifiers, and sentence structure. For each concept, write the rule in your own words and add one example you have checked against a trusted grammar reference.\n\nNo exam question or answer is included in this demo note.",
            ),
        ]
        now = datetime.now().isoformat(timespec="seconds")
        for subject_name, topic_name, title, content in demo_notes:
            topic = conn.execute(
                """
                SELECT t.id, s.id
                FROM study_topics AS t
                JOIN study_subjects AS s ON s.id = t.subject_id
                WHERE s.name = ? AND t.name = ?
                """,
                (subject_name, topic_name),
            ).fetchone()
            if topic:
                conn.execute(
                    """
                    INSERT INTO study_notes (
                        subject_id, topic_id, title, content, created_at, updated_at, active
                    ) VALUES (?, ?, ?, ?, ?, ?, 1)
                    """,
                    (topic[1], topic[0], title, content, now, now),
                )

    conn.commit()
    conn.close()


def ensure_practice_tables():
    ensure_study_tables()
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            explanation TEXT NOT NULL,
            difficulty TEXT NOT NULL DEFAULT 'Medium',
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(subject_id) REFERENCES study_subjects(id),
            FOREIGN KEY(topic_id) REFERENCES study_topics(id)
        );

        CREATE TABLE IF NOT EXISTS practice_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            selected_option TEXT NOT NULL,
            is_correct INTEGER NOT NULL DEFAULT 0,
            answered_at TEXT NOT NULL,
            FOREIGN KEY(question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS revision_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            reviewed_at TEXT NOT NULL,
            FOREIGN KEY(topic_id) REFERENCES study_topics(id)
        );

        CREATE INDEX IF NOT EXISTS idx_questions_subject_topic
            ON questions(subject_id, topic_id, difficulty);
        CREATE INDEX IF NOT EXISTS idx_practice_attempts_question_date
            ON practice_attempts(question_id, answered_at);
        CREATE INDEX IF NOT EXISTS idx_revision_reviews_topic_date
            ON revision_reviews(topic_id, reviewed_at);
    """)

    question_count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    if question_count == 0:
        demo_questions = [
            ("Quantitative Aptitude", "Percentage", "What is 25% of 240?", "40", "50", "60", "80", "C", "25% is one quarter; 240 / 4 = 60.", "Easy"),
            ("Quantitative Aptitude", "Percentage", "A value of 200 is increased by 15%. What is the new value?", "230", "215", "225", "240", "A", "15% of 200 is 30, so the new value is 200 + 30 = 230.", "Medium"),
            ("Quantitative Aptitude", "Number System", "What is the least common multiple of 4 and 6?", "8", "12", "18", "24", "B", "The smallest positive number divisible by both 4 and 6 is 12.", "Easy"),
            ("General Intelligence & Reasoning", "Series", "Which number comes next: 2, 4, 8, 16, ...?", "20", "24", "30", "32", "D", "Each term is twice the previous term, so 16 x 2 = 32.", "Easy"),
            ("English Language & Comprehension", "Grammar", "Choose the standard plural form of 'child'.", "children", "childs", "childes", "childrens", "A", "The standard plural form of child is children.", "Easy"),
            ("General Awareness", "General Science", "Which chemical formula represents water?", "CO2", "H2O", "O2", "NaCl", "B", "A water molecule contains two hydrogen atoms and one oxygen atom: H2O.", "Easy"),
        ]
        now = datetime.now().isoformat(timespec="seconds")
        source = "Demo question — replace with verified SSC source"
        for row in demo_questions:
            subject_name, topic_name, *question_fields = row
            topic = conn.execute(
                """
                SELECT s.id, t.id
                FROM study_subjects AS s
                JOIN study_topics AS t ON t.subject_id = s.id
                WHERE s.name = ? AND t.name = ?
                """,
                (subject_name, topic_name),
            ).fetchone()
            if topic:
                conn.execute(
                    """
                    INSERT INTO questions (
                        subject_id, topic_id, question_text,
                        option_a, option_b, option_c, option_d,
                        correct_option, explanation, difficulty, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (topic[0], topic[1], *question_fields, source, now),
                )

    conn.commit()
    conn.close()


def ensure_quiz_tables():
    ensure_practice_tables()
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            topic_id INTEGER,
            difficulty TEXT NOT NULL DEFAULT 'Mixed',
            total_questions INTEGER NOT NULL DEFAULT 0,
            correct_answers INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            question_ids TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY(subject_id) REFERENCES study_subjects(id),
            FOREIGN KEY(topic_id) REFERENCES study_topics(id)
        );

        CREATE TABLE IF NOT EXISTS quiz_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            selected_option TEXT NOT NULL,
            is_correct INTEGER NOT NULL DEFAULT 0,
            answered_at TEXT NOT NULL,
            UNIQUE(session_id, question_id),
            FOREIGN KEY(session_id) REFERENCES quiz_sessions(id),
            FOREIGN KEY(question_id) REFERENCES questions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_quiz_sessions_completed
            ON quiz_sessions(completed_at);
        CREATE INDEX IF NOT EXISTS idx_quiz_answers_session
            ON quiz_answers(session_id, question_id);
        CREATE INDEX IF NOT EXISTS idx_quiz_answers_question
            ON quiz_answers(question_id, answered_at);
    """)
    columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(quiz_sessions)").fetchall()
    ]
    if "question_ids" not in columns:
        conn.execute(
            "ALTER TABLE quiz_sessions ADD COLUMN question_ids TEXT NOT NULL DEFAULT '[]'"
        )
    conn.commit()
    conn.close()


def _rk_get_combined_weak_topics(conn, limit=50):
    rows = conn.execute(
        """
        WITH topic_attempts AS (
            SELECT q.subject_id, q.topic_id, COUNT(pa.id) AS attempted,
                SUM(pa.is_correct) AS correct, MAX(pa.answered_at) AS last_activity
            FROM practice_attempts AS pa
            JOIN questions AS q ON q.id = pa.question_id
            GROUP BY q.subject_id, q.topic_id
            UNION ALL
            SELECT q.subject_id, q.topic_id, COUNT(qa.id) AS attempted,
                SUM(qa.is_correct) AS correct, MAX(qa.answered_at) AS last_activity
            FROM quiz_answers AS qa
            JOIN questions AS q ON q.id = qa.question_id
            GROUP BY q.subject_id, q.topic_id
        ), totals AS (
            SELECT subject_id, topic_id, SUM(attempted) AS questions_attempted,
                SUM(correct) AS correct, MAX(last_activity) AS last_activity
            FROM topic_attempts
            GROUP BY subject_id, topic_id
        )
        SELECT totals.subject_id, totals.topic_id, s.name, t.name,
            totals.questions_attempted, totals.correct,
            ROUND(100.0 * totals.correct / totals.questions_attempted, 1),
            totals.last_activity
        FROM totals
        JOIN study_subjects AS s ON s.id = totals.subject_id
        JOIN study_topics AS t ON t.id = totals.topic_id
        WHERE 100.0 * totals.correct / totals.questions_attempted < 70
        ORDER BY 100.0 * totals.correct / totals.questions_attempted, totals.last_activity DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "subject_id": row[0],
            "topic_id": row[1],
            "subject_name": row[2],
            "topic_name": row[3],
            "questions_attempted": int(row[4] or 0),
            "correct": int(row[5] or 0),
            "accuracy": float(row[6] or 0),
            "last_attempted": row[7],
        }
        for row in rows
    ]


def rk_get_quiz_dashboard_summary():
    return rk_get_quiz_statistics()


def _rk_get_weak_topics(conn, subject_id=None, limit=50):
    query = """
        SELECT q.subject_id, q.topic_id, s.name, t.name,
            COUNT(pa.id) AS questions_attempted,
            SUM(pa.is_correct) AS correct,
            ROUND(100.0 * SUM(pa.is_correct) / COUNT(pa.id), 1) AS accuracy,
            MAX(pa.answered_at) AS last_attempted
        FROM practice_attempts AS pa
        JOIN questions AS q ON q.id = pa.question_id
        JOIN study_subjects AS s ON s.id = q.subject_id
        JOIN study_topics AS t ON t.id = q.topic_id
    """
    params = []
    if subject_id is not None:
        query += " WHERE q.subject_id = ?"
        params.append(subject_id)
    query += " GROUP BY q.subject_id, q.topic_id HAVING 100.0 * SUM(pa.is_correct) / COUNT(pa.id) < 70 ORDER BY accuracy, last_attempted DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, tuple(params)).fetchall()
    return [
        {
            "subject_id": row[0],
            "topic_id": row[1],
            "subject_name": row[2],
            "topic_name": row[3],
            "questions_attempted": int(row[4] or 0),
            "correct": int(row[5] or 0),
            "accuracy": float(row[6] or 0),
            "last_attempted": row[7],
        }
        for row in rows
    ]


@app.get("/api/quiz/configuration")
def rk_get_quiz_configuration(
    subject_id: int | None = None,
    topic_id: int | None = None,
    difficulty: str = "Mixed",
):
    ensure_quiz_tables()
    conn = get_db()
    subjects = conn.execute(
        "SELECT id, name FROM study_subjects WHERE active = 1 ORDER BY sort_order, id"
    ).fetchall()
    if subject_id is None:
        topic_rows = conn.execute(
            "SELECT id, subject_id, name FROM study_topics WHERE active = 1 ORDER BY subject_id, sort_order, id"
        ).fetchall()
    else:
        topic_rows = conn.execute(
            "SELECT id, subject_id, name FROM study_topics WHERE active = 1 AND subject_id = ? ORDER BY sort_order, id",
            (subject_id,),
        ).fetchall()
    filters = ["subject_id = ?"]
    params = [subject_id] if subject_id is not None else []
    if subject_id is None:
        filters = []
    if topic_id is not None:
        filters.append("topic_id = ?")
        params.append(topic_id)
    selected_difficulty = difficulty.strip().title() if difficulty else "Mixed"
    if selected_difficulty not in {"Easy", "Medium", "Hard", "Mixed"}:
        conn.close()
        raise HTTPException(status_code=422, detail="Difficulty must be Easy, Medium, Hard, or Mixed")
    if selected_difficulty != "Mixed":
        filters.append("difficulty = ?")
        params.append(selected_difficulty)
    question_filter = " WHERE " + " AND ".join(filters) if filters else ""
    available_questions = conn.execute(
        f"SELECT COUNT(*) FROM questions{question_filter}",
        tuple(params),
    ).fetchone()[0]
    conn.close()
    topics = [{"id": None, "subject_id": subject_id, "name": "All Topics"}]
    topics.extend(
        {"id": row[0], "subject_id": row[1], "name": row[2]}
        for row in topic_rows
    )
    return {
        "subjects": [{"id": row[0], "name": row[1]} for row in subjects],
        "topics": topics,
        "difficulties": ["Easy", "Medium", "Hard", "Mixed"],
        "question_counts": [5, 10, 15, 20],
        "available_questions": int(available_questions or 0),
    }


@app.post("/api/quiz/sessions")
def rk_start_quiz_session(quiz: dict):
    ensure_quiz_tables()
    try:
        subject_id = int(quiz.get("subject_id") or 0)
        requested_count = int(quiz.get("total_questions") or 10)
        topic_id = int(quiz["topic_id"]) if quiz.get("topic_id") not in (None, "", "all") else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid quiz configuration")
    difficulty = str(quiz.get("difficulty") or "Mixed").strip().title()
    if subject_id <= 0:
        raise HTTPException(status_code=422, detail="Subject is required")
    if requested_count not in {5, 10, 15, 20}:
        raise HTTPException(status_code=422, detail="Question count must be 5, 10, 15, or 20")
    if difficulty not in {"Easy", "Medium", "Hard", "Mixed"}:
        raise HTTPException(status_code=422, detail="Difficulty must be Easy, Medium, Hard, or Mixed")

    conn = get_db()
    subject = conn.execute(
        "SELECT id FROM study_subjects WHERE id = ? AND active = 1",
        (subject_id,),
    ).fetchone()
    if subject is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz subject not found")
    if topic_id is not None:
        topic = conn.execute(
            "SELECT id FROM study_topics WHERE id = ? AND subject_id = ? AND active = 1",
            (topic_id, subject_id),
        ).fetchone()
        if topic is None:
            conn.close()
            raise HTTPException(status_code=422, detail="Topic does not belong to the selected subject")

    filters = ["subject_id = ?"]
    params = [subject_id]
    if topic_id is not None:
        filters.append("topic_id = ?")
        params.append(topic_id)
    if difficulty != "Mixed":
        filters.append("difficulty = ?")
        params.append(difficulty)
    params.append(requested_count)
    questions = conn.execute(
        f"""
        SELECT id, subject_id, topic_id, question_text, option_a, option_b,
            option_c, option_d, difficulty, source
        FROM questions
        WHERE {' AND '.join(filters)}
        ORDER BY RANDOM()
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    if not questions:
        conn.close()
        raise HTTPException(status_code=409, detail="No questions are available for this quiz configuration")

    started_at = datetime.now().isoformat(timespec="seconds")
    question_ids = [int(question[0]) for question in questions]
    cursor = conn.execute(
        """
        INSERT INTO quiz_sessions (
            subject_id, topic_id, difficulty, total_questions,
            correct_answers, started_at, question_ids
        ) VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (subject_id, topic_id, difficulty, len(questions), started_at, json.dumps(question_ids)),
    )
    conn.commit()
    session_id = cursor.lastrowid
    subject_name = conn.execute("SELECT name FROM study_subjects WHERE id = ?", (subject_id,)).fetchone()[0]
    topic_name = conn.execute("SELECT name FROM study_topics WHERE id = ?", (topic_id,)).fetchone()[0] if topic_id else "All Topics"
    conn.close()
    return {
        "id": session_id,
        "subject_id": subject_id,
        "subject_name": subject_name,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "difficulty": difficulty,
        "total_questions": len(questions),
        "correct_answers": 0,
        "started_at": started_at,
        "completed_at": None,
        "questions": [
            {
                "id": row[0], "subject_id": row[1], "topic_id": row[2],
                "question_text": row[3], "option_a": row[4], "option_b": row[5],
                "option_c": row[6], "option_d": row[7],
                "difficulty": row[8], "source": row[9],
            }
            for row in questions
        ],
    }


@app.post("/api/quiz/sessions/{session_id}/answers")
def rk_submit_quiz_answer(session_id: int, answer: dict):
    ensure_quiz_tables()
    try:
        question_id = int(answer.get("question_id") or 0)
    except (TypeError, ValueError):
        question_id = 0
    selected_option = str(answer.get("selected_option") or "").strip().upper()
    if selected_option not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=422, detail="Select one of options A, B, C, or D")

    conn = get_db()
    session = conn.execute(
        "SELECT subject_id, topic_id, difficulty, total_questions, completed_at, question_ids FROM quiz_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz session not found")
    if session[4] is not None:
        conn.close()
        raise HTTPException(status_code=409, detail="Quiz session is already complete")
    try:
        question_ids = json.loads(session[5] or "[]")
    except (TypeError, ValueError):
        question_ids = []
    if question_id not in question_ids:
        conn.close()
        raise HTTPException(status_code=422, detail="Question is not part of this quiz")
    answered_count = conn.execute(
        "SELECT COUNT(*) FROM quiz_answers WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    if answered_count >= session[3]:
        conn.close()
        raise HTTPException(status_code=409, detail="All quiz questions have already been answered")
    question = conn.execute(
        "SELECT correct_option, explanation FROM questions WHERE id = ?",
        (question_id,),
    ).fetchone()
    if question is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz question not found")
    answered_at = datetime.now().isoformat(timespec="seconds")
    is_correct = int(selected_option == question[0])
    try:
        conn.execute(
            "INSERT INTO quiz_answers (session_id, question_id, selected_option, is_correct, answered_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, question_id, selected_option, is_correct, answered_at),
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="This quiz question was already answered")
    conn.execute(
        "UPDATE quiz_sessions SET correct_answers = correct_answers + ? WHERE id = ?",
        (is_correct, session_id),
    )
    conn.commit()
    conn.close()
    return {
        "session_id": session_id,
        "question_id": question_id,
        "selected_option": selected_option,
        "is_correct": bool(is_correct),
        "correct_option": question[0],
        "explanation": question[1],
        "answered_at": answered_at,
    }


def _rk_quiz_result(session_id, total_questions, correct_answers, started_at, completed_at):
    total = int(total_questions or 0)
    correct = int(correct_answers or 0)
    try:
        duration = max(0, int((datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds()))
    except (TypeError, ValueError):
        duration = 0
    return {
        "id": session_id,
        "total_questions": total,
        "correct_answers": correct,
        "incorrect_answers": total - correct,
        "accuracy": round(100 * correct / total) if total else 0,
        "time_taken_seconds": duration,
        "started_at": started_at,
        "completed_at": completed_at,
    }


@app.post("/api/quiz/sessions/{session_id}/complete")
def rk_complete_quiz_session(session_id: int):
    ensure_quiz_tables()
    conn = get_db()
    session = conn.execute(
        "SELECT total_questions, started_at, completed_at FROM quiz_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz session not found")
    if session[2] is not None:
        result = _rk_quiz_result(session_id, session[0], conn.execute(
            "SELECT correct_answers FROM quiz_sessions WHERE id = ?", (session_id,)
        ).fetchone()[0], session[1], session[2])
        conn.close()
        return result
    answers = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(is_correct), 0) FROM quiz_answers WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if int(answers[0] or 0) != int(session[0] or 0):
        conn.close()
        raise HTTPException(status_code=409, detail="Answer every question before completing the quiz")
    completed_at = datetime.now().isoformat(timespec="seconds")
    correct_answers = int(answers[1] or 0)
    conn.execute(
        "UPDATE quiz_sessions SET correct_answers = ?, completed_at = ? WHERE id = ?",
        (correct_answers, completed_at, session_id),
    )
    conn.commit()
    conn.close()
    return _rk_quiz_result(session_id, session[0], correct_answers, session[1], completed_at)


@app.get("/api/quiz/statistics")
def rk_get_quiz_statistics():
    ensure_quiz_tables()
    conn = get_db()
    stats = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(total_questions), 0),
            COALESCE(SUM(correct_answers), 0),
            COALESCE(MAX(100.0 * correct_answers / NULLIF(total_questions, 0)), 0)
        FROM quiz_sessions
        WHERE completed_at IS NOT NULL
        """
    ).fetchone()
    today = date.today().isoformat()
    today_stats = conn.execute(
        """
        SELECT COUNT(qa.id), COALESCE(SUM(qa.is_correct), 0)
        FROM quiz_answers AS qa
        JOIN quiz_sessions AS qs ON qs.id = qa.session_id
        WHERE qs.completed_at IS NOT NULL AND DATE(qa.answered_at) = ?
        """,
        (today,),
    ).fetchone()
    today_sessions = conn.execute(
        "SELECT COUNT(*) FROM quiz_sessions WHERE completed_at IS NOT NULL AND DATE(completed_at) = ?",
        (today,),
    ).fetchone()[0]
    weak_topics = _rk_get_combined_weak_topics(conn)
    conn.close()
    attempts = int(stats[0] or 0)
    questions = int(stats[1] or 0)
    correct = int(stats[2] or 0)
    return {
        "attempts": attempts,
        "questions": questions,
        "correct": correct,
        "incorrect": questions - correct,
        "accuracy": round(100 * correct / questions) if questions else 0,
        "best_accuracy": round(float(stats[3] or 0)),
        "weak_topics": len(weak_topics),
        "today": {
            "attempts": int(today_sessions or 0),
            "questions": int(today_stats[0] or 0),
            "correct": int(today_stats[1] or 0),
            "accuracy": round(100 * int(today_stats[1] or 0) / int(today_stats[0] or 1)) if today_stats[0] else 0,
        },
    }


@app.get("/api/quiz/history")
def rk_get_quiz_history(limit: int = 20):
    ensure_quiz_tables()
    safe_limit = max(1, min(int(limit), 100))
    conn = get_db()
    rows = conn.execute(
        """
        SELECT qs.id, qs.subject_id, qs.topic_id, s.name, t.name,
            qs.difficulty, qs.total_questions, qs.correct_answers,
            qs.started_at, qs.completed_at
        FROM quiz_sessions AS qs
        JOIN study_subjects AS s ON s.id = qs.subject_id
        LEFT JOIN study_topics AS t ON t.id = qs.topic_id
        WHERE qs.completed_at IS NOT NULL
        ORDER BY qs.completed_at DESC, qs.id DESC
        LIMIT ?
        """,
        (safe_limit,),
    ).fetchall()
    conn.close()
    history = []
    for row in rows:
        result = _rk_quiz_result(row[0], row[6], row[7], row[8], row[9])
        result.update({
            "subject_id": row[1],
            "topic_id": row[2],
            "subject_name": row[3],
            "topic_name": row[4] or "All Topics",
            "difficulty": row[5],
        })
        history.append(result)
    return history


def rk_get_practice_dashboard_summary():
    ensure_practice_tables()
    today = date.today().isoformat()
    conn = get_db()
    row = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(is_correct), 0)
        FROM practice_attempts
        WHERE DATE(answered_at) = ?
        """,
        (today,),
    ).fetchone()
    conn.close()
    total = int(row[0] or 0)
    correct = int(row[1] or 0)
    return {
        "today_questions": total,
        "today_correct": correct,
        "today_accuracy": round(100 * correct / total) if total else 0,
    }


@app.get("/api/practice/questions")
def rk_get_practice_questions(
    subject_id: int | None = None,
    topic_id: int | None = None,
    difficulty: str = "Mixed",
    limit: int = 50,
):
    ensure_practice_tables()
    difficulty = difficulty.strip().title() if difficulty else "Mixed"
    if difficulty not in {"Easy", "Medium", "Hard", "Mixed"}:
        raise HTTPException(status_code=422, detail="Difficulty must be Easy, Medium, Hard, or Mixed")
    safe_limit = max(1, min(int(limit), 100))
    filters = []
    params = []
    if subject_id is not None:
        filters.append("q.subject_id = ?")
        params.append(subject_id)
    if topic_id is not None:
        filters.append("q.topic_id = ?")
        params.append(topic_id)
    if difficulty != "Mixed":
        filters.append("q.difficulty = ?")
        params.append(difficulty)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    params.append(safe_limit)
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT q.id, q.subject_id, q.topic_id, s.name, t.name,
            q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
            q.difficulty, q.source
        FROM questions AS q
        JOIN study_subjects AS s ON s.id = q.subject_id
        JOIN study_topics AS t ON t.id = q.topic_id
        {where}
        ORDER BY q.id
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row[0], "subject_id": row[1], "topic_id": row[2],
            "subject_name": row[3], "topic_name": row[4],
            "question_text": row[5], "option_a": row[6], "option_b": row[7],
            "option_c": row[8], "option_d": row[9],
            "difficulty": row[10], "source": row[11],
        }
        for row in rows
    ]


@app.post("/api/practice/attempts")
def rk_create_practice_attempt(attempt: dict):
    ensure_practice_tables()
    try:
        question_id = int(attempt.get("question_id") or 0)
    except (TypeError, ValueError):
        question_id = 0
    selected_option = str(attempt.get("selected_option") or "").strip().upper()
    if selected_option not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=422, detail="Select one of options A, B, C, or D")
    conn = get_db()
    question = conn.execute(
        "SELECT correct_option, explanation FROM questions WHERE id = ?",
        (question_id,),
    ).fetchone()
    if question is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Practice question not found")
    is_correct = int(selected_option == question[0])
    answered_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        "INSERT INTO practice_attempts (question_id, selected_option, is_correct, answered_at) VALUES (?, ?, ?, ?)",
        (question_id, selected_option, is_correct, answered_at),
    )
    conn.commit()
    attempt_id = cursor.lastrowid
    conn.close()
    return {
        "id": attempt_id,
        "question_id": question_id,
        "selected_option": selected_option,
        "is_correct": bool(is_correct),
        "correct_option": question[0],
        "explanation": question[1],
        "answered_at": answered_at,
    }


@app.get("/api/practice/statistics")
def rk_get_practice_statistics(subject_id: int | None = None, topic_id: int | None = None):
    ensure_practice_tables()
    today = date.today().isoformat()
    filters = []
    params = []
    if subject_id is not None:
        filters.append("q.subject_id = ?")
        params.append(subject_id)
    if topic_id is not None:
        filters.append("q.topic_id = ?")
        params.append(topic_id)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    conn = get_db()
    row = conn.execute(
        f"""
        SELECT COUNT(pa.id), COALESCE(SUM(pa.is_correct), 0)
        FROM practice_attempts AS pa JOIN questions AS q ON q.id = pa.question_id
        {where}
        """,
        tuple(params),
    ).fetchone()
    today_filters = filters + ["DATE(pa.answered_at) = ?"]
    today_params = params + [today]
    today_row = conn.execute(
        f"""
        SELECT COUNT(pa.id), COALESCE(SUM(pa.is_correct), 0)
        FROM practice_attempts AS pa JOIN questions AS q ON q.id = pa.question_id
        WHERE {' AND '.join(today_filters)}
        """,
        tuple(today_params),
    ).fetchone()
    weak_topics = _rk_get_weak_topics(conn)
    conn.close()
    total = int(row[0] or 0)
    correct = int(row[1] or 0)
    today_total = int(today_row[0] or 0)
    today_correct = int(today_row[1] or 0)
    return {
        "total_questions": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": round(100 * correct / total) if total else 0,
        "today": {
            "total_questions": today_total,
            "correct": today_correct,
            "accuracy": round(100 * today_correct / today_total) if today_total else 0,
        },
        "weak_topics": len(weak_topics),
    }


@app.get("/api/practice/weak-topics")
def rk_get_practice_weak_topics(subject_id: int | None = None):
    ensure_practice_tables()
    conn = get_db()
    weak_topics = _rk_get_weak_topics(conn, subject_id=subject_id)
    conn.close()
    return weak_topics


@app.get("/api/revision/topics")
def rk_get_revision_topics():
    ensure_quiz_tables()
    today = date.today().isoformat()
    conn = get_db()
    weak_areas = _rk_get_combined_weak_topics(conn)
    recent_topics = conn.execute(
        """
        SELECT q.subject_id, q.topic_id, s.name, t.name, COUNT(pa.id),
            SUM(pa.is_correct), ROUND(100.0 * SUM(pa.is_correct) / COUNT(pa.id)),
            MAX(pa.answered_at),
            EXISTS(SELECT 1 FROM revision_reviews rr
                WHERE rr.topic_id = q.topic_id AND DATE(rr.reviewed_at) = ?)
        FROM practice_attempts AS pa
        JOIN questions AS q ON q.id = pa.question_id
        JOIN study_subjects AS s ON s.id = q.subject_id
        JOIN study_topics AS t ON t.id = q.topic_id
        GROUP BY q.subject_id, q.topic_id
        ORDER BY MAX(pa.answered_at) DESC
        LIMIT 8
        """,
        (today,),
    ).fetchall()
    recently_studied = conn.execute(
        """
        SELECT ss.subject_id, ss.topic_id, s.name, t.name,
            MAX(COALESCE(ss.completed_at, ss.started_at)) AS last_studied,
            EXISTS(SELECT 1 FROM revision_reviews rr
                WHERE rr.topic_id = ss.topic_id AND DATE(rr.reviewed_at) = ?)
        FROM study_sessions AS ss
        JOIN study_subjects AS s ON s.id = ss.subject_id
        JOIN study_topics AS t ON t.id = ss.topic_id
        WHERE ss.topic_id IS NOT NULL AND ss.session_type = 'study'
        GROUP BY ss.subject_id, ss.topic_id
        ORDER BY last_studied DESC
        LIMIT 8
        """,
        (today,),
    ).fetchall()
    today_revision_count = conn.execute(
        "SELECT COUNT(*) FROM revision_reviews WHERE DATE(reviewed_at) = ?",
        (today,),
    ).fetchone()[0]
    conn.close()
    return {
        "today_revision_count": int(today_revision_count or 0),
        "weak_areas": weak_areas,
        "recent_topics": [
            {
                "subject_id": row[0], "topic_id": row[1], "subject_name": row[2],
                "topic_name": row[3], "questions_attempted": int(row[4] or 0),
                "correct": int(row[5] or 0), "accuracy": float(row[6] or 0),
                "last_studied": row[7], "reviewed_today": bool(row[8]),
            }
            for row in recent_topics
        ],
        "recently_studied": [
            {
                "subject_id": row[0], "topic_id": row[1], "subject_name": row[2],
                "topic_name": row[3], "last_studied": row[4],
                "reviewed_today": bool(row[5]),
            }
            for row in recently_studied
        ],
    }


@app.post("/api/revision/reviews")
def rk_mark_revision_reviewed(review: dict):
    ensure_practice_tables()
    try:
        topic_id = int(review.get("topic_id") or 0)
    except (TypeError, ValueError):
        topic_id = 0
    conn = get_db()
    topic = conn.execute(
        "SELECT id FROM study_topics WHERE id = ? AND active = 1",
        (topic_id,),
    ).fetchone()
    if topic is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Revision topic not found")
    reviewed_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        "INSERT INTO revision_reviews (topic_id, reviewed_at) VALUES (?, ?)",
        (topic_id, reviewed_at),
    )
    conn.commit()
    review_id = cursor.lastrowid
    conn.close()
    return {"id": review_id, "topic_id": topic_id, "reviewed_at": reviewed_at}


def rk_get_study_dashboard_summary():
    ensure_practice_tables()
    today = date.today().isoformat()

    conn = get_db()
    study_row = conn.execute(
        """
        SELECT
            COUNT(*) AS sessions,
            COALESCE(SUM(duration_minutes), 0) AS minutes,
            COUNT(DISTINCT topic_id) AS topics
        FROM study_sessions
        WHERE DATE(COALESCE(completed_at, started_at)) = ?
                    AND session_type = 'study'
        """,
        (today,),
    ).fetchone()
    conn.close()

    return {
        "sessions": int(study_row[0] or 0),
        "study_minutes": int(study_row[1] or 0),
        "topics_studied": int(study_row[2] or 0),
    }


@app.get("/api/study/subjects")
def rk_get_study_subjects():
    ensure_study_tables()

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, name, description, sort_order, active
        FROM study_subjects
        WHERE active = 1
        ORDER BY sort_order, id
        """
    ).fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "sort_order": row[3],
            "active": bool(row[4]),
        }
        for row in rows
    ]


@app.get("/api/study/topics")
def rk_get_study_topics(subject_id: int | None = None):
    ensure_study_tables()

    conn = get_db()

    if subject_id is not None:
        rows = conn.execute(
            """
            SELECT id, subject_id, name, description, sort_order, active
            FROM study_topics
            WHERE active = 1 AND subject_id = ?
            ORDER BY sort_order, id
            """,
            (subject_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, subject_id, name, description, sort_order, active
            FROM study_topics
            WHERE active = 1
            ORDER BY subject_id, sort_order, id
            """
        ).fetchall()

    conn.close()

    return [
        {
            "id": row[0],
            "subject_id": row[1],
            "name": row[2],
            "description": row[3],
            "sort_order": row[4],
            "active": bool(row[5]),
        }
        for row in rows
    ]


@app.get("/api/study/topics/{topic_id}")
def rk_get_study_topic(topic_id: int):
    ensure_quiz_tables()

    conn = get_db()
    row = conn.execute(
        """
        SELECT t.id, t.subject_id, t.name, t.description, t.sort_order, t.active,
            (SELECT COUNT(*) FROM study_sessions AS ss
                WHERE ss.topic_id = t.id AND ss.session_type = 'study'),
            (SELECT COALESCE(SUM(ss.duration_minutes), 0) FROM study_sessions AS ss
                WHERE ss.topic_id = t.id AND ss.session_type = 'study'),
            (SELECT COUNT(*) FROM questions AS q
                JOIN practice_attempts AS pa ON pa.question_id = q.id
                WHERE q.topic_id = t.id),
            (SELECT COALESCE(SUM(pa.is_correct), 0) FROM questions AS q
                JOIN practice_attempts AS pa ON pa.question_id = q.id
                WHERE q.topic_id = t.id),
            (SELECT MAX(COALESCE(ss.completed_at, ss.started_at))
                FROM study_sessions AS ss WHERE ss.topic_id = t.id AND ss.session_type = 'study'),
            (SELECT COUNT(qa.id) FROM quiz_answers AS qa
                JOIN questions AS q ON q.id = qa.question_id
                JOIN quiz_sessions AS qs ON qs.id = qa.session_id
                WHERE q.topic_id = t.id AND qs.completed_at IS NOT NULL),
            (SELECT COALESCE(SUM(qa.is_correct), 0) FROM quiz_answers AS qa
                JOIN questions AS q ON q.id = qa.question_id
                JOIN quiz_sessions AS qs ON qs.id = qa.session_id
                WHERE q.topic_id = t.id AND qs.completed_at IS NOT NULL)
        FROM study_topics AS t
        WHERE t.id = ? AND t.active = 1
        """,
        (topic_id,),
    ).fetchone()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Study topic not found")

    return {
        "id": row[0],
        "subject_id": row[1],
        "name": row[2],
        "description": row[3],
        "sort_order": row[4],
        "active": bool(row[5]),
        "study_sessions": int(row[6] or 0),
        "study_minutes": int(row[7] or 0),
        "practice_questions": int(row[8] or 0),
        "practice_correct": int(row[9] or 0),
        "practice_accuracy": round(100 * int(row[9] or 0) / int(row[8] or 1)) if row[8] else 0,
        "last_studied": row[10],
        "quiz_questions": int(row[11] or 0),
        "quiz_correct": int(row[12] or 0),
        "quiz_accuracy": round(100 * int(row[12] or 0) / int(row[11] or 1)) if row[11] else 0,
    }


@app.get("/api/study/notes")
def rk_get_study_notes(subject_id: int | None = None, topic_id: int | None = None):
    ensure_study_tables()

    conn = get_db()

    query = """
        SELECT id, subject_id, topic_id, title, content, created_at, updated_at, active
        FROM study_notes
        WHERE active = 1
    """
    params = []

    if subject_id is not None:
        query += " AND subject_id = ?"
        params.append(subject_id)

    if topic_id is not None:
        query += " AND topic_id = ?"
        params.append(topic_id)

    query += " ORDER BY updated_at DESC, id DESC"

    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "subject_id": row[1],
            "topic_id": row[2],
            "title": row[3],
            "content": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "active": bool(row[7]),
        }
        for row in rows
    ]


@app.get("/api/study/notes/{note_id}")
def rk_get_study_note(note_id: int):
    ensure_study_tables()

    conn = get_db()
    row = conn.execute(
        """
        SELECT id, subject_id, topic_id, title, content, created_at, updated_at, active
        FROM study_notes
        WHERE id = ? AND active = 1
        """,
        (note_id,),
    ).fetchone()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Study note not found")

    return {
        "id": row[0],
        "subject_id": row[1],
        "topic_id": row[2],
        "title": row[3],
        "content": row[4],
        "created_at": row[5],
        "updated_at": row[6],
        "active": bool(row[7]),
    }


@app.post("/api/study/notes")
def rk_create_study_note(note: dict):
    ensure_study_tables()

    subject_id = int(note.get("subject_id") or 0)
    topic_id = note.get("topic_id")
    title = str(note.get("title") or "").strip()
    content = str(note.get("content") or "").strip()
    active = 1 if note.get("active", True) else 0

    if not subject_id or not title or not content:
        raise HTTPException(status_code=422, detail="Subject, title and content are required")

    now = datetime.now().isoformat(timespec="seconds")

    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO study_notes (
            subject_id,
            topic_id,
            title,
            content,
            created_at,
            updated_at,
            active
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (subject_id, topic_id, title, content, now, now, active),
    )
    conn.commit()
    note_id = cursor.lastrowid
    conn.close()

    return rk_get_study_note(note_id)


@app.post("/api/study/sessions")
def rk_create_study_session(session: dict):
    ensure_study_tables()

    subject_id = int(session.get("subject_id") or 0)
    topic_id = session.get("topic_id")
    session_type = str(session.get("session_type") or "study").strip() or "study"
    started_at = str(session.get("started_at") or datetime.now().isoformat(timespec="seconds"))
    completed_at = str(session.get("completed_at") or datetime.now().isoformat(timespec="seconds"))
    duration_minutes = int(session.get("duration_minutes") or 0)

    if subject_id <= 0:
        raise HTTPException(status_code=422, detail="Subject is required")

    if duration_minutes <= 0:
        try:
            started_dt = datetime.fromisoformat(started_at)
            completed_dt = datetime.fromisoformat(completed_at)
            duration_minutes = max(0, int((completed_dt - started_dt).total_seconds() // 60))
        except ValueError:
            duration_minutes = 0

    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO study_sessions (
            subject_id,
            topic_id,
            started_at,
            completed_at,
            duration_minutes,
            session_type
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (subject_id, topic_id, started_at, completed_at, max(0, duration_minutes), session_type),
    )
    conn.commit()
    session_id = cursor.lastrowid
    conn.close()

    return rk_get_study_session(session_id)


@app.get("/api/study/sessions")
def rk_get_study_sessions(limit: int = 30):
    ensure_study_tables()

    conn = get_db()
    rows = conn.execute(
        """
        SELECT ss.id, ss.subject_id, ss.topic_id, ss.started_at, ss.completed_at,
            ss.duration_minutes, ss.session_type, s.name, t.name
        FROM study_sessions AS ss
        JOIN study_subjects AS s ON s.id = ss.subject_id
        LEFT JOIN study_topics AS t ON t.id = ss.topic_id
        ORDER BY ss.started_at DESC, ss.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "subject_id": row[1],
            "topic_id": row[2],
            "started_at": row[3],
            "completed_at": row[4],
            "duration_minutes": row[5],
            "session_type": row[6],
            "subject_name": row[7],
            "topic_name": row[8],
        }
        for row in rows
    ]


@app.get("/api/study/sessions/{session_id}")
def rk_get_study_session(session_id: int):
    ensure_study_tables()

    conn = get_db()
    row = conn.execute(
        """
        SELECT id, subject_id, topic_id, started_at, completed_at, duration_minutes, session_type
        FROM study_sessions
        WHERE id = ?
        """,
        (session_id,),
    ).fetchone()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Study session not found")

    return {
        "id": row[0],
        "subject_id": row[1],
        "topic_id": row[2],
        "started_at": row[3],
        "completed_at": row[4],
        "duration_minutes": row[5],
        "session_type": row[6],
    }


@app.get("/api/study/overview")
def rk_get_study_overview():
    ensure_study_tables()

    conn = get_db()
    subjects_total = conn.execute("SELECT COUNT(*) FROM study_subjects WHERE active = 1").fetchone()[0]
    topics_total = conn.execute("SELECT COUNT(*) FROM study_topics WHERE active = 1").fetchone()[0]
    today = date.today().isoformat()
    today_sessions = conn.execute(
        "SELECT COUNT(*) FROM study_sessions WHERE DATE(COALESCE(completed_at, started_at)) = ? AND session_type = 'study'",
        (today,),
    ).fetchone()[0]
    today_minutes = conn.execute(
        "SELECT COALESCE(SUM(duration_minutes), 0) FROM study_sessions WHERE DATE(COALESCE(completed_at, started_at)) = ? AND session_type = 'study'",
        (today,),
    ).fetchone()[0]
    topics_studied_today = conn.execute(
        """
        SELECT COUNT(DISTINCT topic_id)
        FROM study_sessions
        WHERE topic_id IS NOT NULL
          AND DATE(COALESCE(completed_at, started_at)) = ?
                    AND session_type = 'study'
        """,
        (today,),
    ).fetchone()[0]
    recent_sessions = conn.execute(
        """
        SELECT ss.id, ss.subject_id, ss.topic_id, ss.started_at, ss.completed_at,
            ss.duration_minutes, ss.session_type, s.name, t.name
        FROM study_sessions AS ss
        JOIN study_subjects AS s ON s.id = ss.subject_id
        LEFT JOIN study_topics AS t ON t.id = ss.topic_id
        WHERE ss.session_type = 'study'
        ORDER BY COALESCE(ss.completed_at, ss.started_at) DESC, ss.id DESC
        LIMIT 8
        """
    ).fetchall()

    dates = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT DATE(COALESCE(completed_at, started_at)) FROM study_sessions WHERE session_type = 'study' AND (completed_at IS NOT NULL OR started_at IS NOT NULL) ORDER BY DATE(COALESCE(completed_at, started_at)) DESC"
        ).fetchall()
    ]
    conn.close()

    current_streak = 0
    if dates:
        current_date = date.today()
        date_set = set(dates)
        while current_date.isoformat() in date_set:
            current_streak += 1
            current_date -= timedelta(days=1)

    return {
        "total_subjects": int(subjects_total or 0),
        "total_topics": int(topics_total or 0),
        "today_sessions": int(today_sessions or 0),
        "today_study_minutes": int(today_minutes or 0),
        "topics_studied_today": int(topics_studied_today or 0),
        "recent_sessions": [
            {
                "id": row[0],
                "subject_id": row[1],
                "topic_id": row[2],
                "started_at": row[3],
                "completed_at": row[4],
                "duration_minutes": row[5],
                "session_type": row[6],
                "subject_name": row[7],
                "topic_name": row[8],
            }
            for row in recent_sessions
        ],
        "current_streak": current_streak,
        "last_activity_date": dates[0] if dates else None,
    }


# ============================================================
# RK OS - PROGRESS / ANALYTICS API
# ============================================================

@app.get("/api/progress")
def rk_get_progress():

    ensure_goals_table()
    ensure_habits_table()
    ensure_quiz_tables()

    conn = get_db()

    # ----------------------------
    # TASK STATISTICS
    # ----------------------------

    task_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(
                CASE
                    WHEN completed = 1 THEN 1
                    ELSE 0
                END
            ), 0) AS completed
        FROM tasks
        """
    ).fetchone()

    total_tasks = int(task_row[0] or 0)
    completed_tasks = int(task_row[1] or 0)

    task_completion = (
        round((completed_tasks / total_tasks) * 100)
        if total_tasks > 0
        else 0
    )


    # ----------------------------
    # HABIT STATISTICS
    # ----------------------------

    today = date.today().isoformat()

    habit_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(
                CASE
                    WHEN completed = 1 AND last_completed_date = ? THEN 1
                    ELSE 0
                END
            ), 0) AS completed
        FROM habits
        """,
        (today,)
    ).fetchone()

    total_habits = int(habit_row[0] or 0)
    completed_habits = int(habit_row[1] or 0)

    habit_completion = (
        round((completed_habits / total_habits) * 100)
        if total_habits > 0
        else 0
    )


    # ----------------------------
    # GOAL STATISTICS
    # ----------------------------

    goal_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(AVG(progress), 0) AS average_progress
        FROM goals
        """
    ).fetchone()

    total_goals = int(goal_row[0] or 0)

    goal_progress = round(
        float(goal_row[1] or 0)
    )

    goal_progress = max(
        0,
        min(100, goal_progress)
    )


    # ----------------------------
    # OVERALL SCORE
    # ----------------------------

    categories = []

    if total_tasks > 0:
        categories.append(task_completion)

    if total_habits > 0:
        categories.append(habit_completion)

    if total_goals > 0:
        categories.append(goal_progress)

    overall_score = (
        round(sum(categories) / len(categories))
        if categories
        else 0
    )


    # ----------------------------
    # TOTAL ITEMS
    # ----------------------------

    total_items = (
        total_tasks +
        total_habits +
        total_goals
    )

    study_row = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(duration_minutes), 0),
            COUNT(DISTINCT topic_id)
        FROM study_sessions
        WHERE session_type = 'study'
        """
    ).fetchone()
    study_sessions = int(study_row[0] or 0)
    study_minutes = int(study_row[1] or 0)
    topics_studied = int(study_row[2] or 0)

    practice_row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(is_correct), 0) FROM practice_attempts"
    ).fetchone()
    practice_questions = int(practice_row[0] or 0)
    practice_correct = int(practice_row[1] or 0)
    weak_topics = _rk_get_weak_topics(conn)
    quiz_row = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(total_questions), 0),
            COALESCE(SUM(correct_answers), 0),
            COALESCE(MAX(100.0 * correct_answers / NULLIF(total_questions, 0)), 0)
        FROM quiz_sessions
        WHERE completed_at IS NOT NULL
        """
    ).fetchone()
    quiz_attempts = int(quiz_row[0] or 0)
    quiz_questions = int(quiz_row[1] or 0)
    quiz_correct = int(quiz_row[2] or 0)
    combined_weak_topics = _rk_get_combined_weak_topics(conn)


    conn.close()


    return {
        "overall_score": overall_score,

        "tasks": {
            "total": total_tasks,
            "completed": completed_tasks,
            "completion": task_completion
        },

        "habits": {
            "total": total_habits,
            "completed": completed_habits,
            "completion": habit_completion
        },

        "goals": {
            "total": total_goals,
            "progress": goal_progress
        },

        "study": {
            "sessions": study_sessions,
            "study_minutes": study_minutes,
            "topics_studied": topics_studied,
        },

        "practice": {
            "questions": practice_questions,
            "correct": practice_correct,
            "accuracy": round(100 * practice_correct / practice_questions) if practice_questions else 0,
            "weak_topics": len(weak_topics),
        },

        "quiz": {
            "attempts": quiz_attempts,
            "questions": quiz_questions,
            "correct": quiz_correct,
            "accuracy": round(100 * quiz_correct / quiz_questions) if quiz_questions else 0,
            "best_accuracy": round(float(quiz_row[3] or 0)),
            "weak_topics": len(combined_weak_topics),
        },

        "total_items": total_items
    }


# ============================================================
# RK OS - ACTIVITY HISTORY API
# ============================================================

@app.get("/api/activity-history")
def rk_get_activity_history(limit: int = 30):

    ensure_activity_history_table()

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            id,
            activity_date,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        FROM activity_history
        ORDER BY activity_date DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    conn.close()

    return [
        {
            "id": row[0],
            "activity_date": row[1],
            "tasks_total": row[2],
            "tasks_completed": row[3],
            "habits_total": row[4],
            "habits_completed": row[5],
            "goals_total": row[6],
            "goal_progress": row[7],
            "overall_score": row[8]
        }
        for row in rows
    ]


@app.get("/api/activity-history/today")
def rk_get_today_activity():

    ensure_activity_history_table()

    today = date.today().isoformat()

    conn = get_db()

    row = conn.execute(
        """
        SELECT
            id,
            activity_date,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        FROM activity_history
        WHERE activity_date = ?
        """,
        (today,)
    ).fetchone()

    conn.close()

    if row is None:
        return {
            "activity_date": today,
            "tasks_total": 0,
            "tasks_completed": 0,
            "habits_total": 0,
            "habits_completed": 0,
            "goals_total": 0,
            "goal_progress": 0,
            "overall_score": 0
        }

    return {
        "id": row[0],
        "activity_date": row[1],
        "tasks_total": row[2],
        "tasks_completed": row[3],
        "habits_total": row[4],
        "habits_completed": row[5],
        "goals_total": row[6],
        "goal_progress": row[7],
        "overall_score": row[8]
    }


@app.post("/api/activity-history")
def rk_save_activity_history(activity: dict):

    ensure_activity_history_table()

    activity_date = str(activity.get(
        "activity_date",
        date.today().isoformat()
    ))

    if activity_date != date.today().isoformat():
        raise HTTPException(
            status_code=409,
            detail="Only today's activity snapshot can be updated"
        )

    tasks_total = int(activity.get("tasks_total", 0) or 0)
    tasks_completed = int(activity.get("tasks_completed", 0) or 0)

    habits_total = int(activity.get("habits_total", 0) or 0)
    habits_completed = int(activity.get("habits_completed", 0) or 0)

    goals_total = int(activity.get("goals_total", 0) or 0)
    goal_progress = int(activity.get("goal_progress", 0) or 0)

    overall_score = int(activity.get("overall_score", 0) or 0)

    conn = get_db()

    conn.execute(
        """
        INSERT INTO activity_history (
            activity_date,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(activity_date)
        DO UPDATE SET
            tasks_total = excluded.tasks_total,
            tasks_completed = excluded.tasks_completed,
            habits_total = excluded.habits_total,
            habits_completed = excluded.habits_completed,
            goals_total = excluded.goals_total,
            goal_progress = excluded.goal_progress,
            overall_score = excluded.overall_score
        """,
        (
            activity_date,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        )
    )

    conn.commit()

    row = conn.execute(
        """
        SELECT
            id,
            activity_date,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        FROM activity_history
        WHERE activity_date = ?
        """,
        (activity_date,)
    ).fetchone()

    conn.close()

    return {
        "id": row[0],
        "activity_date": row[1],
        "tasks_total": row[2],
        "tasks_completed": row[3],
        "habits_total": row[4],
        "habits_completed": row[5],
        "goals_total": row[6],
        "goal_progress": row[7],
        "overall_score": row[8]
    }


# ============================================================
# RK OS - AUTOMATIC DAILY ACTIVITY SNAPSHOT
# ============================================================

@app.post("/api/activity-history/snapshot")
def rk_create_daily_snapshot():

    ensure_activity_history_table()
    ensure_habits_table()
    ensure_habit_history_table()
    ensure_goals_table()

    today = date.today().isoformat()
    conn = get_db()

    conn.execute(
        """
        INSERT INTO habit_history (
            habit_id, activity_date, completed
        )
        SELECT
            id,
            ?,
            CASE
                WHEN completed = 1 AND last_completed_date = ? THEN 1
                ELSE 0
            END
        FROM habits
            WHERE 1 = 1
            ON CONFLICT(habit_id, activity_date)
            DO UPDATE SET completed = excluded.completed
        """,
        (today, today)
    )

    # --------------------------------------------------------
    # TASK STATISTICS
    # --------------------------------------------------------

    task_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(
                SUM(
                    CASE
                        WHEN completed = 1 THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS completed
        FROM tasks
        """
    ).fetchone()

    tasks_total = int(task_row[0] or 0)
    tasks_completed = int(task_row[1] or 0)

    # --------------------------------------------------------
    # HABIT STATISTICS
    # --------------------------------------------------------

    habit_row = conn.execute(
        """
        SELECT
            COUNT(h.id) AS total,
            COALESCE(SUM(COALESCE(hh.completed, 0)), 0) AS completed
        FROM habits AS h
        LEFT JOIN habit_history AS hh
            ON hh.habit_id = h.id
            AND hh.activity_date = ?
        """
    , (today,)).fetchone()

    habits_total = int(habit_row[0] or 0)
    habits_completed = int(habit_row[1] or 0)

    # --------------------------------------------------------
    # GOAL STATISTICS
    # --------------------------------------------------------

    goal_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(AVG(progress), 0) AS average_progress
        FROM goals
        """
    ).fetchone()

    goals_total = int(goal_row[0] or 0)
    goal_progress = round(float(goal_row[1] or 0))

    # --------------------------------------------------------
    # OVERALL SCORE
    # --------------------------------------------------------

    task_score = 0

    if tasks_total > 0:
        task_score = (
            tasks_completed / tasks_total
        ) * 100

    habit_score = 0

    if habits_total > 0:
        habit_score = (
            habits_completed / habits_total
        ) * 100

    goal_score = goal_progress

    score_parts = []

    if tasks_total > 0:
        score_parts.append(task_score)

    if habits_total > 0:
        score_parts.append(habit_score)

    if goals_total > 0:
        score_parts.append(goal_score)

    if score_parts:
        overall_score = round(
            sum(score_parts) / len(score_parts)
        )
    else:
        overall_score = 0

    # --------------------------------------------------------
    # SAVE TODAY'S SNAPSHOT
    # --------------------------------------------------------

    conn.execute(
        """
        INSERT INTO activity_history (
            activity_date,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(activity_date)
        DO UPDATE SET
            tasks_total = excluded.tasks_total,
            tasks_completed = excluded.tasks_completed,
            habits_total = excluded.habits_total,
            habits_completed = excluded.habits_completed,
            goals_total = excluded.goals_total,
            goal_progress = excluded.goal_progress,
            overall_score = excluded.overall_score
        """,
        (
            today,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        )
    )

    conn.commit()

    # --------------------------------------------------------
    # RETURN SNAPSHOT
    # --------------------------------------------------------

    row = conn.execute(
        """
        SELECT
            id,
            activity_date,
            tasks_total,
            tasks_completed,
            habits_total,
            habits_completed,
            goals_total,
            goal_progress,
            overall_score
        FROM activity_history
        WHERE activity_date = ?
        """,
        (today,)
    ).fetchone()

    conn.close()

    return {
        "id": row[0],
        "activity_date": row[1],
        "tasks_total": row[2],
        "tasks_completed": row[3],
        "habits_total": row[4],
        "habits_completed": row[5],
        "goals_total": row[6],
        "goal_progress": row[7],
        "overall_score": row[8]
    }


def ensure_profile_tables():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL DEFAULT 'RK User',
            bio TEXT NOT NULL DEFAULT '',
            study_target INTEGER NOT NULL DEFAULT 120,
            exam_target TEXT NOT NULL DEFAULT 'SSC CGL',
            preferences TEXT NOT NULL DEFAULT '',
            assistant_preferences TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS assistant_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            action TEXT,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


@app.get("/api/profile")
def rk_get_profile():
    ensure_profile_tables()
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO user_profile (id, updated_at) VALUES (1, ?)",
        (datetime.now().isoformat(timespec="seconds"),),
    )
    conn.commit()
    row = conn.execute(
        "SELECT name, bio, study_target, exam_target, preferences, assistant_preferences, updated_at FROM user_profile WHERE id = 1"
    ).fetchone()
    conn.close()
    return {
        "name": row[0],
        "bio": row[1],
        "study_target": int(row[2] or 120),
        "exam_target": row[3],
        "preferences": row[4],
        "assistant_preferences": row[5],
        "updated_at": row[6],
    }


@app.put("/api/profile")
def rk_update_profile(profile: dict):
    ensure_profile_tables()
    name = str(profile.get("name") or "RK User").strip()[:80]
    if not name:
        raise HTTPException(status_code=422, detail="Profile name is required")
    try:
        study_target = max(1, min(1440, int(profile.get("study_target") or 120)))
    except (TypeError, ValueError):
        study_target = 120
    values = (
        name,
        str(profile.get("bio") or "").strip()[:240],
        study_target,
        str(profile.get("exam_target") or "SSC CGL").strip()[:120],
        str(profile.get("preferences") or "").strip()[:500],
        str(profile.get("assistant_preferences") or "").strip()[:500],
        datetime.now().isoformat(timespec="seconds"),
    )
    conn = get_db()
    conn.execute(
        """
        INSERT INTO user_profile (
            id, name, bio, study_target, exam_target, preferences, assistant_preferences, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            bio = excluded.bio,
            study_target = excluded.study_target,
            exam_target = excluded.exam_target,
            preferences = excluded.preferences,
            assistant_preferences = excluded.assistant_preferences,
            updated_at = excluded.updated_at
        """,
        values,
    )
    conn.commit()
    conn.close()
    return rk_get_profile()


@app.get("/api/routines/summary")
def rk_get_routines_summary():
    ensure_habits_table()
    ensure_habit_history_table()
    ensure_goals_table()
    ensure_activity_history_table()
    today = date.today().isoformat()
    conn = get_db()
    task_counts = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END), 0) FROM tasks"
    ).fetchone()
    pending_tasks = conn.execute(
        "SELECT title FROM tasks WHERE completed = 0 ORDER BY id DESC LIMIT 4"
    ).fetchall()
    habit_counts = conn.execute(
        """
        SELECT COUNT(h.id), COALESCE(SUM(CASE WHEN h.completed = 1 AND h.last_completed_date = ? THEN 1 ELSE 0 END), 0)
        FROM habits AS h
        """,
        (today,),
    ).fetchone()
    pending_habits = conn.execute(
        "SELECT name FROM habits WHERE completed != 1 OR last_completed_date IS NULL OR last_completed_date != ? ORDER BY id DESC LIMIT 4",
        (today,),
    ).fetchall()
    goal_counts = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN progress >= 100 THEN 1 ELSE 0 END), 0) FROM goals"
    ).fetchone()
    active_goals = conn.execute(
        "SELECT title, progress FROM goals WHERE progress < 100 ORDER BY progress, id DESC LIMIT 4"
    ).fetchall()
    history_dates = [row[0] for row in conn.execute(
        """
        SELECT activity_date FROM activity_history
        WHERE tasks_completed > 0 OR habits_completed > 0 OR goal_progress > 0
        ORDER BY activity_date DESC LIMIT 30
        """
    ).fetchall()]
    conn.close()
    current_streak = 0
    today_date = date.today()
    date_set = set(history_dates)
    if today_date.isoformat() not in date_set:
        today_date -= timedelta(days=1)
    while today_date.isoformat() in date_set:
        current_streak += 1
        today_date -= timedelta(days=1)
    return {
        "tasks": {"total": int(task_counts[0] or 0), "completed": int(task_counts[1] or 0)},
        "habits": {"total": int(habit_counts[0] or 0), "completed_today": int(habit_counts[1] or 0)},
        "goals": {"total": int(goal_counts[0] or 0), "completed": int(goal_counts[1] or 0)},
        "pending_tasks": [row[0] for row in pending_tasks],
        "pending_habits": [row[0] for row in pending_habits],
        "active_goals": [{"title": row[0], "progress": int(row[1] or 0)} for row in active_goals],
        "current_streak": current_streak,
        "weekly_consistency": round(100 * len([item for item in history_dates if item >= (date.today() - timedelta(days=6)).isoformat()]) / 7),
    }


@app.get("/api/assistant/history")
def rk_get_assistant_history(limit: int = 30):
    ensure_profile_tables()
    safe_limit = max(1, min(int(limit), 100))
    conn = get_db()
    rows = conn.execute(
        "SELECT id, role, content, action, created_at FROM assistant_history ORDER BY id DESC LIMIT ?",
        (safe_limit,),
    ).fetchall()
    conn.close()
    return [
        {"id": row[0], "role": row[1], "content": row[2], "action": row[3], "created_at": row[4]}
        for row in reversed(rows)
    ]


@app.get("/api/automation/capabilities")
def rk_get_automation_capabilities():
    return {
        "connected": False,
        "integrations": [],
        "message": "No external mobile or service integrations are connected.",
    }


def rk_assistant_dispatch(command: str):
    normalized = command.casefold().strip()
    clean_command = command.strip().rstrip(".?! ")

    create_match = re.search(r"(?:add|create)\s+(?:a\s+)?task\s+(?:to\s+|called\s+|named\s+)?(.+)", clean_command, re.IGNORECASE)
    if create_match:
        title = create_match.group(1).strip()
        created = create_task({"title": title})
        return "create_task", f"Added task: {created['title']}.", created

    habit_match = re.search(r"(?:create|add)\s+(?:a\s+)?habit\s+(?:called\s+|named\s+)?(.+)", clean_command, re.IGNORECASE)
    if habit_match:
        created = rk_create_habit({"name": habit_match.group(1).strip()})
        return "create_habit", f"Created habit: {created['name']}.", created

    goal_match = re.search(r"(?:create|add)\s+(?:a\s+)?goal\s+(?:to\s+|called\s+|named\s+)?(.+)", clean_command, re.IGNORECASE)
    if goal_match:
        created = rk_create_goal({"title": goal_match.group(1).strip()})
        return "create_goal", f"Created goal: {created['title']}.", created

    delete_task_match = re.search(r"delete\s+task\s+(.+)", clean_command, re.IGNORECASE)
    if delete_task_match:
        task_name = delete_task_match.group(1).strip()
        conn = get_db()
        task = conn.execute("SELECT id, title FROM tasks WHERE title LIKE ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (f"%{task_name}%",)).fetchone()
        conn.close()
        if task is None:
            return "delete_task", f"I couldn't find a task matching '{task_name}'.", None
        delete_task(int(task[0]))
        return "delete_task", f"Deleted task: {task[1]}.", {"id": int(task[0]), "title": task[1]}

    delete_habit_match = re.search(r"delete\s+habit\s+(.+)", clean_command, re.IGNORECASE)
    if delete_habit_match:
        habit_name = delete_habit_match.group(1).strip()
        conn = get_db()
        habit = conn.execute("SELECT id, name FROM habits WHERE name LIKE ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (f"%{habit_name}%",)).fetchone()
        conn.close()
        if habit is None:
            return "delete_habit", f"I couldn't find a habit matching '{habit_name}'.", None
        rk_delete_habit(int(habit[0]))
        return "delete_habit", f"Deleted habit: {habit[1]}.", {"id": int(habit[0]), "name": habit[1]}

    update_goal_match = re.search(r"update\s+goal\s+(.+?)\s+to\s+(\d{1,3})\s*%", clean_command, re.IGNORECASE)
    if update_goal_match:
        goal_name = update_goal_match.group(1).strip()
        progress = max(0, min(100, int(update_goal_match.group(2))))
        conn = get_db()
        goal = conn.execute("SELECT id, title FROM goals WHERE title LIKE ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (f"%{goal_name}%",)).fetchone()
        conn.close()
        if goal is None:
            return "update_goal", f"I couldn't find a goal matching '{goal_name}'.", None
        updated = rk_update_goal(int(goal[0]), {"progress": progress})
        return "update_goal", f"Updated {goal[1]} to {progress}%.", updated

    complete_habit_match = re.search(
        r"(?:complete|finish)\s+(?:(?:my|the|a)\s+)?habit(?:\s+(?:called|named))?\s+(.+)|mark\s+habit\s+(.+?)\s+complete",
        clean_command,
        re.IGNORECASE,
    )
    if complete_habit_match:
        habit_name = next(group for group in complete_habit_match.groups() if group).strip()
        conn = get_db()
        habit = conn.execute("SELECT id, name FROM habits WHERE name LIKE ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (f"%{habit_name}%",)).fetchone()
        conn.close()
        if habit is None:
            return "complete_habit", f"I couldn't find a habit matching '{habit_name}'.", None
        updated = rk_update_habit(int(habit[0]), {"completed": True})
        return "complete_habit", f"Marked habit complete: {habit[1]}.", updated

    complete_task_match = re.search(
        r"(?:complete|finish)\s+(?:(?:my|the|a)\s+)?task\s+(.+)|mark\s+task\s+(.+?)\s+complete",
        clean_command,
        re.IGNORECASE,
    )
    if complete_task_match:
        task_name = next(group for group in complete_task_match.groups() if group).strip()
        conn = get_db()
        task = conn.execute("SELECT id, title FROM tasks WHERE title LIKE ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (f"%{task_name}%",)).fetchone()
        conn.close()
        if task is None:
            return "complete_task", f"I couldn't find a task matching '{task_name}'.", None
        updated = update_task(int(task[0]), {"completed": True})
        return "complete_task", f"Completed task: {task[1]}.", updated

    if "start" in normalized and ("focus" in normalized or "timer" in normalized):
        duration_match = re.search(r"(\d+)\s*(?:minute|min)s?", normalized)
        duration = max(1, min(240, int(duration_match.group(1)))) if duration_match else 25
        return "start_focus_timer", f"Starting a {duration}-minute focus session for your selected study topic.", {"minutes": duration}

    if "open" in normalized and "revision" in normalized:
        return "open_revision", "Opening your revision list.", None
    if ("open" in normalized or "start" in normalized) and "quiz" in normalized:
        return "start_quiz", "Opening Quiz Studio.", None
    if ("open" in normalized or "start" in normalized) and "practice" in normalized:
        return "start_practice", "Opening Practice for your selected topic.", None
    if "open" in normalized and ("learn" in normalized or "study plan" in normalized):
        return "open_learn", "Opening your SSC study plan.", None

    if "weak area" in normalized or "weak topic" in normalized:
        ensure_quiz_tables()
        conn = get_db()
        weak_topics = _rk_get_combined_weak_topics(conn, limit=8)
        conn.close()
        if not weak_topics:
            return "show_weak_topics", "No weak study topics are recorded yet.", []
        summary = "; ".join(f"{item['topic_name']} ({item['accuracy']}%)" for item in weak_topics)
        return "show_weak_topics", f"Your current weak areas are: {summary}.", weak_topics

    if "routine" in normalized or "today" in normalized and ("show" in normalized or "what" in normalized):
        routines = rk_get_routines_summary()
        response = (
            f"Today: {routines['habits']['completed_today']} of {routines['habits']['total']} habits completed, "
            f"{routines['tasks']['completed']} of {routines['tasks']['total']} tasks completed, "
            f"and {routines['goals']['total']} goals tracked."
        )
        return "show_today", response, routines

    if "streak" in normalized:
        routines = rk_get_routines_summary()
        return "show_streak", f"Your current activity streak is {routines['current_streak']} day(s).", {"current_streak": routines["current_streak"]}

    if "perform" in normalized or "progress" in normalized or "this week" in normalized:
        progress = rk_get_progress()
        return "show_progress", f"Your current RK OS score is {progress['overall_score']}%. Practice accuracy is {progress['practice']['accuracy']}%, quiz accuracy is {progress['quiz']['accuracy']}%.", progress

    if "study" in normalized and ("what should" in normalized or "recommend" in normalized or "plan" in normalized):
        subjects = rk_get_study_subjects()
        topics = rk_get_study_topics()
        if not topics:
            return "show_study_plan", "No active study topics are available yet.", []
        topic = topics[0]
        subject = next((item for item in subjects if item["id"] == topic["subject_id"]), None)
        return "show_study_plan", f"A study topic available today is {topic['name']} in {(subject or {}).get('name', 'your study plan')}.", {"subject": subject, "topic": topic}

    return None, "That capability isn't connected yet.", None


@app.post("/api/assistant/command")
def rk_assistant_command(payload: dict):
    ensure_profile_tables()
    command = str(payload.get("command") or "").strip()
    if not command:
        raise HTTPException(status_code=422, detail="Enter a message for RK Assistant")
    action, response, data = rk_assistant_dispatch(command)
    created_at = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    conn.executemany(
        "INSERT INTO assistant_history (role, content, action, created_at) VALUES (?, ?, ?, ?)",
        [("user", command, None, created_at), ("assistant", response, action, created_at)],
    )
    conn.commit()
    conn.close()
    return {"response": response, "action": action, "data": data, "created_at": created_at}


# =========================
# FRONTEND
# =========================

ensure_quiz_tables()
ensure_profile_tables()

app.mount(
    "/",
    StaticFiles(
        directory=BASE_DIR / "static",
        html=True
    ),
    name="static"
)