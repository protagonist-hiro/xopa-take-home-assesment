from app.routers.metrics import build_prometheus_metrics


def test_build_prometheus_metrics_contains_core_lines():
    text = build_prometheus_metrics(
        total_calls=12,
        active_calls=3,
        completed_calls=9,
        pending_uploads=1,
        cps_current={"test-key-1": 2},
        limits_map={"test-key-1": {"max_concurrent_calls": 5, "max_cps": 2, "cps_window_seconds": 1}},
    )

    assert "# TYPE comm_calls_total counter" in text
    assert "comm_calls_total 12" in text
    assert "comm_calls_active 3" in text
    assert 'comm_cps_current{api_key="test-key-1"} 2' in text
    assert 'comm_api_key_limit_max_concurrent{api_key="test-key-1"} 5' in text
    assert 'comm_api_key_limit_max_cps{api_key="test-key-1"} 2' in text
    assert 'comm_api_key_limit_cps_window_seconds{api_key="test-key-1"} 1' in text
