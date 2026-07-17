"""
Test-data helper for the retention feature — NOT part of the real system.

Creates a handful of incidents at different ages (some old, some recent),
each with a real (tiny, dummy) video file on disk, so you can test the
video/incident retention sliders and the "Purge now" button without needing
the camera or the water sensor connected.

Run this from INSIDE the dashboard/ folder, with the dashboard stopped
(Ctrl+C it first) so nothing else is writing to compliance.db at the same
time:

    cd dashboard
    python simulate_test_incidents.py

Then start the dashboard as normal and check Review Incidents / Rules &
Alerts -> Data Retention.

Safe to run multiple times — it just adds more test rows each time.
Safe to delete afterwards; it doesn't touch anything except compliance.db
and dashboard/static/evidence/.
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta

DB_PATH = "compliance.db"
EVIDENCE_DIR = os.path.join("static", "evidence")

if not os.path.exists(DB_PATH):
    print(f"ERROR: {DB_PATH} not found. Run this script from inside the dashboard/ folder,")
    print("and make sure you've started dashboard_app.py at least once already so the")
    print("database and demo accounts/sites exist.")
    raise SystemExit(1)

os.makedirs(EVIDENCE_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Use whatever site/camera already exist (from normal seeding) rather than
# assuming specific IDs.
site = c.execute("SELECT id, name FROM sites ORDER BY id LIMIT 1").fetchone()
if not site:
    print("ERROR: no sites found — start dashboard_app.py at least once first so it seeds demo data.")
    raise SystemExit(1)
site_id = site["id"]

camera = c.execute("SELECT id, camera_id FROM cameras WHERE site_id=? LIMIT 1", (site_id,)).fetchone()
camera_pk = camera["id"] if camera else None

print(f"Using site: {site['name']} (id={site_id}), camera pk={camera_pk}")

# (days_ago, compliance_status, risk_level, has_video, label)
TEST_CASES = [
    (0,   "non_compliant", "high",   True,  "today - non-compliant (should NOT purge yet)"),
    (3,   "compliant",     "low",    True,  "3 days old - compliant, QC-sampled video"),
    (10,  "non_compliant", "high",   True,  "10 days old - non-compliant with video"),
    (45,  "non_compliant", "high",   True,  "45 days old - non-compliant with video"),
    (100, "non_compliant", "high",   True,  "100 days old - past default 90-day incident retention"),
    (200, "compliant",     "low",    True,  "200 days old - well past retention, should fully purge"),
]

created = 0
for days_ago, status, risk, has_video, label in TEST_CASES:
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    evidence_url = None

    if has_video:
        fname = f"test_incident_{days_ago}d_{status}.mp4"
        fpath = os.path.join(EVIDENCE_DIR, fname)
        with open(fpath, "wb") as f:
            f.write(b"FAKE TEST VIDEO DATA - not a real video, just for testing retention/purge")
        evidence_url = f"/static/evidence/{fname}"

    details = json.dumps({
        "result": "FAIL" if status == "non_compliant" else "PASS",
        "steps": ["soap", "rub"] if status == "non_compliant" else ["soap", "rub", "rinse", "dry"],
        "rub_duration": 8.0 if status == "non_compliant" else 22.0,
    })

    c.execute(
        """INSERT INTO incidents
           (site_id, camera_id, behaviour_type, compliance_status, risk_level,
            confidence, timestamp, details, evidence_url, alerted)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (site_id, camera_pk, "handwashing", status, risk, None, ts, details, evidence_url, 0)
    )
    created += 1
    print(f"  created: {label}  (timestamp={ts[:10]}, evidence_url={evidence_url})")

conn.commit()
conn.close()

print(f"\nDone — {created} test incidents created.")
print("Start the dashboard, log in as quality/admin, and check Review Incidents,")
print("then try the retention sliders and 'Purge now' under Rules & Alerts as admin.")
