# Watchdog policy
The supervisor is restricted to this repository. It reads only its own owner and heartbeat, checks for stale or interrupted execution, and emits a recovery-verification request. The consumer reads authorized private task state to decide whether resumption or finalization is permitted.

A newly opened pull request with title beginning LOG_GABRIEL_PAPER_STALE is a request to check, never permission to extend an authorization. The supervisor does not edit manuscript files, read private storage, or claim ownership. It uses a 12-minute cooperative lease, a 20-minute stale threshold for silent running, and one-minute polling.

The private task instructions govern every editorial action, immutable clock, checkpoint and delivery. Missing automation capability must be reported accurately. Completed, cancelled, or intentionally paused work is not restarted.

## Recovery acknowledgement and bounded retry
Signals are deduplicated by campaign, run, generation and attempt. An expired owner exactly one generation ahead of an old heartbeat can be an orphaned handover; independently inspect private state before any claim. After a request, wait six minutes for a fresh coherent successor owner and heartbeat. At most three requests are emitted for an incident; then emit one LOG_GABRIEL_PAPER_INFRA_FAILURE alert. The supervisor never grants new authorization. The private recovery consumer alone checks immutable start, delivery reserve and hard deadline before choosing permitted work.

A completed/expired status with unverified delivery requests finalization only. Stop after terminal_delivery_complete and dropbox_final_status_verified are both true. Deliberate pause or cancellation does not authorize resumption. Clean shutdown publishes and verifies private final state before terminal flags, then releases the existing owner conditionally.
