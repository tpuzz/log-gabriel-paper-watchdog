import copy
import unittest
from datetime import datetime, timedelta, timezone
from supervisor import decide, recovery_acknowledged, incident_identity, CAMPAIGN


class RecoveryDecisions(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
        self.h = dict(campaign_id=CAMPAIGN, run_id="old-run", lease_generation=1,
                      status="running", watchdog_recovery_armed=True,
                      last_heartbeat_utc=(self.now-timedelta(minutes=21)).isoformat())
        self.o = dict(campaign_id=CAMPAIGN, owner_run_id="old-run", generation=1,
                      status="active", lease_expires_utc=(self.now-timedelta(minutes=1)).isoformat())

    def test_stale_and_expired(self):
        self.assertEqual(decide(self.h, self.o, self.now).action, "trigger")

    def test_live_owner_blocks_recovery(self):
        self.o["lease_expires_utc"] = (self.now+timedelta(minutes=1)).isoformat()
        self.assertEqual(decide(self.h, self.o, self.now).action, "wait")

    def test_fresh_heartbeat_blocks_recovery(self):
        self.h["last_heartbeat_utc"] = self.now.isoformat()
        self.assertEqual(decide(self.h, self.o, self.now).action, "wait")

    def test_conflicting_generation_blocks_recovery(self):
        self.o["generation"] = 4
        self.assertEqual(decide(self.h, self.o, self.now).action, "wait")

    def test_orphaned_handover_requires_expired_successor(self):
        self.o.update(generation=2, owner_run_id="successor")
        self.assertEqual(decide(self.h, self.o, self.now).action, "trigger")
        self.o["lease_expires_utc"] = (self.now+timedelta(minutes=1)).isoformat()
        self.assertEqual(decide(self.h, self.o, self.now).action, "wait")

    def test_interruption_uses_lease_without_stale_delay(self):
        self.h.update(status="interrupted", last_heartbeat_utc=self.now.isoformat())
        self.assertEqual(decide(self.h, self.o, self.now).action, "trigger")

    def test_terminal_delivery_is_verified(self):
        self.h.update(status="completed", terminal_delivery_complete=True)
        self.assertEqual(decide(self.h, self.o, self.now).mode, "finalize_only")
        self.h["dropbox_final_status_verified"] = True
        self.assertEqual(decide(self.h, self.o, self.now).action, "stop")

    def test_cancellation_and_pause(self):
        for status in ("cancelled", "paused"):
            self.h["status"] = status
            self.assertEqual(decide(self.h, self.o, self.now).action, "stop")

    def test_unknown_or_malformed_state_fails_closed(self):
        for field, value in (("campaign_id", "other"), ("last_heartbeat_utc", "bad"),
                             ("watchdog_recovery_armed", False), ("status", "unknown")):
            h = copy.deepcopy(self.h)
            h[field] = value
            self.assertEqual(decide(h, self.o, self.now).action, "wait")

    def test_ack_requires_coherent_fresh_successor(self):
        h, o = copy.deepcopy(self.h), copy.deepcopy(self.o)
        h.update(run_id="new-run", lease_generation=2, last_heartbeat_utc=self.now.isoformat())
        o.update(owner_run_id="new-run", generation=2,
                 lease_expires_utc=(self.now+timedelta(minutes=12)).isoformat())
        self.assertTrue(recovery_acknowledged(self.h, self.o, h, o, self.now))
        h["lease_generation"] = 1
        self.assertFalse(recovery_acknowledged(self.h, self.o, h, o, self.now))

    def test_incident_identity_changes_with_generation(self):
        first = incident_identity(self.h, self.o)
        self.o["generation"] += 1
        self.assertNotEqual(first, incident_identity(self.h, self.o))


if __name__ == "__main__":
    unittest.main()
