"""Running the ETL from the console.

The web team update the site on Saturdays. Getting that into the bot meant
waiting for Monday's cron to produce a diff, signing it, and then finding
somebody who could `sudo git pull && sudo bash build.sh` on the box.

These tests are about the ways a button like that goes wrong: two runs at
once on a 3.8 GB machine, an uncapped reindex paging the bot out of RAM, a
failure that only shows up on the server, and a green page over a corpus
nobody rebuilt.
"""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from src.api.admin import etl_jobs


@pytest.fixture(autouse=True)
def _clean():
    etl_jobs.reset_for_tests()
    yield
    etl_jobs.reset_for_tests()


class TestTheCommands:
    def test_apply_is_memory_capped(self):
        """Uncapped, the reindex pushes the serving process into swap and
        patrons get NO answer within 30 seconds -- measured, and the
        process still reports active while it happens. Slower answers are
        a cost; a bot that stops answering is not one we get to choose."""
        cmd = " ".join(etl_jobs._cmd("apply"))
        assert "systemd-run" in cmd
        assert f"MemoryMax={etl_jobs.APPLY_MEMORY_CAP_MB}M" in cmd

    def test_the_cap_is_the_figure_that_was_measured(self):
        """1,100 MB is where 25.5-second answers were measured. Raising it
        is how you get the row below that in the capacity table."""
        assert etl_jobs.APPLY_MEMORY_CAP_MB == 1100

    def test_prepare_is_not_capped(self):
        """It fetches and parses, does not embed, and spends nothing.
        Capping it would only make the cheap half slow."""
        assert "MemoryMax" not in " ".join(etl_jobs._cmd("prepare"))

    def test_both_load_the_env_file(self):
        """Without it there is no OPENAI_API_KEY and no database URL, and
        the failure is a traceback rather than an obvious misconfiguration."""
        for phase in ("prepare", "apply"):
            assert "/opt/chatbot/.env" in " ".join(etl_jobs._cmd(phase))


class TestOneAtATime:
    def _fake_run(self, monkeypatch, hold):
        def _run(job):
            hold.wait(timeout=5)
            job.returncode = 0
            job.finished_at = dt.datetime.now(dt.timezone.utc)
        monkeypatch.setattr(etl_jobs, "_run", _run)

    def test_a_second_run_is_refused_while_one_is_going(self, monkeypatch):
        """Two of these at once takes the box down, and a prepare racing an
        apply signs one diff and applies another."""
        import threading

        hold = threading.Event()
        self._fake_run(monkeypatch, hold)
        ok, _ = etl_jobs.start("prepare", started_by="a@miamioh.edu")
        assert ok
        ok2, msg = etl_jobs.start("apply", started_by="b@miamioh.edu")
        assert not ok2
        assert "already running" in msg
        hold.set()

    def test_the_refusal_says_what_is_running(self, monkeypatch):
        """"Try again later" sends somebody to the server to find out
        what. The message has to carry it."""
        import threading

        hold = threading.Event()
        self._fake_run(monkeypatch, hold)
        etl_jobs.start("prepare", started_by="a@miamioh.edu")
        _ok, msg = etl_jobs.start("prepare", started_by="b@miamioh.edu")
        assert "prepare" in msg
        hold.set()

    def test_a_finished_run_does_not_block_the_next_one(self, monkeypatch):
        monkeypatch.setattr(etl_jobs, "_run", lambda job: (
            setattr(job, "returncode", 0),
            setattr(job, "finished_at", dt.datetime.now(dt.timezone.utc))))
        assert etl_jobs.start("prepare", started_by="a@miamioh.edu")[0]
        import time
        time.sleep(0.05)
        assert etl_jobs.start("apply", started_by="a@miamioh.edu")[0]

    def test_an_unknown_phase_is_refused(self):
        ok, msg = etl_jobs.start("delete-everything", started_by="a@x.edu")
        assert not ok and "unknown phase" in msg


class TestFailuresAreVisible:
    def test_the_output_is_kept_so_the_page_can_show_it(self, monkeypatch):
        def _fake(cmd, **kw):
            return NS(returncode=1, stdout="stdout line",
                      stderr="Traceback: it broke")
        monkeypatch.setattr(etl_jobs.subprocess, "run", _fake)
        job = etl_jobs.Job(phase="prepare",
                           started_at=dt.datetime.now(dt.timezone.utc),
                           started_by="a@x.edu")
        etl_jobs._run(job)
        assert not job.ok
        assert "it broke" in job.output

    def test_stderr_comes_first(self, monkeypatch):
        """The traceback is the part worth reading, and a failure whose
        reason scrolled off the bottom is one somebody guesses at."""
        def _fake(cmd, **kw):
            return NS(returncode=1, stdout="x" * 50, stderr="THE REASON")
        monkeypatch.setattr(etl_jobs.subprocess, "run", _fake)
        job = etl_jobs.Job(phase="prepare",
                           started_at=dt.datetime.now(dt.timezone.utc),
                           started_by="a@x.edu")
        etl_jobs._run(job)
        assert job.output.startswith("THE REASON")

    def test_a_hung_run_ends_instead_of_holding_the_lock_forever(
            self, monkeypatch):
        import subprocess as sp

        def _fake(cmd, **kw):
            raise sp.TimeoutExpired(cmd, 1)
        monkeypatch.setattr(etl_jobs.subprocess, "run", _fake)
        job = etl_jobs.Job(phase="apply",
                           started_at=dt.datetime.now(dt.timezone.utc),
                           started_by="a@x.edu")
        etl_jobs._run(job)
        assert not job.running
        assert "did not finish" in job.error


class TestPromotionNeedsNoRestart:
    def test_it_switches_the_collection_in_this_process(self, monkeypatch):
        """The whole reason there is nothing to run on the server. Every
        read of the collection name on the serving path is an os.getenv at
        request time, so setting it here lands on the next question."""
        monkeypatch.setenv("WEAVIATE_CHUNK_COLLECTION", "Chunk_old")
        etl_jobs.promote_in_process("Chunk_new")

        from src.retrieval.search import _default_collection

        assert _default_collection() == "Chunk_new"

    def test_a_failed_promotion_does_not_turn_a_good_build_red(
            self, monkeypatch):
        """The corpus was built and is safe on disk. Failing the whole run
        would invite somebody to rebuild it, which costs another seven
        minutes of slow answers for nothing."""
        def _fake(cmd, **kw):
            return NS(returncode=1, stdout="", stderr="promote blew up")
        monkeypatch.setattr(etl_jobs.subprocess, "run", _fake)
        job = etl_jobs.Job(phase="apply",
                           started_at=dt.datetime.now(dt.timezone.utc),
                           started_by="a@x.edu", returncode=0)
        etl_jobs._promote_after_apply(job)
        assert job.returncode == 0
        assert "still answering from the previous one" in job.error
