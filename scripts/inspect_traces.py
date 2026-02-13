from smith.storage.mongodb import DBTools
import json
from datetime import datetime


class DateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def inspect_latest_trace():
    db = DBTools()
    res = db.read_many("traces", {})
    if res["status"] != "success":
        print(f"Error reading DB: {res.get('error')}")
        return

    traces = res.get("data", [])
    if not traces:
        print("No traces found.")
        return

    traces.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    latest = traces[0]

    with open("trace_dump.json", "w", encoding="utf-8") as f:
        json.dump(latest, f, indent=2, cls=DateTimeEncoder)

    print(f"Trace {latest.get('trace_id')} dumped to trace_dump.json")


if __name__ == "__main__":
    inspect_latest_trace()
