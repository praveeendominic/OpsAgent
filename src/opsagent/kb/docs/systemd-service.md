---
title: systemd.service - restart behaviour and exit status
source_id: systemd/service
url: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
---

Excerpt, in our own words, of the parts of `systemd.service(5)` and `systemd.unit(5)` that matter when a service
keeps dying and systemd keeps restarting it.

## Restart

`Restart=` in the `[Service]` section decides whether systemd starts the service again after its main process
exits. `no` (the default) never restarts. `on-success` restarts only on a clean exit. `on-failure` restarts on a
non-zero exit code, on a signal-induced death that is not a clean one, on a timeout, or when the watchdog fires.
`on-abnormal` is like `on-failure` but ignores non-zero exit codes. `on-abort` restarts only on uncaught signals.
`always` restarts no matter how the process ended, including a clean exit. A process killed by the kernel OOM
killer dies from `SIGKILL`, which counts as a failure, so both `on-failure` and `always` restart it. Exit codes
or signals listed in `RestartPreventExitStatus=` are excluded; `RestartForceExitStatus=` does the reverse.
Restarting hides a crash from users for a moment but does nothing about the cause: a service with a memory leak
restarts, grows, and is killed again on a cycle whose length is the leak rate.

## RestartSec

`RestartSec=` is the delay between the service stopping and the restart attempt. The default is 100 ms, which
is short enough that a crash loop can run many iterations per minute and flood the journal. A value of a few
seconds (`RestartSec=5`) is common for daemons. Newer systemd (v254+) adds `RestartSteps=` and
`RestartMaxDelaySec=` for an exponential back-off between those two values.

## Start rate limiting with StartLimitBurst

`StartLimitIntervalSec=` and `StartLimitBurst=` live in the `[Unit]` section and bound how often a unit may be
started: by default no more than 5 starts within 10 seconds. When the burst is exceeded, systemd refuses further
starts, logs `Start request repeated too quickly` and puts the unit in `failed` state until `systemctl
reset-failed <unit>` or the interval passes. Automatic restarts configured with `Restart=` count against this
limit, so a crash loop with the default 100 ms `RestartSec` will trip the limiter in about half a second and
leave the service down. Raising `RestartSec=` keeps a slowly dying service under the limit; setting
`StartLimitIntervalSec=0` disables the limiter entirely, which is rarely what you want.

## Reading "Main process exited, code=killed, status=9/KILL"

When the main process dies systemd logs a line of the form
`<unit>.service: Main process exited, code=<how>, status=<value>`. `code=exited` means the process called exit
and `status=` is its exit code. `code=killed` means it died from a signal and `status=` is the signal number and
name. `status=9/KILL` is `SIGKILL`: the process did not stop itself and could not catch or handle the signal.
Nothing inside the application produced this; something outside did. On a server the two usual senders are the
kernel OOM killer (look for `Out of memory: Killed process <pid>` or `Memory cgroup out of memory` in the kernel
log at the same timestamp) and an operator or supervisor sending `kill -9`. `status=15/TERM` by contrast is a
normal `systemctl stop`. After `code=killed` with `status=9` systemd records
`Failed with result 'signal'` and, if `Restart=` allows, `Scheduled restart job, restart counter is at N`. The
counter tells you how many times this has happened since the last manual start.

## Useful commands

`systemctl status <unit>` shows the last few journal lines, the active state and the memory line.
`journalctl -u <unit> --since "-1h"` gives the unit's own log; `journalctl -k --since "-1h" | grep -i -E
"out of memory|oom"` gives the kernel's side. `systemctl show <unit> -p NRestarts` prints the restart counter.
To stop a loop while investigating: `systemctl stop <unit>` then `systemctl reset-failed <unit>`.
