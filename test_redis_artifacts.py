"""
Tests for Redis-backed artifact persistence (using fakeredis).

These tests:
 - exercise `run_analysis_job` to create artifacts (with a fake analyze implementation)
 - verify artifact metadata is persisted into Redis (via the artifact store)
 - simulate a restart by replacing the in-memory store with a new Redis-backed view
 - (optional) verify the FastAPI artifact download endpoint using TestClient if available

Notes:
 - These tests use `fakeredis` to emulate Redis. If `fakeredis` is not installed the tests
   will be skipped gracefully.
 - The tests follow the lightweight style used in the repo (print + return True/False).
"""

import os
import shutil
import pytest

# Local imports
try:
    import fakeredis
except Exception:
    fakeredis = None  # type: ignore

try:
    import api
    import bibliometrics
    import jobs
except Exception:
    jobs = None  # type: ignore
    bibliometrics = None  # type: ignore
    api = None  # type: ignore

try:
    from fastapi.testclient import TestClient
except Exception:
    TestClient = None  # type: ignore


def _fake_analyze(
    query,
    max_results_per_source=200,
    sources=None,
    output_dir=None,
    use_cache=True,
    cache_ttl_hours=24,
):
    """
    Minimal stub for bibliometrics.analyze_field used in tests.
    Writes a small GEXF and HTML file into output_dir and returns an exports mapping.
    """
    if output_dir is None:
        raise RuntimeError("output_dir must be provided for fake analyze")
    os.makedirs(output_dir, exist_ok=True)
    gexf = os.path.join(output_dir, "test_coauthorship.gexf")
    html = os.path.join(output_dir, "test_coauthorship.html")
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


def test_redis_artifact_persistence():
    """Test artifact metadata persisted to Redis and retrievable after a simulated restart."""
    print("\nTesting Redis-backed artifact persistence...")

    if jobs is None or bibliometrics is None:
        pytest.skip("Project modules not available; skipping")

    if fakeredis is None:
        pytest.skip("fakeredis not available; skipping Redis persistence tests")

    # Save original store and replace with a Redis-backed store that uses fakeredis
    orig_store = getattr(jobs, "_ARTIFACT_STORE", None)
    fake_redis = fakeredis.FakeRedis()
    # Create a RedisArtifactStore-like object that uses the fake_redis
    # We bypass __init__ to avoid requiring real redis.from_url calls.
    redis_store = object.__new__(jobs.RedisArtifactStore)
    redis_store._conn = fake_redis  # type: ignore

    jobs._ARTIFACT_STORE = redis_store

    # Monkeypatch bibliometrics.analyze_field to avoid external calls
    orig_analyze = bibliometrics.analyze_field
    bibliometrics.analyze_field = _fake_analyze

    artifact_id = None
    out_dir = None
    try:
        # Run analysis and register artifact (persisted into fake redis)
        res = jobs.run_analysis_job("redis-test", max_results=5)
        artifact_id = res.get("artifact_id")
        token = res.get("download_token")
        exports = res.get("exports", {})
        paths = res.get("exports_paths", {})

        assert artifact_id, "artifact_id missing"
        assert token, "download_token missing"
        assert "gexf" in exports, "exports missing expected key 'gexf'"
        assert "gexf" in paths, "exports_paths missing expected key 'gexf'"

        # Now fetch via job API (which should read from fake redis)
        meta = jobs.get_job_artifacts(artifact_id)
        assert meta is not None, "artifact metadata not found in store"
        assert meta.get("download_token") == token, (
            "token mismatch with persisted metadata"
        )
        out_dir = meta.get("output_dir")
        assert out_dir and os.path.exists(out_dir), (
            "artifact output_dir missing on disk"
        )

        # Simulate restart: replace _ARTIFACT_STORE with a fresh RedisArtifactStore wrapper
        new_wrapper = object.__new__(jobs.RedisArtifactStore)
        new_wrapper._conn = fake_redis  # same underlying fake redis
        jobs._ARTIFACT_STORE = new_wrapper

        # Retrieve metadata again after 'restart'
        meta2 = jobs.get_job_artifacts(artifact_id)
        assert meta2 is not None, (
            "artifact metadata not persisted across store wrapper replacement"
        )
        assert meta2.get("download_token") == token

        print(
            "  ✓ Redis-backed artifact persisted and is retrievable after restart simulation"
        )
    except AssertionError as ae:
        pytest.fail(f"Assertion failed: {ae}")
    except Exception as e:
        import traceback

        traceback.print_exc()
        pytest.fail(f"Exception during test: {e}")
    finally:
        # restore original analyze and artifact store; cleanup files
        bibliometrics.analyze_field = orig_analyze
        if artifact_id:
            try:
                jobs.clear_job_artifacts(artifact_id)
            except Exception:
                pass
        if out_dir and os.path.exists(out_dir):
            shutil.rmtree(out_dir, ignore_errors=True)
        # restore original store
        jobs._ARTIFACT_STORE = orig_store


def test_redis_artifact_download_endpoint():
    """Optional: test the FastAPI download endpoint when artifacts are stored in Redis (via fakeredis)."""
    print("\nTesting artifact download endpoint with Redis persistence...")

    if jobs is None or bibliometrics is None or api is None:
        pytest.skip("Project modules not available; skipping")

    if fakeredis is None:
        pytest.skip("fakeredis not available; skipping Redis download endpoint test")

    if TestClient is None:
        pytest.skip("FastAPI TestClient not available; skipping endpoint test")

    # Setup fake redis store
    orig_store = getattr(jobs, "_ARTIFACT_STORE", None)
    fake_redis = fakeredis.FakeRedis()
    redis_store = object.__new__(jobs.RedisArtifactStore)
    redis_store._conn = fake_redis  # type: ignore
    jobs._ARTIFACT_STORE = redis_store

    # Monkeypatch analyze to write files
    orig_analyze = bibliometrics.analyze_field
    bibliometrics.analyze_field = _fake_analyze

    client = TestClient(api.app)
    artifact_id = None
    out_dir = None
    try:
        # Run sync analyze to get artifact & token
        resp = client.post(
            "/analyze", json={"query": "download-test", "max_results": 5}
        )
        assert resp.status_code == 200, (
            f"/analyze failed: {resp.status_code} {resp.text}"
        )
        data = resp.json()
        artifact_id = data.get("artifact_id")
        token = data.get("download_token")
        exports = data.get("exports", {})
        _ = data.get("exports_paths", {})
        assert artifact_id and token and exports, (
            "missing artifact info in /analyze response"
        )
        gexf_url = exports.get("gexf")
        assert gexf_url and "download" in gexf_url, "unexpected gexf download URL"

        # Try to download using the returned URL (it includes the token query param)
        r = client.get(gexf_url)
        if r.status_code != 200:
            pytest.fail(f"Download endpoint returned: {r.status_code} {r.text}")
        assert r.content and r.content.startswith(b"<?xml"), (
            "downloaded content not expected"
        )

        # Also try listing files endpoint with token
        r2 = client.get(f"/artifacts/{artifact_id}/files?token={token}")
        assert r2.status_code == 200
        files = r2.json().get("files", [])
        assert any("test_coauthorship.gexf" in f for f in files), (
            "gexf not listed in files"
        )

        print("  ✓ artifact download endpoint works with Redis-backed metadata")
    except AssertionError as ae:
        pytest.fail(f"Assertion failed: {ae}")
    except Exception as e:
        import traceback

        traceback.print_exc()
        pytest.fail(f"Exception during endpoint test: {e}")
    finally:
        bibliometrics.analyze_field = orig_analyze
        if artifact_id:
            try:
                jobs.clear_job_artifacts(artifact_id)
            except Exception:
                pass
        if out_dir and os.path.exists(out_dir):
            shutil.rmtree(out_dir, ignore_errors=True)
        jobs._ARTIFACT_STORE = orig_store


def run_all_tests():
    """Run all tests in this file (compatible with repo's lightweight test runner)."""
    print("=" * 60)
    print("Running Redis artifact tests")
    print("=" * 60 + "\n")

    tests = [test_redis_artifact_persistence, test_redis_artifact_download_endpoint]
    results = []
    for t in tests:
        try:
            r = t()
            results.append(bool(r))
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
