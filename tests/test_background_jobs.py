import threading
import time

from agentic_data_platform.jobs import BackgroundJobEngine


def wait_terminal(engine, job_id):
    for _ in range(200):
        current = engine.get(job_id)
        if current["status"] in {"SUCCESS", "FAILED", "CANCELLED"}:
            return current
        time.sleep(0.005)
    raise AssertionError("job did not reach terminal state")


def test_background_job_success_and_failure(tmp_path):
    engine = BackgroundJobEngine(tmp_path / "jobs.db", max_workers=1)
    success = engine.submit("sum", lambda: {"value": 4})
    assert wait_terminal(engine, success)["result"] == {"value": 4}

    def fail():
        raise ValueError("boom")

    failed = engine.submit("fail", fail)
    state = wait_terminal(engine, failed)
    assert state["status"] == "FAILED"
    assert "ValueError: boom" in state["error"]
    assert len(engine.list()) == 2
    engine.shutdown()


def test_background_job_cancel_when_still_queued(tmp_path):
    engine = BackgroundJobEngine(tmp_path / "jobs.db", max_workers=1)
    gate = threading.Event()
    first = engine.submit("block", lambda: gate.wait(1))
    second = engine.submit("queued", lambda: 2)
    assert engine.cancel(second) is True
    assert engine.get(second)["status"] == "CANCELLED"
    gate.set()
    wait_terminal(engine, first)
    engine.shutdown()
