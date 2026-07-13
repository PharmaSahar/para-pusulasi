import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import scheduler
import src.channel_manager as cm
import src.pipeline as pipeline
import src.scheduler_utils as su


def run_probe() -> None:
    with tempfile.TemporaryDirectory(prefix="probe_attrs_") as td:
        root = Path(td)
        qf = root / "channel_queue.json"
        qf.write_text("{}", encoding="utf-8")

        scheduler.QUEUE_FILE = str(qf)
        su.QUARANTINE_TRAIL_PATH = root / "queue_quarantine_decisions.jsonl"
        su.PROVIDER_HEALTH_FILE = str(root / "provider_health.json")
        su.check_disk_space = lambda **_k: True
        su.get_provider_circuit_status = lambda _provider: {
            "provider": "anthropic",
            "is_open": False,
            "retry_after_seconds": 0,
            "state": {},
        }
        su.notify_error = lambda *_a, **_k: {}
        su.force_cleanup = lambda: None
        cm.get_channel = lambda _cid: SimpleNamespace(name="Demo Channel", upload_times=["10:00"], niche="saglik")

        calls = {"pipeline": 0}

        def raise_with_attrs(**_kwargs):
            calls["pipeline"] += 1
            err = RuntimeError("topic_domain_blocked:no_valid_candidate niche=saglik")
            setattr(err, "_skip_scheduler_pipeline_retry", True)
            setattr(err, "_quarantine_reason", "topic_domain_blocked")
            setattr(err, "_guard_reason_codes", ["topic_domain_blocked"])
            setattr(err, "_run_id", "run_probe")
            setattr(err, "_content_id", "content_probe")
            setattr(err, "_topic", "Probe Topic")
            setattr(err, "_detected_domain", "finance")
            raise err

        pipeline.run_full_pipeline = raise_with_attrs
        scheduler.render_and_schedule("demo_channel")
        queue_data = json.loads(qf.read_text(encoding="utf-8"))
        print(json.dumps({"calls": calls["pipeline"], "queue": queue_data}, ensure_ascii=False))


if __name__ == "__main__":
    run_probe()
