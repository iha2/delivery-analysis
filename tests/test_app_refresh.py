import threading

from delivery_analysis.app.refresh import RefreshWorker


def test_one_refresh_at_a_time_and_its_state():
    gate = threading.Event()
    calls = []

    def run(source, full):
        calls.append((source, full))
        gate.wait(5)
        return "1 ok, 0 failed"

    worker = RefreshWorker(run)
    assert worker.start("bitbucket", True) is True
    assert worker.start() is False  # a second request while running
    state = worker.state()
    assert (state["running"], state["source"], state["full"]) == (True, "bitbucket", True)
    gate.set()
    worker.wait()
    done = worker.state()
    assert (done["running"], done["summary"], done["error"]) == (False, "1 ok, 0 failed", None)
    assert done["finished_at"].endswith("Z") and calls == [("bitbucket", True)]
    assert worker.start() is True
    worker.wait()


def test_a_failing_refresh_records_the_error_and_frees_the_worker():
    def run(source, full):
        raise RuntimeError("source down")

    worker = RefreshWorker(run)
    worker.start()
    worker.wait()
    assert worker.state()["error"] == "source down" and worker.state()["running"] is False


def test_worker_redacts_stored_error_and_summary():
    worker = RefreshWorker(lambda source, full: "done SECRET", redact=lambda text: text.replace("SECRET", "***"))
    worker.start()
    worker.wait()
    assert worker.state()["summary"] == "done ***"

    def boom(source, full):
        raise RuntimeError("bad SECRET")

    failing = RefreshWorker(boom, redact=lambda text: text.replace("SECRET", "***"))
    failing.start()
    failing.wait()
    assert failing.state()["error"] == "bad ***"
