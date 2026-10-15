# Watchdog policy
The supervisor is restricted to this repository. It reads only its own owner and heartbeat, checks for stale or interrupted execution, and emits a recovery-verification request. The consumer reads authorized private task state to decide whether resumption or finalization is permitted.

A newly opened pull request with title beginning LOG_GABRIEL_PAPER_STALE is a request to check, never permission to extend an authorization. The supervisor does not edit manuscript files, read private storage, or claim ownership. It uses a 12-minute cooperative lease, a 20-minute stale threshold for silent running, and one-minute polling.

The private task instructions govern every editorial action, immutable clock, checkpoint and delivery. Missing automation capability must be reported accurately. Completed, cancelled, or intentionally paused work is not restarted.
