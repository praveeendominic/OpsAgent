---
title: cgroup v2 memory controller
source_id: linux/cgroup-v2-memory
url: https://docs.kernel.org/admin-guide/cgroup-v2.html#memory
---

Excerpt, in our own words, of the memory section of the kernel's cgroup v2 administration guide. systemd's
`MemoryHigh=`, `MemoryMax=` and `MemorySwapMax=` are front ends for the files described here, so this is the
mechanism behind a unit's limits.

## What the controller accounts

The memory controller tracks, per cgroup, anonymous memory (heap, stacks), page cache and tmpfs/shmem, kernel
data structures such as dentries and inodes attributed to the group, and socket buffers. Usage is charged to
the cgroup of the process that first touched the page and stays there until the page is freed. Each unit that
systemd runs gets its own cgroup under `/sys/fs/cgroup/system.slice/<unit>.service/`, which is where the
control files below live; `memory.current` in that directory is the live usage in bytes and `memory.stat`
breaks it down (`anon`, `file`, `kernel`, `shmem`, and so on).

## memory.high

`memory.high` is the throttle limit. When the group's usage goes over it the kernel does not kill; it puts the
group under heavy reclaim pressure and, if usage keeps rising, makes the allocating processes sleep in
proportion to how far over they are. The effect is a service that gets slower rather than one that dies, and
usage may stay somewhat above `memory.high` for a while. The documentation recommends it as the main mechanism
for controlling a group's memory because the failure mode is degradation that monitoring can see, not a hard
stop. `memory.events` in the same directory counts `high` (how many times the limit was exceeded) so you can
tell whether throttling has been happening. The value is bytes or `max` for no limit.

## memory.max

`memory.max` is the hard limit. When usage reaches it and reclaim cannot bring it down, the kernel invokes the
OOM killer *restricted to this cgroup*: a process inside the group is killed, chosen by the same badness score
as a system-wide OOM, and the kernel log says `Memory cgroup out of memory: Killed process ...`. Processes in
other groups are untouched. The `oom_kill` counter in `memory.events` increments and `memory.events` also has
a `max` counter for how often the limit was hit. Because a cgroup OOM is contained, `memory.max` is what turns
"the host ran out of memory and the kernel shot something" into "this one service hit its budget and
restarted". Set it with headroom below the instance's RAM minus what the rest of the system needs, and set
`memory.high` a little under it so throttling gives a warning first.

## Throttling versus OOM

The two limits are designed to be used together. Below `memory.high` the group runs normally. Between
`memory.high` and `memory.max` it is throttled and reclaimed; a steady leak will cross this band more slowly
and your metrics will show the service as slow and its memory as flat near the high mark. At `memory.max` the
group's OOM killer fires. A group with only `memory.max` goes from fine to killed with no warning; a group
with only `memory.high` can still, under a fast leak, outrun the throttling and push the host into a global
OOM. On a machine whose RAM is mostly for one service the practical recipe is `memory.high` at about 80 percent
of what the service may use and `memory.max` at 90 percent, leaving the remainder for the OS, the agent and
the page cache.

## memory.swap.max and memory.oom.group

`memory.swap.max` caps swap used by the group (systemd `MemorySwapMax=`); `0` disables swap for it.
`memory.oom.group`, when set to 1, makes a cgroup OOM kill every process in the group instead of one, which is
what you want for a service whose workers cannot run without their parent (systemd: `OOMPolicy=kill` is the
related unit-level setting, applied by systemd rather than the kernel).

## Inspecting the live state

```
cat /sys/fs/cgroup/system.slice/<unit>.service/memory.current
cat /sys/fs/cgroup/system.slice/<unit>.service/memory.high
cat /sys/fs/cgroup/system.slice/<unit>.service/memory.max
cat /sys/fs/cgroup/system.slice/<unit>.service/memory.events
```

`systemd-cgtop -m` sorts all units by memory, which quickly shows which cgroup owns the growth.
