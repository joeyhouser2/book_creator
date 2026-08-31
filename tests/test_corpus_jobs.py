"""Driving the latin repo's translate / victorianize passes as jobs.

The passes themselves need a GPU and a multi-gigabyte model, so nothing here
runs one. Instead a stub repo is built in a temp directory whose "scripts"
print the same output the real ones do -- which exercises the parts that are
actually this project's: command construction, progress parsing, log
filtering, cancellation, and failure reporting.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from book_creator import corpus_jobs


# --------------------------------------------------------------------------- #
# Locating the repo and interpreter
# --------------------------------------------------------------------------- #
def test_a_bad_latin_repo_env_var_is_rejected_by_name(monkeypatch, tmp_path):
    """Naming the variable that is wrong beats a generic "not found"."""
    monkeypatch.setenv("LATIN_REPO", str(tmp_path / "nope"))
    with pytest.raises(corpus_jobs.JobError) as exc:
        corpus_jobs.find_repo()
    assert "LATIN_REPO" in str(exc.value)
    assert "not a usable latin repo" in str(exc.value)


def test_find_repo_error_names_what_it_tried(monkeypatch, tmp_path):
    """With nothing named at all, the fallbacks are searched -- and listed."""
    monkeypatch.setattr(corpus_jobs, "_REPO_CANDIDATES", (str(tmp_path / "nope"),))
    monkeypatch.delenv("LATIN_REPO", raising=False)
    with pytest.raises(corpus_jobs.JobError) as exc:
        corpus_jobs.find_repo()
    assert "LATIN_REPO" in str(exc.value)
    assert "Tried" in str(exc.value)


def test_find_repo_rejects_a_bare_database(tmp_path):
    """A copied-out corpus.db is enough to read from but not to write into."""
    db = tmp_path / "corpus.db"
    db.write_bytes(b"")
    with pytest.raises(corpus_jobs.JobError, match="not a repo checkout"):
        corpus_jobs.find_repo(str(db))


def test_an_explicit_path_never_falls_back_to_another_checkout(tmp_path):
    """These passes write. Silently translating into a different corpus than
    the one the caller named would be the worst failure this module has."""
    # A real checkout exists in the default locations on this machine; the
    # point is that naming a bad path must not reach it.
    with pytest.raises(corpus_jobs.JobError, match="is not a usable latin repo"):
        corpus_jobs.find_repo(str(tmp_path / "not-a-repo"))


def test_a_repo_missing_one_script_is_not_treated_as_the_wrong_repo(stub_repo):
    """It is the repo; it just lacks that pass. `run` says so by name."""
    assert corpus_jobs.find_repo(str(stub_repo)) == stub_repo.resolve()


def test_find_python_falls_back_to_this_interpreter(stub_repo):
    # The stub repo has no venv; failing here would be worse than using ours,
    # which carries torch and transformers anyway.
    assert corpus_jobs.find_python(stub_repo) == Path(sys.executable)


def test_find_python_prefers_the_repo_venv(stub_repo):
    venv = stub_repo / "latinvenv" / "Scripts"
    venv.mkdir(parents=True)
    (venv / "python.exe").write_text("")
    assert corpus_jobs.find_python(stub_repo) == venv / "python.exe"


# --------------------------------------------------------------------------- #
# GPU selection
# --------------------------------------------------------------------------- #
def test_gpus_parses_nvidia_smi(monkeypatch):
    class Result:
        returncode = 0
        stdout = ("0, NVIDIA GeForce RTX 4060 Ti, 16380\n"
                  "1, NVIDIA GeForce RTX 4070 SUPER, 12282\n"
                  "garbage line\n")

    monkeypatch.setattr(corpus_jobs.subprocess, "run", lambda *a, **k: Result())
    found = corpus_jobs.gpus()
    assert [g.index for g in found] == [0, 1]
    assert found[0].total_mb == 16380


def test_gpus_is_empty_without_nvidia_smi(monkeypatch):
    def boom(*a, **k):
        raise OSError("no nvidia-smi")

    monkeypatch.setattr(corpus_jobs.subprocess, "run", boom)
    assert corpus_jobs.gpus() == []
    assert corpus_jobs.best_gpu() is None


def test_auto_device_picks_the_biggest_card_not_device_zero(monkeypatch):
    """The whole point: CUDA's default order is fastest-first, so plain
    "cuda" can land on the smaller card. Auto must choose by memory."""
    monkeypatch.setattr(corpus_jobs, "gpus", lambda: [
        corpus_jobs.Gpu(0, "small", 8192),
        corpus_jobs.Gpu(1, "big", 16380),
    ])
    env = corpus_jobs._cuda_env(None)
    assert env["CUDA_VISIBLE_DEVICES"] == "1"
    # Without PCI ordering the index would mean something else in the child.
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"


def test_explicit_device_and_cpu(monkeypatch):
    monkeypatch.setattr(corpus_jobs, "gpus", lambda: [corpus_jobs.Gpu(0, "a", 1)])
    assert corpus_jobs._cuda_env(1)["CUDA_VISIBLE_DEVICES"] == "1"
    assert corpus_jobs._cuda_env("cpu")["CUDA_VISIBLE_DEVICES"] == ""


def test_no_cuda_leaves_the_environment_alone(monkeypatch):
    monkeypatch.setattr(corpus_jobs, "gpus", lambda: [])
    assert corpus_jobs._cuda_env(None) == {}


# --------------------------------------------------------------------------- #
# Command construction
# --------------------------------------------------------------------------- #
def test_translate_command_carries_the_document_and_tuning():
    cmd = corpus_jobs._translate_cmd(42, {"batch_size": 8, "chunk": 50})
    assert cmd[0] == "scripts/translate_pending.py"
    assert "--doc-id" in cmd and "42" in cmd
    assert cmd[cmd.index("--batch-size") + 1] == "8"
    assert cmd[cmd.index("--chunk") + 1] == "50"


def test_stylize_command_rejects_unknown_preset_and_backend():
    with pytest.raises(corpus_jobs.JobError, match="preset"):
        corpus_jobs._stylize_cmd(1, {"preset": "pirate"})
    with pytest.raises(corpus_jobs.JobError, match="backend"):
        corpus_jobs._stylize_cmd(1, {"backend": "quantum"})


def test_unknown_pass_is_refused():
    with pytest.raises(corpus_jobs.JobError, match="unknown pass"):
        corpus_jobs.run("delete-everything", 1)


# --------------------------------------------------------------------------- #
# Running a pass
# --------------------------------------------------------------------------- #
@pytest.fixture
def stub_repo(tmp_path, monkeypatch):
    """A directory shaped like the latin repo, so find_repo accepts it."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "corpus.db").write_bytes(b"")
    (tmp_path / "scripts").mkdir()
    # No real CUDA in the test environment, and none needed.
    monkeypatch.setattr(corpus_jobs, "gpus", lambda: [])
    return tmp_path


def write_script(repo: Path, name: str, body: str) -> None:
    (repo / "scripts" / name).write_text(textwrap.dedent(body), encoding="utf-8")


def run_stub(repo, **kwargs):
    """Run a pass against the stub repo, collecting log and progress."""
    log: list[str] = []
    progress: list[tuple] = []
    result = corpus_jobs.run(
        kwargs.pop("kind", "translate"), kwargs.pop("doc_id", 1),
        repo_path=str(repo), on_log=log.append,
        on_progress=lambda d, t, i=None: progress.append((d, t, i)),
        **kwargs)
    return result, log, progress


def test_progress_lines_become_progress_not_log(stub_repo):
    """A long pass emits thousands of progress lines; they must not all end
    up in the log the browser re-downloads on every poll."""
    write_script(stub_repo, "translate_pending.py", """
        print("=== Translate pending: 1 docs, 300 segments ===")
        print("Loading translation model: models/nllb-latin")
        for done in (100, 200, 300):
            print(f"  [1] src   {done}/300 | overall {done:,}/300 2.5 seg/s ETA 0.1h")
        print("Done. Translated 300 segments across 1 docs in 0.1h.")
    """)
    result, log, progress = run_stub(stub_repo)

    assert result == {"segments": 300, "cancelled": False}
    assert [(d, t) for d, t, _ in progress] == [(0, 300), (100, 300), (200, 300), (300, 300)]
    assert progress[-1][2] == {"rate": 2.5, "eta_hours": 0.1}
    # The model-loading notice is kept; the per-chunk spam is not.
    assert any("nllb-latin" in line for line in log)
    assert not any("overall" in line for line in log)


def test_the_total_is_known_before_any_chunk_lands(stub_repo):
    """So the bar is scaled during the long silent model load."""
    write_script(stub_repo, "translate_pending.py", """
        print("=== Translate pending: 1 docs, 12,345 segments ===")
    """)
    _, _, progress = run_stub(stub_repo)
    assert progress[0] == (0, 12345, None)


def test_tqdm_frames_are_dropped(stub_repo):
    """Universal newlines turn one tqdm bar into hundreds of "lines"."""
    write_script(stub_repo, "translate_pending.py", r"""
        print("=== Translate pending: 1 docs, 1 segments ===")
        print("Loading weights:   1%|          | 6/512 [00:00<00:00, 1194.96it/s]")
        print("Loading weights:  50%|#####     | 256/512 [00:00<00:00, 1194.96it/s]")
        print("a real message")
    """)
    _, log, _ = run_stub(stub_repo)
    assert "a real message" in log
    assert not any("Loading weights" in line for line in log)


def test_a_failing_script_raises_with_its_status(stub_repo):
    write_script(stub_repo, "translate_pending.py", """
        import sys
        print("something went wrong")
        sys.exit(3)
    """)
    with pytest.raises(corpus_jobs.JobError, match="status 3"):
        run_stub(stub_repo)


def test_a_missing_script_is_reported_clearly(stub_repo):
    with pytest.raises(corpus_jobs.JobError, match="missing from the latin repo"):
        run_stub(stub_repo, kind="stylize")


def test_cancelling_stops_the_pass_and_keeps_what_was_done(stub_repo):
    """Stop must take effect while the script is *silent* -- a batch can run
    for minutes without printing, and that is exactly when a user cancels."""
    write_script(stub_repo, "stylize_library.py", """
        import time
        print("=== Stylize (victorian_prose/t5) shard 0/1: 1 docs, 900 segments pending ===")
        for done in range(20, 920, 20):
            print(f"  [1] src   {done}/900 | overall {done:,}/900 1.0 seg/s ETA 0.2h")
            time.sleep(2)          # a long, silent batch
        print("Done. Stylized 900 segments across 1 docs in 0.2h.")
    """)
    seen: list[tuple] = []
    log: list[str] = []
    result = corpus_jobs.run(
        "stylize", 1, repo_path=str(stub_repo), on_log=log.append,
        on_progress=lambda d, t, i=None: seen.append((d, t)),
        # Stop once the pass is genuinely under way.
        should_stop=lambda: len(seen) >= 3)

    assert result["cancelled"] is True
    # It stopped early rather than running all 45 chunks to completion.
    assert len(seen) < 45
    assert any("kept" in line for line in log)


def test_status_reports_unavailable_without_a_repo(monkeypatch, tmp_path):
    monkeypatch.setattr(corpus_jobs, "_REPO_CANDIDATES", ())
    monkeypatch.setattr(corpus_jobs, "gpus", lambda: [])
    monkeypatch.setenv("LATIN_REPO", str(tmp_path / "nope"))
    status = corpus_jobs.status()
    assert status["available"] is False
    assert "error" in status


def test_status_describes_a_usable_repo(stub_repo):
    status = corpus_jobs.status(str(stub_repo))
    assert status["available"] is True
    assert status["repo"] == str(stub_repo.resolve())
    assert "victorian_prose" in status["presets"]
