from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

import psutil

from ..models import HostMetrics
from .gpu import get_gpu_summary

log = logging.getLogger(__name__)


def _gb(x: float) -> float:
    return round(x / (1024 ** 3), 2)


def _mb(x: float) -> float:
    return round(x / (1024 ** 2), 1)


class HostMetricsProvider:
    def __init__(self, disk_path: str = "/", include_gpu: bool = True):
        self.disk_path = disk_path
        self.include_gpu = include_gpu

        # prime cpu percent to avoid first-call 0.0 on some systems
        psutil.cpu_percent(interval=None)

    def snapshot(self) -> HostMetrics:
        cpu = psutil.cpu_percent(interval=None)

        vm = psutil.virtual_memory()
        mem_used_gb = _gb(vm.used)
        mem_total_gb = _gb(vm.total)
        mem_percent = float(vm.percent)

        du = psutil.disk_usage(self.disk_path)
        disk_used_gb = _gb(du.used)
        disk_total_gb = _gb(du.total)
        disk_percent = float(du.percent)

        net = psutil.net_io_counters() or None
        if net is None:
            net_sent_mb = 0.0
            net_recv_mb = 0.0
        else:
            net_sent_mb = _mb(getattr(net, 'bytes_sent', 0))
            net_recv_mb = _mb(getattr(net, 'bytes_recv', 0))

        dio = psutil.disk_io_counters()
        disk_read_mb = _mb(dio.read_bytes) if dio else 0.0
        disk_write_mb = _mb(dio.write_bytes) if dio else 0.0

        gpu_summary: Optional[str] = None
        if self.include_gpu:
            gpu_summary = get_gpu_summary()

        return HostMetrics(
            cpu_percent=float(cpu),
            mem_used_gb=mem_used_gb,
            mem_total_gb=mem_total_gb,
            mem_percent=mem_percent,
            disk_used_gb=disk_used_gb,
            disk_total_gb=disk_total_gb,
            disk_percent=disk_percent,
            net_sent_mb=net_sent_mb,
            net_recv_mb=net_recv_mb,
            disk_read_mb=disk_read_mb,
            disk_write_mb=disk_write_mb,
            gpu_summary=gpu_summary,
        )
