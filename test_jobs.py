"""
Basic tests for job submission and run_analysis_job behavior.

These tests exercise the in-process job backend (no FastAPI required) and verify:
- `run_analysis_job` registers artifacts and returns download metadata
- submitting `run_analysis_job` via `submit_job` yields a job whose id equals the artifact id
  (the in-process backend injects the job id into the callable when possible)

The tests are lightweight and stub out the heavy `bibliometrics.analyze_field` method to
write small, deterministic artifact files in the specified output directory.
"""

import os
import shutil
import time
from typing import Any, Dict

# Import project modules under test
try:
    import bibliometrics
    import jobs
except Exception as e:
    # If imports fail, tests will be skipped when run directly
    jobs = None  # type: ignore
    bibliometrics = None  # type: ignore


def _fake_analyze_field(
    query: str,
    max_results_per_source: int = 200,
    sources=None,
    output_dir=None,
    use_cache=True,
    cache_ttl_hours=24,
) -> Dict[str, Any]:
    """
    Minimal stand-in for bibliometrics.analyze_field that writes a couple of files
    into `output_dir` and returns the expected shape with 'exports' pointing to
    the filesystem paths.
    """
    if output_dir is None:
        raise RuntimeError("output_dir must be provided for fake analyze")
    os.makedirs(output_dir, exist_ok=True)
    gexf = os.path.join(output_dir, f"{query.replace(' ', '_')}_coauthorship.gexf")
    html = os.path.join(output_dir, f"{query.replace(' ', '_')}_coauthorship.html")
    with open(gexf, "w", encoding="utf-8") as fh:
        fh.write("<?xml version='1.0'?><gexf>dummy</gexf>")
    with open(html, "w", encoding="utf-8") as fh:
        fh.write("<html><body>dummy pyvis</body></html>")

    return {
        "query": query,
        "n_publications": 0,
        "publications": [],
        "top_authors": [],
        "graph": None,
        "exports": {"gexf": gexf, "pyvis": html},
        "time_series": {},
        "forecast": {},
        "source_errors": [],
    }


def test_run_analysis_job_direct():
    """Directly call run_analysis_job and validate artifact registration & paths."""
    print("\nTesting run_analysis_job (direct invocation)...")

    if jobs is None or bibliometrics is None:
        print("  ⚠ project modules not available; skipping")
        return True

    orig = bibliometrics.analyze_field
    bibliometrics.analyze_field = _fake_analyze_field

    artifact_id = None
    out_dir = None
    try:
        res = jobs.run_analysis_job(
            "test_direct",
            max_results=5,
            sources=["pubmed"],
            use_cache=False,
            cache_ttl_hours=0,
        )
        # Basic result shape
        assert isinstance(res, dict)
        artifact_id = res.get("artifact_id")
        token = res.get("download_token")
        exports = res.get("exports", {})
        paths = res.get("exports_paths", {})

        assert artifact_id, "artifact_id missing from run_analysis_job result"
        assert token, "download_token missing from run_analysis_job result"
        assert "gexf" in exports, f"exports did not include expected keys: {exports}"
        assert "gexf" in paths, f"exports_paths did not include expected keys: {paths}"

        # exports should be converted to download URLs (relative path starting with /artifacts/)
        gexf_url = exports["gexf"]
        assert isinstance(gexf_url, str) and "/artifacts/" in gexf_url, (
            f"unexpected gexf URL: {gexf_url}"
        )

        # filesystem path should exist
        gexf_path = paths["gexf"]
        assert os.path.exists(gexf_path), f"expected artifact file missing: {gexf_path}"
        with open(gexf_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        assert "<gexf" in content.lower()

        # Registered artifact metadata should be available via job registry
        meta = jobs.get_job_artifacts(artifact_id)
        assert meta is not None, "artifact metadata not registered"
        out_dir = meta.get("output_dir")
        assert out_dir and os.path.exists(out_dir)

        print("  ✓ run_analysis_job wrote artifacts and registered metadata")
        return True
    except AssertionError as ae:
        print("  ✗ Assertion failed:", ae)
        return False
    except Exception as e:
        print("  ✗ Exception during test:", e)
        return False
    finally:
        # restore
        bibliometrics.analyze_field = orig
        # cleanup files and registry
        try:
            if artifact_id:
                jobs.clear_job_artifacts(artifact_id)
            if out_dir and os.path.exists(out_dir):
                shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass


def test_submit_job_inprocess_flow():
    """Submit `run_analysis_job` via submit_job (in-process) and validate end-to-end flow."""
    print("\nTesting submit_job -> run_analysis_job (in-process backend)...")

    if jobs is None or bibliometrics is None:
        print("  ⚠ project modules not available; skipping")
        return True

    orig = bibliometrics.analyze_field
    bibliometrics.analyze_field = _fake_analyze_field

    job_id = None
    out_dir = None
    try:
        job_id = jobs.submit_job(
            jobs.run_analysis_job, "test_async", 5, ["pubmed"], False, 0
        )
    except Exception as e:
        print("  ✗ Failed to submit job:", e)
        bibliometrics.analyze_field = orig
        return False

    try:
        # Poll for completion
        finished = False
        info = None
        for _ in range(200):
            info = jobs.get_job_info(job_id)
            if info and info.get("status") == "finished":
                finished = True
                break
            time.sleep(0.02)

        if not finished:
            print("  ✗ Job did not finish in time:", info)
            return False

        # Fetch result
        try:
            result = jobs.get_job_result(job_id, timeout=1)
        except Exception as e:
            print("  ✗ Failed to retrieve job result:", e)
            return False

        # The in-process backend injects job_id into run_analysis_job, so artifact_id should match job_id
        artifact_id = result.get("artifact_id")
        assert artifact_id == job_id, (
            f"artifact_id ({artifact_id}) != job_id ({job_id})"
        )

        # Artifact metadata should be registered
        meta = jobs.get_job_artifacts(job_id)
        assert meta is not None, "artifact metadata missing for job_id"
        out_dir = meta.get("output_dir")
        assert out_dir and os.path.exists(out_dir), "artifact output dir missing"

        # Original file path should exist as recorded in exports_paths
        exports_paths = meta.get("exports_paths") or result.get("exports_paths") or {}
        gexf_path = exports_paths.get("gexf")
        assert gexf_path and os.path.exists(gexf_path), (
            "expected artifact file missing on disk"
        )

        print("  ✓ submit_job (in-process) completed and artifact available")
        return True
    except AssertionError as ae:
        print("  ✗ Assertion failed:", ae)
        return False
    except Exception as e:
        print("  ✗ Exception during test:", e)
        return False
    finally:
        # restore and cleanup
        bibliometrics.analyze_field = orig
        try:
            if job_id:
                jobs.clear_job_artifacts(job_id)
            if out_dir and os.path.exists(out_dir):
                shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass


def run_all_tests():
    """Run tests in this file (compat with the project's lightweight test runner)."""
    print("=" * 60)
    print("Running job tests")
    print("=" * 60 + "\n")

    tests = [test_run_analysis_job_direct, test_submit_job_inprocess_flow]
    results = []
    for test in tests:
        try:
            ok = test()
            results.append(bool(ok))
        except Exception as e:
            print(f"\n✗ Test {test.__name__} crashed: {e}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    import sys

    sys.exit(0 if success else 1)
