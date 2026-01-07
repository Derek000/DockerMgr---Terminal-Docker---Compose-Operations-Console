from dockermgr.utils.system_metrics import HostMetricsProvider


def test_metrics_snapshot_has_fields():
    m = HostMetricsProvider(include_gpu=False)
    snap = m.snapshot()
    assert snap.mem_total_gb > 0
    assert 0.0 <= snap.cpu_percent <= 100.0
