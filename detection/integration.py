"""
Integration helper for detection.py
Sends each concluded handwashing session to the dashboard.
"""

import requests

DASHBOARD_URL = "http://localhost:5002"

def send_to_dashboard(result, steps_completed, rub_duration, camera_id,
                      behaviour_type="handwashing", confidence=None, evidence_url=None):
    """
    Call this at the end of conclude_session() in detection.py:
        send_to_dashboard(result_display, steps_completed, rub_duration, camera_id, evidence_url)
    """
    try:
        payload = {
            "result": result,                 # 'PASS' / 'WARNING' / 'FAIL'
            "steps": steps_completed,          # e.g. ['soap','rub','rinse','dry']
            "rub_duration": rub_duration,
            "camera_id": str(camera_id),
            "behaviour_type": behaviour_type,
            "confidence": confidence,          # optional 0..1
            "evidence_url": evidence_url,      # optional video path, e.g. /static/evidence/incident_xxx.mp4
        }
        r = requests.post(f"{DASHBOARD_URL}/api/incidents", json=payload, timeout=5)
        if r.status_code == 201:
            d = r.json()
            print(f"  -> dashboard: {result} stored as {d['compliance_status']} "
                  f"(risk={d['risk_level']}, id={d['incident_id']})")
        else:
            print(f"  -> dashboard error {r.status_code}: {r.text[:120]}")
    except requests.exceptions.ConnectionError:
        print(f"  -> dashboard not reachable at {DASHBOARD_URL} (is dashboard_app.py running?)")
    except Exception as e:
        print(f"  -> dashboard send failed: {e}")
