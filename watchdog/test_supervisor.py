import unittest
from datetime import datetime,timedelta,timezone
from supervisor import decision
class Tests(unittest.TestCase):
 def setUp(self):
  self.now=datetime.now(timezone.utc); self.h={"run_id":"x","lease_generation":1,"status":"running","last_heartbeat_utc":(self.now-timedelta(minutes=21)).isoformat()};self.o={"owner_run_id":"x","generation":1,"status":"active","lease_expires_utc":(self.now-timedelta(minutes=1)).isoformat()}
 def test_stale(self): self.assertEqual(decision(self.h,self.o,self.now),"verify_private_state")
 def test_fresh(self):
  self.h["last_heartbeat_utc"]=self.now.isoformat();self.assertEqual(decision(self.h,self.o,self.now),"wait")
 def test_live_owner(self):
  self.o["lease_expires_utc"]=(self.now+timedelta(minutes=1)).isoformat();self.assertEqual(decision(self.h,self.o,self.now),"wait")
 def test_conflict(self):
  self.o["generation"]=2;self.assertEqual(decision(self.h,self.o,self.now),"wait")
 def test_terminal(self):
  self.h["status"]="completed";self.assertEqual(decision(self.h,self.o,self.now),"stop")
if __name__=="__main__":unittest.main()
