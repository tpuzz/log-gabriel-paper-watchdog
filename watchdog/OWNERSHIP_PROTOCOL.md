# Cooperative ownership for this watchdog
This repository contains coordination infrastructure only. Read the authorized private task state for the task identity, source files, scope, immutable time limits and recovery frontier.

Before editing shared task artifacts, read owner.json with its current blob SHA. Respect every active unexpired lease. For an authorized initial claim or independently justified recovery, conditionally update the exact fetched SHA, increment generation, use a unique run ID, and set a 12-minute active lease. Read back and verify. A failed conditional update must not be retried blindly.

Renew approximately every five minutes using a freshly fetched SHA; verify readback before publishing a matching heartbeat. Recheck before publishing shared checkpoints and after long operations. A lease is cooperative, not a server-enforced fence on private storage.

For running/checkpointed state, request independent recovery verification only after a 20-minute stale heartbeat and expiry of the matching lease. For interrupted/blocked incomplete delivery, expiry is sufficient. A request is not proof that the old process has stopped. Never take over a fresh owner. The recovery consumer must read private state, preserve the original authorization and deadlines, and claim/read back a new lease before work.

At clean stop, privately persist and verify the deliverables, publish truthful terminal status, and conditionally release the lease. Explicit cancellation and completed delivery remain stopped. No deadline, scope, or private file path is stored in this protocol.
