"""Queue resource limits for the Gadi supercomputer (Australia)."""

from pbspy import QueueLimits, QueueLimitsMap

__all__ = ["gadi_queue_limits"]

gadi_queue_limits: QueueLimitsMap = {
    "normal": QueueLimits(cpus_per_node=48, max_mem_per_node=190, max_jobfs_per_node=400),
    "express": QueueLimits(cpus_per_node=48, max_mem_per_node=190, max_jobfs_per_node=400),
    "hugemem": QueueLimits(cpus_per_node=48, max_mem_per_node=1470, max_jobfs_per_node=1400),
    "megamem": QueueLimits(cpus_per_node=48, max_mem_per_node=2990, max_jobfs_per_node=1400),
    "gpuvolta": QueueLimits(cpus_per_node=12, max_mem_per_node=382, max_jobfs_per_node=400),
    "normalbw": QueueLimits(cpus_per_node=28, max_mem_per_node=256, max_jobfs_per_node=400),
    "expressbw": QueueLimits(cpus_per_node=28, max_mem_per_node=256, max_jobfs_per_node=400),
    "normalsl": QueueLimits(cpus_per_node=32, max_mem_per_node=192, max_jobfs_per_node=400),
    "hugemembw": QueueLimits(cpus_per_node=28, max_mem_per_node=1020, max_jobfs_per_node=390),
    "megamembw": QueueLimits(cpus_per_node=64, max_mem_per_node=3000, max_jobfs_per_node=800),
    "copyq": QueueLimits(cpus_per_node=1, max_mem_per_node=190, max_jobfs_per_node=400),
    "dgxa100": QueueLimits(cpus_per_node=16, max_mem_per_node=2000, max_jobfs_per_node=28000),
    "normalsr": QueueLimits(cpus_per_node=104, max_mem_per_node=500, max_jobfs_per_node=400),
    "expresssr": QueueLimits(cpus_per_node=104, max_mem_per_node=500, max_jobfs_per_node=400),
}
