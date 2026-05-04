"""
Basic tests — run with:  pytest tests/
No GPU or Prometheus server required.
"""

import asyncio
import pytest

from infra_metrics import configure, track
from infra_metrics._metrics import ERROR_COUNT, REQUEST_COUNT, REQUEST_LATENCY
from infra_metrics._gpu import NVML_AVAILABLE


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _configure():
    configure(service="test-svc", env="test", gpu_device_index=None)


# ── @track on sync functions ──────────────────────────────────────────────────

def test_sync_increments_request_count():
    before = REQUEST_COUNT.labels("test-svc", "my_fn", "ok")._value.get()

    @track()
    def my_fn():
        return 42

    assert my_fn() == 42
    after = REQUEST_COUNT.labels("test-svc", "my_fn", "ok")._value.get()
    assert after == before + 1


def test_sync_records_error_on_exception():
    @track()
    def boom():
        raise ValueError("oops")

    with pytest.raises(ValueError):
        boom()

    count = ERROR_COUNT.labels("test-svc", "boom", "ValueError")._value.get()
    assert count >= 1


def test_sync_custom_endpoint_label():
    @track(endpoint="custom")
    def anything():
        return "ok"

    anything()
    count = REQUEST_COUNT.labels("test-svc", "custom", "ok")._value.get()
    assert count >= 1


# ── @track on async functions ─────────────────────────────────────────────────

def test_async_increments_request_count():
    before = REQUEST_COUNT.labels("test-svc", "async_fn", "ok")._value.get()

    @track()
    async def async_fn():
        return "done"

    asyncio.run(async_fn())
    after = REQUEST_COUNT.labels("test-svc", "async_fn", "ok")._value.get()
    assert after == before + 1


def test_async_records_error():
    @track()
    async def async_boom():
        raise RuntimeError("async fail")

    with pytest.raises(RuntimeError):
        asyncio.run(async_boom())

    count = ERROR_COUNT.labels("test-svc", "async_boom", "RuntimeError")._value.get()
    assert count >= 1


# ── GPU availability ──────────────────────────────────────────────────────────

def test_nvml_availability_is_bool():
    assert isinstance(NVML_AVAILABLE, bool)


def test_gpu_tracking_skipped_when_disabled():
    """gpu=False should not raise even on a GPU machine."""
    @track(gpu=False)
    def infer():
        return "result"

    assert infer() == "result"
