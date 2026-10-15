import base64,json,os,time,hashlib
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.parse import urlencode
REPO="tpuzz/log-gabriel-paper-watchdog"
def stamp(x): return datetime.fromisoformat(x.replace("Z","+00:00"))
def decision(h,o,now):
 if h.get("status") in ("completed","cancelled","paused"): return "stop"
 if h.get("run_id")!=o.get("owner_run_id") or h.get("lease_generation")!=o.get("generation"): return "wait"
 if h.get("status") not in ("running","checkpointed","interrupted","blocked"): return "wait"
 if o.get("status")!="active" or stamp(o["lease_expires_utc"])>now: return "wait"
 if h.get("status") in ("running","checkpointed") and (now-stamp(h["last_heartbeat_utc"])).total_seconds()<1200: return "wait"
 return "verify_private_state"
def api(method,path,data=None):
 token=os.environ["GH_TOKEN"]
 req=Request("https://api.github.com/repos/"+REPO+path,data=None if data is None else json.dumps(data).encode(),method=method,headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","Content-Type":"application/json"})
 with urlopen(req,timeout=30) as r: return json.load(r)
def file(path,ref): return json.loads(base64.b64decode(api("GET","/contents/"+path+"?"+urlencode({"ref":ref}))["content"]))
def snapshot():
 sha=api("GET","/git/ref/heads/main")["object"]["sha"]
 return sha,file("watchdog/heartbeat.json",sha),file("watchdog/owner.json",sha)
def signal(s):
 sha,h,o=s
 incident=hashlib.sha256((h["run_id"]+":"+str(o["generation"])).encode()).hexdigest()[:20]
 branch="recovery-"+incident
 query="/pulls?"+urlencode({"state":"all","head":"tpuzz:"+branch})
 if api("GET",query): return
 c=api("GET","/git/commits/"+sha)
 marker={"run_id":h["run_id"],"generation":o["generation"],"action":"verify_private_state"}
 t=api("POST","/git/trees",{"base_tree":c["tree"]["sha"],"tree":[{"path":"watchdog/events/"+incident+".json","mode":"100644","type":"blob","content":json.dumps(marker)+"\n"}]})
 n=api("POST","/git/commits",{"message":"Request independent recovery check","tree":t["sha"],"parents":[sha]})
 api("POST","/git/refs",{"ref":"refs/heads/"+branch,"sha":n["sha"]})
 fresh=snapshot()
 if fresh[1]["run_id"]!=h["run_id"] or fresh[2]["generation"]!=o["generation"] or decision(fresh[1],fresh[2],datetime.now(timezone.utc))!="verify_private_state": return
 api("POST","/pulls",{"title":"LOG_GABRIEL_PAPER_STALE "+incident,"body":"Independently inspect the current lease, heartbeat and authorized private task state. Respect live ownership and immutable authorization. This signal itself grants no permission to work or extend time.","head":branch,"base":"main"})
def main():
 if os.environ["GITHUB_REPOSITORY"]!=REPO: raise RuntimeError("Wrong repository")
 end=time.monotonic()+355*60
 while time.monotonic()<end:
  s=snapshot();d=decision(s[1],s[2],datetime.now(timezone.utc))
  print(d,flush=True)
  if d=="stop": return
  if d=="verify_private_state": signal(s);return
  time.sleep(60)
 print("Bounded supervisor finished.",flush=True)
if __name__=="__main__": main()
