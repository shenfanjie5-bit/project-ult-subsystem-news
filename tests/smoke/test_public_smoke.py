"""Smoke tier — minimal end-to-end through subsystem-news public.py.

Same shape as other modules' smoke tier. Exercise the 5 module-level
singletons end-to-end with realistic-but-minimal inputs and bound the
timing for the cheapest paths.
"""

from __future__ import annotations

import time

from subsystem_news import public


class TestSmokeFastPath:
    def test_health_probe_under_1s(self) -> None:
        start = time.monotonic()
        result = public.health_probe.check(timeout_sec=1.0)
        elapsed = time.monotonic() - start

        assert result["status"] in {"healthy", "degraded"}, result
        assert elapsed < 1.0, f"health_probe took {elapsed:.3f}s"

    def test_smoke_hook_passes_for_lite_local(self) -> None:
        result = public.smoke_hook.run(profile_id="lite-local")
        assert result["passed"], result.get("failure_reason")

    def test_smoke_hook_passes_for_full_dev(self) -> None:
        result = public.smoke_hook.run(profile_id="full-dev")
        assert result["passed"], result.get("failure_reason")

    def test_smoke_hook_rejects_unknown_profile(self) -> None:
        result = public.smoke_hook.run(profile_id="bogus-profile")
        assert not result["passed"]
        assert "unknown profile_id" in result["failure_reason"]

    def test_init_hook_returns_none(self) -> None:
        assert public.init_hook.initialize(resolved_env={}) is None

    def test_version_declaration_shape(self) -> None:
        decl = public.version_declaration.declare()
        assert decl["module_id"] == "subsystem-news"
        assert decl["module_version"]  # non-empty
        assert decl["supported_ex_types"] == ["Ex-1", "Ex-2", "Ex-3"]
        assert "produced_at" in decl["sdk_envelope_fields"]
        assert decl["ex3_high_threshold_marker"] is True

    def test_cli_version_under_1s(self) -> None:
        start = time.monotonic()
        rc = public.cli.invoke(["version"])
        elapsed = time.monotonic() - start

        assert rc == 0
        assert elapsed < 1.0, f"cli version took {elapsed:.3f}s"

    def test_cli_health_under_1s(self) -> None:
        start = time.monotonic()
        rc = public.cli.invoke(["health", "--timeout-sec", "1.0"])
        elapsed = time.monotonic() - start

        # exit 0 on healthy/degraded, 1 on down
        assert rc in {0, 1}, rc
        assert elapsed < 1.0, f"cli health took {elapsed:.3f}s"
