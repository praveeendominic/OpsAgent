---
title: Linux kernel OOM killer
source_id: linux/oom-killer
url: https://docs.kernel.org/admin-guide/mm/concepts.html
---

Excerpt, in our own words, of the kernel memory-management documentation (`admin-guide/mm/concepts`, "OOM
killer" section) and the classic *Understanding the Linux Virtual Memory Manager* chapter on out-of-memory
management (https://www.kernel.org/doc/gorman/html/understand/understand016.html).

## What the OOM killer is

Linux overcommits memory: a process may map more address space than the machine has RAM and swap, because most
allocations are never fully touched. The bill comes due when pages are actually written. If the kernel needs a
free page, has already reclaimed page cache and swapped out what it can, and still finds nothing, it cannot
return an error to the faulting process (the allocation succeeded long ago). Its only remaining option is to
free memory by terminating a process. That decision is the out-of-memory killer. It is not a bug and not an
application crash; it is the kernel protecting itself so the whole host does not deadlock.

## Reading "Out of memory: Killed process"

The kernel log (`dmesg`, `journalctl -k`) records each invocation. A typical line is

```
Out of memory: Killed process 1234 (python3) total-vm:4210000kB, anon-rss:3650000kB, file-rss:0kB, shmem-rss:0kB, UID:1000 pgtables:7400kB oom_score_adj:0
```

preceded by a memory state dump and a table of candidate tasks. `total-vm` is the full virtual size of the
process, including mapped files and untouched reservations, so it overstates real use. `anon-rss` is the
resident anonymous memory, essentially the heap and stacks, that cannot be dropped without swap; this is the
number that reflects what the process actually consumed and the one to compare with the instance's RAM.
`file-rss` is resident file-backed memory, which the kernel could have reclaimed, and `shmem-rss` is shared
memory. An `anon-rss` that grows between successive OOM events, with the same process name each time, is the
signature of a leak or an unbounded cache in that service. If the line says `Memory cgroup out of memory`
instead of plain `Out of memory`, the limit that was hit was a cgroup limit (for example systemd `MemoryMax=`),
not the machine's RAM.

## How a victim is chosen: oom_score and oom_score_adj

The killer computes a badness score for every eligible task, roughly the share of RAM plus swap the task uses,
and kills the one with the highest score; `/proc/<pid>/oom_score` exposes it. Administrators tilt the choice
with `/proc/<pid>/oom_score_adj`, an integer from -1000 to 1000 added to the percentage score. `-1000` makes a
process immune, `1000` makes it the first to go. systemd exposes this as `OOMScoreAdjust=` in the `[Service]`
section. Because the largest process is the most likely victim, the leaking service is usually the one killed,
but on a busy host the killer can take out an innocent large process such as a database while the real culprit
survives. Raising the culprit's `oom_score_adj` or giving it a cgroup limit removes that ambiguity.

## Why the kernel kills instead of letting the service fail gracefully

Memory is returned to a process when it first touches a page, deep inside a page fault, not when it calls
`malloc`. There is no error path at that point: the process is in the middle of an instruction. Delivering a
catchable signal would require the process to run, which needs memory it does not have. So the kernel sends
`SIGKILL`, which cannot be caught, ignored or delayed. From the service's point of view it simply stops; no
shutdown hook, logger flush or connection drain runs. This is why the application log goes silent while the
journal shows `code=killed, status=9/KILL`, and why the only way to get graceful behaviour is to bound memory
*before* the host runs out: a cgroup `memory.high` limit throttles first, an application-level cap on caches
and queues, or an instance with more RAM.

## Investigation checklist

`journalctl -k --since "-2h" | grep -E "Out of memory|oom-kill|Memory cgroup"` for the events;
`free -m` and `vmstat 1 5` for current pressure; `ps -eo pid,rss,comm --sort=-rss | head` for the biggest
residents; the CloudWatch agent's `mem_used_percent` for the slope that preceded the kill.
