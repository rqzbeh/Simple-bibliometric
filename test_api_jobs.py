"""
Tests for the API endpoints covering:
 - synchronous analysis (`POST /analyze`)
 - asynchronous analysis job flow (`POST /analyze_async` -> poll `/jobs/{job_id}` -> `/jobs/{job_id}/result`)
 - artifact listing and secure downloads (`/artifacts/{artifact_id}/files`, `/artifacts/{artifact_id}/download/{filename}`)

These tests are written to be lightweight and avoid calling external services by monkeypatching
`bibliometrics.analyze_field` with a small fake that writes known artifacts into the provided
`output_dir`.
"""

import os
import shutil
import time
from typing import Any, Dict

import pytest

try:
    from fastapi.testclient import TestClient
except Exception:
    # If TestClient is not available, tests will be skipped gracefully below.
    TestClient = None  # type: ignore

# Local imports (project modules)
try:
    import api
    import bibliometrics
    import jobs
except Exception:  # pragma: no cover - environment without the package
    bibliometrics = None  # type: ignore
    jobs = None  # type: ignore
    api = None  # type: ignore


def _fake_analyze_write_files(
    query: str,
    max_results_per_source=200,
    sources=None,
    output_dir=None,
    use_cache=True,
    cache_ttl_hours=24,
) -> Dict[str, Any]:
    """
    Fake analyze_field implementation that writes a couple of small artifact files to
    `output_dir` and returns a minimal analysis result dict.
    """
    os.makedirs(output_dir, exist_ok=True)
    gexf_path = os.path.join(output_dir, "test_coauthorship.gexf")
    html_path = os.path.join(output_dir, "test_coauthorship.html")
    with open(gexf_path, "w", encoding="utf-8") as fh:
        fh.write("<?xml version='1.0'?><graph>dummy gexf</graph>")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write("<html><body>dummy pyvis</body></html>")

    return {
        "query": query,
        "n_publications": 0,
        "publications": [],
        "top_authors": [],
        "graph": None,
        "exports": {"gexf": gexf_path, "pyvis": html_path},
        "time_series": {},
        "forecast": {},
        "source_errors": [],
    }


def test_analyze_sync_and_artifact_download():
    """Test synchronous /analyze returns artifact info and files are downloadable."""
    print("\nTesting synchronous /analyze -> artifact download")

    if TestClient is None or bibliometrics is None or api is None:
        pytest.skip("FastAPI TestClient or project modules not available; skipping")

    client = TestClient(api.app)

    # Monkeypatch analyze_field to avoid external network calls
    orig_analyze = bibliometrics.analyze_field
    bibliometrics.analyze_field = _fake_analyze_write_files

    out_dir_to_cleanup = None
    try:
        resp = client.post(
            "/analyze",
            json={
                "query": "test sync",
                "max_results": 10,
                "use_cache": False,
                "cache_ttl_hours": 0,
            },
        )
        if resp.status_code != 200:
            pytest.fail(f"/analyze returned non-200: {resp.status_code} {resp.text}")

        data = resp.json()
        print("  ✓ /analyze response keys:", list(data.keys()))
        artifact_id = data.get("artifact_id")
        download_token = data.get("download_token")
        exports = data.get("exports", {})
        paths = data.get("exports_paths", {})
        out_dir_to_cleanup = data.get("_job_output_dir")

        if not artifact_id:
            pytest.fail("Missing artifact_id in response")
        if not download_token:
            pytest.fail("Missing download_token in response")
        if "gexf" not in exports or "gexf" not in paths:
            pytest.fail("Missing gexf export in response")

        gexf_url = exports["gexf"]
        print("  ✓ gexf download URL:", gexf_url)

        # Download the file using the returned URL (it already includes token query param)
        r2 = client.get(gexf_url)
        if r2.status_code != 200:
            pytest.fail(f"Failed to download gexf: {r2.status_code} {r2.text}")
        content = r2.content.decode("utf-8")
        if "dummy gexf" not in content:
            pytest.fail(f"Unexpected gexf content: {content}")
        print("  ✓ gexf content validated")

        # Test listing files via /artifacts/{artifact_id}/files (requires token)
        rfiles = client.get(f"/artifacts/{artifact_id}/files?token={download_token}")
        if rfiles.status_code != 200:
            pytest.fail(f"Failed to list artifact files: {rfiles.status_code} {rfiles.text}")
        flist = rfiles.json().get("files", [])
        if not any("test_coauthorship.gexf" in f for f in flist):
            pytest.fail(f"Expected gexf not listed in artifact files: {flist}")
        print("  ✓ artifact files listed:", flist)

        print("  ✓ synchronous analyze + artifact download flow works")
    except Exception as exc:
        pytest.fail(f"Exception during sync analysis test: {exc}")
    finally:
        # revert monkeypatch
        bibliometrics.analyze_field = orig_analyze
        # cleanup filesystem artifacts if present
        try:
            if out_dir_to_cleanup and os.path.exists(out_dir_to_cleanup):
                shutil.rmtree(out_dir_to_cleanup, ignore_errors=True)
                # also clear registered artifacts if any
                try:
                    jobs.clear_job_artifacts(out_dir_to_cleanup)
                except Exception:
                    pass
        except Exception:
            pass


def test_analyze_async_job_and_artifact_download():
    """Test async job flow: enqueue, poll, fetch result, download artifact file."""
    print("\nTesting async /analyze_async -> poll jobs -> download artifact")

    if TestClient is None or bibliometrics is None or api is None or jobs is None:
        pytest.skip("FastAPI TestClient or project modules not available; skipping")

    client = TestClient(api.app)

    # Monkeypatch analyze_field with our fake
    orig_analyze = bibliometrics.analyze_field
    bibliometrics.analyze_field = _fake_analyze_write_files

    out_dir_to_cleanup = None
    try:
        # Enqueue async job
        resp = client.post(
            "/analyze_async",
            json={
                "query": "test async",
                "max_results": 10,
                "use_cache": False,
                "cache_ttl_hours": 0,
            },
        )
        if resp.status_code != 200:
            pytest.fail(f"/analyze_async returned non-200: {resp.status_code} {resp.text}")
        jinfo = resp.json()
        job_id = jinfo.get("job_id")
        if not job_id:
            pytest.fail("No job_id returned from /analyze_async")
        print("  ✓ job enqueued:", job_id)

        # Poll job status until finished (with timeout)
        finished = False
        status_url = f"/jobs/{job_id}"
        for _ in range(100):  # up to ~5 seconds (100 * 0.05)
            sj = client.get(status_url)
            if sj.status_code != 200:
                pytest.fail(f"Failed to fetch job status: {sj.status_code} {sj.text}")
            sdata = sj.json()
            if sdata.get("status") == "finished":
                finished = True
                break
            time.sleep(0.05)

        if not finished:
            pytest.fail(f"Job did not finish in time; last status: {sdata}")
        print("  ✓ job finished")

        # Fetch job result
        rres = client.get(f"/jobs/{job_id}/result")
        if rres.status_code != 200:
            pytest.fail(f"/jobs/{{job_id}}/result returned non-200: {rres.status_code} {rres.text}")
        resdata = rres.json()
        artifact_info = resdata.get("artifact_info", {})
        if not artifact_info:
            pytest.fail(f"No artifact_info present in job result: {resdata.keys()}")
        download_urls = artifact_info.get("download_urls", {})
        _token = artifact_info.get("download_token")
        if "gexf" not in download_urls:
            pytest.fail(f"gexf not present in download_urls: {download_urls}")
        gexf_url = download_urls["gexf"]
        print("  ✓ gexf download URL:", gexf_url)

        # Download artifact
        rdown = client.get(gexf_url)
        if rdown.status_code != 200:
            pytest.fail(f"Failed to download artifact: {rdown.status_code} {rdown.text}")
        content = rdown.content.decode("utf-8")
        if "dummy gexf" not in content:
            pytest.fail(f"Unexpected artifact content: {content}")
        print("  ✓ artifact downloaded and content validated")

        # Determine output_dir for cleanup (job result includes _job_output_dir)
        out_dir_to_cleanup = resdata.get("_job_output_dir")
        print("  ✓ cleanup dir:", out_dir_to_cleanup)

        print("  ✓ async job flow + artifact download works")
    except Exception as exc:
        pytest.fail(f"Exception during async analysis test: {exc}")
    finally:
        # revert monkeypatch
        bibliometrics.analyze_field = orig_analyze
        # cleanup artifacts
        try:
            if out_dir_to_cleanup and os.path.exists(out_dir_to_cleanup):
                shutil.rmtree(out_dir_to_cleanup, ignore_errors=True)
                try:
                    # artifacts were registered under the job id (artifact id)
                    jobs.clear_job_artifacts(out_dir_to_cleanup)
                except Exception:
                    pass
        except Exception:
            pass


def run_all_tests():
    """Run tests in this file (compat with the project's lightweight test runner)."""
    print("=" * 60)
    print("Running API job & artifact tests")
    print("=" * 60 + "\n")

    tests = [
        test_analyze_sync_and_artifact_download,
        test_analyze_async_job_and_artifact_download,
    ]
    results = []
    for t in tests:
        try:
            result = t()
            results.append(bool(result))
        except Exception as e:
            print(f"\n✗ Test {t.__name__} crashed: {e}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    return all(results)


if __name__ == "__main__":
    ok = run_all_tests()
    import sys

    sys.exit(0 if ok else 1)
