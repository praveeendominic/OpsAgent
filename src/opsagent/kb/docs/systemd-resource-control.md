---
title: systemd.resource-control - memory limits for units
source_id: systemd/resource-control
url: https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html
---

Excerpt, written in our own words, of the systemd resource-control manual as it applies to memory limits on
service units. Every setting below goes in the `[Service]` section (or `[Slice]` / `[Scope]`) of a unit file and
needs the unified cgroup v2 hierarchy, which is the default on current distributions.

## MemoryHigh

`MemoryHigh=` sets the throttling limit for the unit's cgroup. When the memory used by all processes in the
unit goes above this value the kernel does not kill anything; instead it reclaims memory aggressively and slows
the processes down (they spend time in direct reclaim). The limit can be exceeded, so it behaves as a soft cap
that keeps a leaking service from eating the whole machine while still letting it run. Values accept a size
suffix (`K`, `M`, `G`, `T`) or a percentage of physical memory, for example `MemoryHigh=1500M` or
`MemoryHigh=70%`. The special value `infinity` removes the limit. systemd maps this setting to the cgroup v2 file
`memory.high`. Because throttling is gradual it is the recommended primary memory control for most services; set
it below `MemoryMax=` so the unit is slowed before it is killed.

## MemoryMax

`MemoryMax=` is the hard limit, mapped to cgroup v2 `memory.max`. When the unit cannot stay under it after
reclaim, the kernel's OOM killer is invoked *inside the cgroup* and kills a process belonging to that unit. The
rest of the system is unaffected, which is the point: a bounded service fails on its own instead of forcing the
kernel to pick a victim across the whole host. Use the same size or percentage syntax as `MemoryHigh=`. The
usual pattern is `MemoryHigh=` at roughly 80-90 percent of `MemoryMax=`. When a process is killed this way
the journal shows the unit's main process exiting with `status=9/KILL` and the kernel log reports
`Memory cgroup out of memory`. Older unit files may still use `MemoryLimit=`, which is the deprecated cgroup v1
equivalent; replace it with `MemoryMax=`.

## MemorySwapMax

`MemorySwapMax=` caps how much swap the unit may use and maps to `memory.swap.max`. Setting it to `0` forbids
swap for the unit, which makes memory pressure show up as reclaim and OOM instead of as slow, swapping
behaviour. Setting it only makes sense when the host has swap configured at all; many EC2 images ship with no
swap, in which case the setting has no visible effect.

## MemoryAccounting

Memory accounting must be on for the limits to be enforced. `MemoryAccounting=yes` is the default through
`DefaultMemoryAccounting=` in `/etc/systemd/system.conf` on modern systemd (since v238). With accounting on,
`systemctl status <unit>` shows a `Memory:` line with the current usage and the configured `high`/`max`, and
`systemd-cgtop` shows per-unit consumption live.

## Drop-in files with systemctl edit

Never edit the vendor unit under `/usr/lib/systemd/system/` directly; it is overwritten on package upgrade.
Instead create a drop-in: `systemctl edit <unit>` opens an editor on
`/etc/systemd/system/<unit>.service.d/override.conf` and reloads the manager when you save. The file only needs
the section header and the keys you want to override:

```
[Service]
MemoryHigh=1500M
MemoryMax=1800M
```

Non-interactively, create the directory and file yourself, then run `systemctl daemon-reload`. Drop-ins are
merged over the original unit, so this is also the way to add a limit to a unit that had none. Remove the
override with `systemctl revert <unit>` or by deleting the drop-in directory and reloading.

## daemon-reload and restart

`systemctl daemon-reload` re-reads unit files and drop-ins but does not change running services. Memory limits
written to a cgroup attribute are applied to the live cgroup on the next `systemctl restart <unit>`; for most
memory settings systemd can also apply them without restart through `systemctl set-property <unit> MemoryMax=...`
which writes a drop-in in `/etc/systemd/system.control/` and updates the cgroup immediately. Use
`--runtime` with `set-property` for a change that should not survive reboot. After a change, verify with
`systemctl show <unit> -p MemoryHigh -p MemoryMax` and `cat /sys/fs/cgroup/system.slice/<unit>.service/memory.max`.
