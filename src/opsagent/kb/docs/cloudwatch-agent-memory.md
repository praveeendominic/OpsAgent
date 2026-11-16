---
title: CloudWatch agent memory metrics and alarms
source_id: aws/cloudwatch-agent-memory
url: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/metrics-collected-by-CloudWatch-agent.html
---

Excerpt, in our own words, of the CloudWatch documentation on the metrics the unified CloudWatch agent collects
on Linux, as it applies to memory monitoring and alarming.

## Why the agent is needed for memory

EC2 publishes CPU, disk I/O, network and status-check metrics from the hypervisor at no extra configuration.
Memory is not visible from outside the guest, so there is no `MemoryUtilization` metric by default. The
unified CloudWatch agent runs inside the instance, reads `/proc/meminfo`, and publishes memory metrics to the
`CWAgent` namespace (configurable). Without the agent a memory-related outage leaves no metric trail, only the
kernel log on the instance.

## Memory metrics collected

In the agent configuration the `mem` block selects which fields to publish. The relevant ones:

* `mem_used_percent` - percentage of physical memory in use, excluding buffers and cache; the primary signal
  for pressure. This is the metric to alarm on.
* `mem_available_percent` - percentage of memory available to start new applications without swapping,
  the complement of used memory plus reclaimable cache. Low values mean the kernel is about to reclaim or swap.
* `mem_used`, `mem_available`, `mem_free`, `mem_total`, `mem_cached`, `mem_buffered` - the same quantities in
  bytes. `mem_free` alone is misleading on Linux because the page cache uses free memory by design; prefer
  `mem_available`.
* `mem_active`, `mem_inactive` - recently and less recently used pages, useful for reclaim diagnostics.
* `swap_used_percent`, `swap_used`, `swap_free` - in the `swap` block; on instances without swap these stay at
  zero, so a rising `mem_used_percent` with zero swap means the next step is reclaim and then the OOM killer.

Each metric carries the dimensions configured in `append_dimensions` and `aggregation_dimensions`, typically
`InstanceId`, and optionally `InstanceType`, `AutoScalingGroupName` and `ImageId`.

## Collection interval

`metrics_collection_interval` (seconds) sets how often the agent samples; it can be set globally or per
metric block. The default is 60 seconds. Values below 60 produce high-resolution metrics, which cost more and
are only kept at full resolution for 3 hours, but let an alarm react in well under a minute. For a service
that leaks over hours, 60 seconds is enough; for one that goes from normal to OOM in two minutes, 10 or 30
seconds is needed for the alarm to fire before the kill. The agent buffers and sends in batches, so a short
interval does not mean one API call per sample. Configuration lives in
`/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`; apply a change with
`amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:<path> -s`.

## Alarms on memory

A CloudWatch alarm on `mem_used_percent` in the `CWAgent` namespace with the instance's dimensions is the
standard early warning. A common configuration is Statistic `Average`, Period 60 seconds, threshold 85 percent,
`GreaterThanThreshold`, and 3 of 3 datapoints to alarm, which filters single spikes. A second alarm at 95
percent with 1 datapoint gives a critical signal just before the OOM killer acts. Treat `INSUFFICIENT_DATA` on
a memory alarm as a problem in itself: it means the agent stopped publishing, which also happens when the
instance is so short of memory that the agent is killed or throttled. Alarm actions post to an SNS topic,
which is how OpsAgent receives the event.

Example CLI:

```
aws cloudwatch put-metric-alarm --alarm-name "<name>-mem-high" --namespace CWAgent \
  --metric-name mem_used_percent --dimensions Name=InstanceId,Value=<id> \
  --statistic Average --period 60 --evaluation-periods 3 --datapoints-to-alarm 3 \
  --threshold 85 --comparison-operator GreaterThanThreshold \
  --alarm-actions <sns-topic-arn> --treat-missing-data breaching
```

## Interpreting the curve after an OOM event

A sawtooth in `mem_used_percent`, rising to near 100 and dropping sharply at the moment the journal shows
`status=9/KILL`, is a leak-and-restart cycle; the period of the sawtooth is the leak rate. A step up that stays
flat after a deployment is a change in working set, which argues for a resize or a configuration cap rather
than a code fix.
