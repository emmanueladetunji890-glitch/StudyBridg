"""
StudyBridge — Academic Progress & Timetable Web App
Student: Emmanuel Adetunji | Exam Prep: WAEC / NECO
Stack: Python, Flask, SQLite
"""

import sqlite3
import os
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify

# template_folder="." allows index.html to sit in the same folder
app = Flask(__name__, template_folder=".")
app.secret_key = "studybridge-secret-adetunji"
DB_NAME = "studybridge.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    # Create the 5 required SQLite tables from the project brief
    c.executescript("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        exam_date TEXT
    );

    CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS daily_availability (
        day_of_week INTEGER PRIMARY KEY,
        day_name TEXT NOT NULL,
        available_hours REAL NOT NULL CHECK(available_hours >= 0 AND available_hours <= 24)
    );

    CREATE TABLE IF NOT EXISTS practice_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL,
        score REAL NOT NULL CHECK(score >= 0 AND score <= 100),
        test_date TEXT NOT NULL,
        notes TEXT,
        FOREIGN KEY (topic_id) REFERENCES topics (id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS study_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL,
        session_date TEXT NOT NULL,
        day_name TEXT NOT NULL,
        allocated_minutes INTEGER NOT NULL,
        completed INTEGER DEFAULT 0 CHECK(completed IN (0, 1)),
        FOREIGN KEY (topic_id) REFERENCES topics (id) ON DELETE CASCADE
    );
    """)

    # Default weekly study limits (Mon - Sun)
    c.execute("SELECT COUNT(*) FROM daily_availability")
    if c.fetchone()[0] == 0:
        days = [
            (0, "Monday", 2.0), (1, "Tuesday", 2.0), (2, "Wednesday", 2.0),
            (3, "Thursday", 2.0), (4, "Friday", 2.0), (5, "Saturday", 4.0),
            (6, "Sunday", 3.0)
        ]
        c.executemany("INSERT INTO daily_availability VALUES (?, ?, ?)", days)

    # Preload the Page 1 demonstration data if empty
    c.execute("SELECT COUNT(*) FROM subjects")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO subjects (name, exam_date) VALUES (?, ?)", [
            ("Mathematics", "2026-05-15"),
            ("Chemistry", "2026-05-18"),
            ("English Language", "2026-05-12"),
            ("Physics", "2026-05-22")
        ])
        c.executemany("INSERT INTO topics (subject_id, name) VALUES (?, ?)", [
            (1, "Quadratic Equations"),
            (1, "Trigonometry"),
            (2, "Periodic Table & Trends"),
            (2, "Organic Chemistry Basics"),
            (3, "Comprehension & Summary"),
            (4, "Newton's Laws of Motion")
        ])
        # Page 1 scores: Math low (42%), Chemistry high (88%), English (70%)
        c.executemany("INSERT INTO practice_results (topic_id, score, test_date, notes) VALUES (?, ?, ?, ?)", [
            (1, 42.0, "2026-11-01", "Struggled with factoring formula"),
            (3, 88.0, "2026-11-01", "Strong grasp of periodic trends"),
            (5, 70.0, "2026-11-02", "Good comprehension; practice timing")
        ])

    conn.commit()
    conn.close()


# Recommendation Rules (Page 2 Requirement)
def compute_recommendations(conn):
    sql = """
        SELECT t.id AS topic_id, t.name AS topic_name, s.name AS subject_name,
               pr.score AS latest_score
        FROM topics t
        JOIN subjects s ON t.subject_id = s.id
        LEFT JOIN practice_results pr ON pr.id = (
            SELECT pr2.id FROM practice_results pr2
            WHERE pr2.topic_id = t.id
            ORDER BY pr2.test_date DESC, pr2.id DESC LIMIT 1
        )
        ORDER BY s.name, t.name
    """
    rows = conn.execute(sql).fetchall()
    recs = []
    for r in rows:
        sc = r["latest_score"]
        if sc is None:
            cat, prio, badge, reason = "Needs Baseline Test", 2.5, "badge-warning", "No test recorded yet. Needs diagnostic assessment."
        elif sc < 60.0:
            cat, prio, badge, reason = "Immediate Revision", 3.5, "badge-danger", f"Score of {sc:.1f}% is below 60%. Critical revision required."
        elif sc < 80.0:
            cat, prio, badge, reason = "Targeted Practice", 2.0, "badge-info", f"Score of {sc:.1f}% indicates fair grasp; targeted drill recommended."
        else:
            cat, prio, badge, reason = "Maintenance Practice", 1.0, "badge-success", f"Strong performance ({sc:.1f}%). Maintenance review to preserve mastery."

        recs.append({
            "topic_id": r["topic_id"], "topic_name": r["topic_name"],
            "subject_name": r["subject_name"], "latest_score": sc,
            "category": cat, "priority": prio, "badge": badge, "reason": reason
        })
    recs.sort(key=lambda x: x["priority"], reverse=True)
    return recs


# Routes
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/data", methods=["GET"])
def get_data():
    conn = get_db()
    recs = compute_recommendations(conn)

    # Subjects with topics
    subs = []
    for s in conn.execute("SELECT * FROM subjects ORDER BY name").fetchall():
        t_rows = conn.execute("SELECT id, name FROM topics WHERE subject_id = ?", (s["id"],)).fetchall()
        subs.append({
            "id": s["id"], "name": s["name"], "exam_date": s["exam_date"],
            "topics": [{"id": t["id"], "name": t["name"]} for t in t_rows]
        })

    # Scores
    scores = [dict(r) for r in conn.execute("""
        SELECT pr.id, pr.score, pr.test_date, pr.notes, t.name AS topic_name, s.name AS subject_name
        FROM practice_results pr
        JOIN topics t ON pr.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        ORDER BY pr.test_date DESC, pr.id DESC
    """).fetchall()]

    # Sessions
    sessions = [dict(r) for r in conn.execute("""
        SELECT ss.id, ss.day_name, ss.allocated_minutes, ss.completed,
               t.name AS topic_name, s.name AS subject_name
        FROM study_sessions ss
        JOIN topics t ON ss.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        ORDER BY ss.id ASC
    """).fetchall()]

    completed_mins = conn.execute("SELECT SUM(allocated_minutes) FROM study_sessions WHERE completed = 1").fetchone()[0] or 0

    metrics = {
        "total_subjects": len(subs),
        "total_topics": conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
        "total_sessions": len(sessions),
        "completed_sessions": sum(1 for s in sessions if s["completed"] == 1),
        "completed_hours": round(completed_mins / 60.0, 1)
    }
    conn.close()

    return jsonify({
        "subjects": subs, "scores": scores, "sessions": sessions,
        "recommendations": recs, "metrics": metrics
    })


@app.route("/api/score", methods=["POST"])
def add_score():
    data = request.json or {}
    try:
        val = float(data.get("score"))
        if val < 0 or val > 100:
            return jsonify({"success": False, "error": "Score must be between 0 and 100."}), 400

        conn = get_db()
        conn.execute(
            "INSERT INTO practice_results (topic_id, score, test_date, notes) VALUES (?, ?, ?, ?)",
            (data.get("topic_id"), val, data.get("test_date") or date.today().isoformat(), data.get("notes", ""))
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid score value."}), 400


@app.route("/api/timetable/generate", methods=["POST"])
def generate_timetable():
    conn = get_db()
    recs = compute_recommendations(conn)
    if not recs:
        conn.close()
        return jsonify({"success": False, "error": "No topics found."}), 400

    conn.execute("DELETE FROM study_sessions")
    days = conn.execute("SELECT * FROM daily_availability ORDER BY day_of_week").fetchall()
    t_idx = 0

    for d in days:
        rem_mins = int(d["available_hours"] * 60)
        while rem_mins >= 30 and recs:
            topic = recs[t_idx % len(recs)]
            # Priority >= 3.0 (Immediate Revision) receives 60 min blocks; others get 45 min
            chunk = 60 if topic["priority"] >= 3.0 else 45
            if rem_mins < chunk:
                chunk = rem_mins

            conn.execute("""
                INSERT INTO study_sessions (topic_id, session_date, day_name, allocated_minutes, completed)
                VALUES (?, ?, ?, ?, 0)
            """, (topic["topic_id"], date.today().isoformat(), d["day_name"], chunk))

            rem_mins -= chunk
            t_idx += 1

    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/timetable/toggle", methods=["POST"])
def toggle_session():
    sid = (request.json or {}).get("session_id")
    conn = get_db()
    row = conn.execute("SELECT completed FROM study_sessions WHERE id = ?", (sid,)).fetchone()
    if row:
        new_status = 0 if row["completed"] == 1 else 1
        conn.execute("UPDATE study_sessions SET completed = ? WHERE id = ?", (new_status, sid))
        conn.commit()
    conn.close()
    return jsonify({"success": True})


if __name__ == "__main__":
    init_db()
    print("=" * 60)
    print(" StudyBridge running at: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, port=5000)