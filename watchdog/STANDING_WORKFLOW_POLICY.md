# Log Gabriel watchdog policy

This repository is shared coordination infrastructure for Log Gabriel workflows whose exact
`campaign_id` begins with `log-gabriel-`. The supervisor reads only its own public
`watchdog/heartbeat.json` and `watchdog/owner.json`. It never performs research or editorial
work, reads private storage, grants authorization, or changes a campaign clock.

A newly opened pull request whose title begins

`LOG_GABRIEL_WORKFLOW_STALE`

is only a recovery-verification wake-up. The exact campaign is carried by the coherent public
heartbeat/owner pair and by the incident marker. The recovery consumer must independently read the
newest coherent private durable state for that exact campaign before any takeover.

The supervisor is campaign-generic within the `log-gabriel-` family. It rejects mismatched
heartbeat/owner campaign IDs and all non-Log-Gabriel campaign IDs. This replaces the obsolete
single-campaign paper-revision binding.

The supervisor uses a 12-minute cooperative lease, a 20-minute stale threshold for silent
`running`/`checkpointed` executions, and one-minute polling. An explicit
`interrupted`/`blocked` status with an expired/released matching lease may request recovery
without waiting another 20 minutes. For silent `running`/`checkpointed` recovery, the decisive
public conditions are a heartbeat stale by at least 20 minutes and an expired matching lease;
the private recovery consumer still independently verifies authorization and scope before any work.

## Private authorization is authoritative

No start time, delivery reserve, hard deadline, extension, mathematical scope, or source path is
hard-coded in this public policy or in the recovery wake-up. The recovery consumer must read the
latest authoritative private authorization record (for example `AUTHORIZATION.json` and any
newer superseding state) every time it handles a wake-up.

A user-authorized extension updates the same campaign's effective clock only when it is actually
recorded in the newest coherent private state. The consumer must preserve the original start and
all elapsed work; it must not infer an extension from a PR or from this repository.

At or after the current private delivery reserve, only reconciliation, persistence, packaging and
delivery of already-produced work are permitted. At or after the current private hard deadline,
no substantive continuation is permitted without a newer explicit user authorization.

## Recovery acknowledgement and bounded retry

Signals are deduplicated by exact campaign, run, generation and attempt. An expired owner exactly
one generation ahead of an old heartbeat can be an orphaned handover; the consumer must still
inspect private state before any claim.

After a wake-up, the supervisor waits six minutes for a coherent successor owner/heartbeat under
the same campaign and authorization. At most three recovery requests are emitted for one incident.
If none is acknowledged, it emits one

`LOG_GABRIEL_WORKFLOW_INFRA_FAILURE`

alert. The supervisor never treats a PR as evidence that recovery succeeded.

A clean terminal state stops supervision only after both `terminal_delivery_complete` and
`dropbox_final_status_verified` are true. Deliberate pause or cancellation does not authorize
resumption. Clean shutdown persists/verifies the private final state before terminal flags and
conditionally releases ownership.
