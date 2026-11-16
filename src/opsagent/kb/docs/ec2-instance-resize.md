---
title: Amazon EC2 - change the instance type
source_id: aws/ec2-instance-resize
url: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-resize.html
---

Excerpt, in our own words, of the EC2 User Guide page on changing the instance type of an existing instance.
Resizing is the usual durable fix when a workload has outgrown its instance rather than leaked memory.

## When resizing is the right fix

Changing the instance type moves the same root volume, data volumes, instance ID, private IP addresses, tags
and IAM role onto different hardware with more (or less) vCPU, memory or network capacity. It fixes memory
pressure only when the application legitimately needs more memory at its normal working set: steady growth that
plateaus, or a working set that grew with the dataset. It does not fix a leak; a leaking process will fill a
larger instance too, just more slowly. Check the memory trend first: if `mem_used_percent` climbs linearly
until a kill and resets, bound the service and fix the code. If it sits at a stable high level and the service is
being killed on spikes, resize.

## Requirements and restrictions

The instance must be EBS-backed; an instance-store-backed instance cannot be resized and has to be re-created
from an AMI. The new type must be compatible with the current one: same virtualization type (HVM), same
architecture (an x86 instance cannot become a Graviton `*g` instance without a new AMI), compatible networking
(ENA drivers must be installed for current-generation types, NVMe drivers for Nitro types), and the current
AMI must support the target. Staying within the same family and generation, for example `t3.medium` to
`t3.large` or `m6i.large` to `m6i.xlarge`, avoids almost all of these issues; the memory doubles with each size
step inside a family. Moving between families (for example `t3` to `m6i` for sustained CPU, or to `r6i` for
memory-heavy work) is allowed if the AMI and drivers support it. Instances in an Auto Scaling group should be
resized through the launch template instead, or the group will replace the instance with the old type.

## Procedure: stop, modify, start

1. Note the instance's current public IP if it is not an Elastic IP; it will change on start.
2. Stop the instance: `aws ec2 stop-instances --instance-ids <id>` and wait for `stopped`
   (`aws ec2 wait instance-stopped --instance-ids <id>`). A running instance cannot be modified.
3. Change the type: `aws ec2 modify-instance-attribute --instance-id <id> --instance-type "{\"Value\": \"t3.large\"}"`.
4. Start it: `aws ec2 start-instances --instance-ids <id>` and wait for `running` and for the status checks.
5. Confirm from inside: `free -m` or `grep MemTotal /proc/meminfo`, and check the service came back
   (`systemctl status <unit>`).

In the console the same steps are Instance state > Stop instance, then Actions > Instance settings > Change
instance type, then Start instance.

## Downtime and side effects

Stopping is a full shutdown of the guest OS, so the service is unavailable from the stop until the application
is up again, typically a few minutes. Anything in memory or on instance-store volumes is lost; EBS volumes
persist. The public IPv4 address changes unless an Elastic IP is attached. The instance may land on a
different physical host, and after a type change the operating system may renumber network interfaces or
NVMe device names. If a stop hangs, `--force` stops it without a clean shutdown. Billing switches to the new
type's rate when the instance starts.

## Reversal

Resizing is reversible by repeating the stop, modify, start sequence with the previous type. Record the old
type before the change so the rollback is a one-liner.
