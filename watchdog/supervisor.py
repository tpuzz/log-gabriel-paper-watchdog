#!/usr/bin/env python3
"""Bounded, fail-closed supervisor. It requests recovery; it never owns editorial work."""
import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

CAMPAIGN = "abelian-reconstruction-paper-revision-20261015-v1"
STALE_SECONDS = 1200
POLL_SECONDS = 60
ACK_TIMEOUT_SECONDS = 360
MAX_RECOVERY_ATTEMPTS = 3


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    mode: str = ""


def decide(hb, owner, now):
    """Public coordination only; the consumer verifies private authorization."""
    if not isinstance(hb, dict) or not isinstance(owner, dict):
        return Decision("wait", "Invalid state objects")
    if hb.get("campaign_id") != CAMPAIGN or owner.get("campaign_id") != CAMPAIGN:
        return Decision("wait", "Campaign mismatch")
    status = hb.get("status")
    if status in ("inactive", "cancelled", "canceled") or hb.get("user_stop_requested") is True:
        return Decision("stop", "Inactive or explicitly cancelled")
    delivered = (hb.get("terminal_delivery_complete") is True
                 and hb.get("dropbox_final_status_verified") is True)
    if status in ("completed", "paused", "expired", "interrupted", "blocked") and delivered:
        return Decision("stop", "Verified terminal delivery")
    if status == "paused" and hb.get("resume_authorized") is not True:
        return Decision("stop", "Deliberate pause does not authorize resumption")
    if status not in ("running", "checkpointed", "interrupted", "blocked", "completed", "expired"):
        return Decision("wait", "Unknown status")
    if status in ("running", "checkpointed") and hb.get("watchdog_recovery_armed") is not True:
        return Decision("wait", "Recovery not armed")
    run_id = hb.get("run_id")
    generation, previous_generation = owner.get("generation"), hb.get("lease_generation")
    if not isinstance(run_id, str) or not run_id or type(generation) is not int or type(previous_generation) is not int or min(generation, previous_generation) < 1:
        return Decision("wait", "Invalid run or generation")
    if owner.get("status") not in ("active", "inactive"):
        return Decision("wait", "Unknown lease status")
    try:
        lease_end = timestamp(owner.get("lease_expires_utc"))
        last = timestamp(hb.get("last_heartbeat_utc"))
    except (TypeError, ValueError, OverflowError):
        return Decision("wait", "Invalid timestamps")
    if last > now + timedelta(seconds=120):
        return Decision("wait", "Heartbeat is in the future")
    matches = owner.get("owner_run_id") == run_id and generation == previous_generation
    if not matches:
        orphan = (owner.get("status") == "active" and generation == previous_generation + 1
                  and owner.get("owner_run_id") not in (None, "", run_id)
                  and now >= lease_end and (now-last).total_seconds() >= STALE_SECONDS)
        if not orphan:
            return Decision("wait", "Conflicting state or handover in progress")
        return Decision("trigger", "Expired orphaned handover; independently verify", "verify_private_authorization")
    if now < lease_end:
        return Decision("wait", "Unexpired owner")
    if owner.get("status") == "inactive" and status in ("running", "checkpointed"):
        return Decision("wait", "Released ownership needs reconciliation")
    if status in ("running", "checkpointed") and (now-last).total_seconds() < STALE_SECONDS:
        return Decision("wait", "Heartbeat is fresh")
    mode = "finalize_only" if status in ("completed", "expired") or hb.get("recovery_mode") == "finalize_only" else "verify_private_authorization"
    return Decision("trigger", "Expired lease and stale or interrupted execution", mode)


class APIError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class GitHubAPI:
    def __init__(self, repo, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid repository identity")
        self.repo, self.token = repo, token

    def request(self, method, endpoint, payload=None, missing_ok=False):
        raw = None if payload is None else json.dumps(payload).encode()
        req = Request("https://api.github.com/repos/" + self.repo + endpoint,
                      data=raw, method=method,
                      headers={"Authorization": "Bearer " + self.token,
                               "Accept": "application/vnd.github+json",
                               "Content-Type": "application/json",
                               "X-GitHub-Api-Version": "2022-11-28",
                               "User-Agent": "log-gabriel-paper-watchdog"})
        try:
            with urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise APIError(error.code, "GitHub HTTP %d on %s %s: %s" %
                           (error.code, method, endpoint, error.read(1200).decode(errors="replace"))) from error

    def file(self, path, ref):
        record = self.request("GET", "/contents/" + path + "?" + urlencode({"ref": ref}))
        return json.loads(base64.b64decode(record["content"]).decode())

    def snapshot(self):
        sha = self.request("GET", "/git/ref/heads/main")["object"]["sha"]
        return sha, self.file("watchdog/heartbeat.json", sha), self.file("watchdog/owner.json", sha)


def incident_identity(hb, owner):
    value = "%s\0%s\0%s" % (CAMPAIGN, hb["run_id"], owner["generation"])
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def copy_dict(value):
    return json.loads(json.dumps(value))


def recovery_acknowledged(old_hb, old_owner, new_hb, new_owner, now):
    """A recovery request is successful only after a coherent successor generation is live."""
    if not isinstance(new_hb, dict) or not isinstance(new_owner, dict):
        return False
    if new_hb.get("campaign_id") != CAMPAIGN or new_owner.get("campaign_id") != CAMPAIGN:
        return False
    old_generation = old_owner.get("generation")
    new_generation = new_owner.get("generation")
    if type(old_generation) is not int or type(new_generation) is not int or new_generation <= old_generation:
        return False
    new_run = new_owner.get("owner_run_id")
    if not isinstance(new_run, str) or not new_run or new_run == old_hb.get("run_id"):
        return False
    if new_owner.get("status") != "active":
        return False
    if new_hb.get("run_id") != new_run or new_hb.get("lease_generation") != new_generation:
        return False
    if old_hb.get("authorization_id") and new_hb.get("authorization_id") != old_hb.get("authorization_id"):
        return False
    if old_hb.get("hard_deadline_utc") and new_hb.get("hard_deadline_utc") != old_hb.get("hard_deadline_utc"):
        return False
    if new_hb.get("status") not in ("running", "checkpointed", "interrupted", "blocked"):
        return False
    try:
        lease_end = timestamp(new_owner.get("lease_expires_utc"))
        last = timestamp(new_hb.get("last_heartbeat_utc"))
    except (TypeError, ValueError, OverflowError):
        return False
    if lease_end <= now or last > now + timedelta(seconds=120) or (now-last).total_seconds() >= STALE_SECONDS:
        return False
    return True


def emit_recovery(api, snapshot, decision, attempt=1):
    sha, hb, owner = snapshot
    incident = incident_identity(hb, owner)
    branch = "watchdog-recovery-" + incident + "-a" + str(attempt)
    query = urlencode({"state": "all", "head": api.repo.split("/")[0] + ":" + branch, "per_page": 100})
    existing = api.request("GET", "/pulls?" + query)
    if existing:
        print("Recovery signal already exists: " + existing[0]["html_url"], flush=True)
        return "done"
    marker_path = "watchdog/events/" + incident + "-a" + str(attempt) + ".json"
    marker = {"campaign_id": CAMPAIGN, "run_id": hb["run_id"],
              "lease_generation": owner["generation"], "incident_id": incident,
              "recovery_mode": decision.mode, "reason": decision.reason,
              "snapshot_commit": sha,
              "attempt": attempt}
    ref = api.request("GET", "/git/ref/heads/" + branch, missing_ok=True)
    if ref is None:
        commit = api.request("GET", "/git/commits/" + sha)
        tree = api.request("POST", "/git/trees", {"base_tree": commit["tree"]["sha"], "tree": [
            {"path": marker_path, "mode": "100644", "type": "blob", "content": json.dumps(marker, indent=2) + "\n"}]})
        new_commit = api.request("POST", "/git/commits", {"message": "Request log-gabriel-paper recovery " + incident,
                                  "tree": tree["sha"], "parents": [sha]})
        try:
            api.request("POST", "/git/refs", {"ref": "refs/heads/" + branch, "sha": new_commit["sha"]})
        except APIError as error:
            if error.status != 422:
                raise
            # A same-incident racer may have created the deterministic branch.
            api.request("GET", "/git/ref/heads/" + branch)
    saved_marker = api.file(marker_path, branch)
    if any(saved_marker.get(k) != marker[k] for k in ("campaign_id", "run_id", "lease_generation", "incident_id")):
        raise ValueError("Existing incident branch has conflicting provenance")
    fresh = api.snapshot()
    current = decide(fresh[1], fresh[2], datetime.now(timezone.utc))
    if current.action != "trigger" or incident_identity(fresh[1], fresh[2]) != incident:
        print("State advanced during preparation; no recovery PR opened", flush=True)
        return "changed"
    # Recompute mode: the delivery reserve/deadline may have arrived meanwhile.
    title = "LOG_GABRIEL_PAPER_STALE " + current.mode + " " + hb["run_id"] + " attempt-" + str(attempt)
    body = ("Recovery request only, not permission to skip checks.\n\n"
            + "Incident: `" + incident + "`; generation: `" + str(owner["generation"]) + "`; attempt: `" + str(attempt) + "`.\n"
            + "Requested mode: `" + current.mode + "`.\n"
            + "Verify the immutable authorization in private durable state before any work.\n\n"
            + "Read live GitHub ownership/heartbeat and the newest coherent Dropbox frontier. "
            + "Do not take over an unexpired or changed owner. Claim and verify the lease conditionally before any authorized work. "
            + "At or after the delivery reserve, or when recovery_mode is finalize_only, perform only reconciliation, "
            + "persistence and delivery of existing results: no new editorial rewriting, repeated gates, deadline extension or successor. "
            + "A hash or PASS attestation is not a replacement for missing proof/audit bytes; disclose missing artifacts. "
            + "Ignore this request if verified terminal delivery has since completed. "
            + "Re-arm a resumed execution only after publishing coherent ownership and heartbeats.\n")
    try:
        pr = api.request("POST", "/pulls", {"title": title, "body": body, "head": branch, "base": "main"})
    except APIError as error:
        if error.status != 422:
            raise
        found = api.request("GET", "/pulls?" + query)
        if not found:
            raise
        pr = found[0]
    print("Recovery PR created/verified: " + pr["html_url"], flush=True)
    return "done"



def emit_infrastructure_failure(api, snapshot, attempts):
    """Persist a visible alert if no recovery consumer acknowledges repeated wake-ups."""
    sha, hb, owner = snapshot
    incident = incident_identity(hb, owner)
    branch = "watchdog-recovery-failure-" + incident
    marker_path = "watchdog/events/" + incident + "-launch-failure.json"
    marker = {"campaign_id": CAMPAIGN, "run_id": hb["run_id"],
              "lease_generation": owner["generation"], "incident_id": incident,
              "attempts": attempts, "reason": "Recovery wake-ups were not acknowledged",
              "snapshot_commit": sha}
    query = urlencode({"state": "all", "head": api.repo.split("/")[0] + ":" + branch, "per_page": 100})
    existing = api.request("GET", "/pulls?" + query)
    if existing:
        print("Infrastructure-failure signal already exists: " + existing[0]["html_url"], flush=True)
        return
    ref = api.request("GET", "/git/ref/heads/" + branch, missing_ok=True)
    if ref is None:
        commit = api.request("GET", "/git/commits/" + sha)
        tree = api.request("POST", "/git/trees", {"base_tree": commit["tree"]["sha"], "tree": [
            {"path": marker_path, "mode": "100644", "type": "blob", "content": json.dumps(marker, indent=2) + "\n"}]})
        new_commit = api.request("POST", "/git/commits", {"message": "Record unacknowledged log-gabriel-paper recovery " + incident,
                                  "tree": tree["sha"], "parents": [sha]})
        try:
            api.request("POST", "/git/refs", {"ref": "refs/heads/" + branch, "sha": new_commit["sha"]})
        except APIError as error:
            if error.status != 422:
                raise
    title = "LOG_GABRIEL_PAPER_INFRA_FAILURE " + hb["run_id"]
    body = ("Automatic recovery was requested " + str(attempts) + " times but no coherent successor "
            "owner/heartbeat generation acknowledged the incident. No mathematical authorization is added. "
            "Inspect the ChatGPT recovery consumer; preserve the original deadline and scope.")
    try:
        pr = api.request("POST", "/pulls", {"title": title, "body": body, "head": branch, "base": "main"})
    except APIError as error:
        if error.status != 422:
            raise
        found = api.request("GET", "/pulls?" + query)
        if not found:
            raise
        pr = found[0]
    print("Infrastructure-failure PR created/verified: " + pr["html_url"], flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Evaluate once without waiting")
    parser.add_argument("--dry-run", action="store_true", help="Read/evaluate only; never mutate GitHub")
    args = parser.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    if repo != "tpuzz/log-gabriel-paper-watchdog":
        raise ValueError("This supervisor is restricted to the paper repository")
    api = GitHubAPI(repo, os.environ["GH_TOKEN"])
    failures, previous = 0, None
    stop_at = time.monotonic() + 355 * 60
    pending = None
    while time.monotonic() < stop_at:
        try:
            now = datetime.now(timezone.utc)
            snapshot = api.snapshot()

            if pending is not None:
                if recovery_acknowledged(pending["hb"], pending["owner"], snapshot[1], snapshot[2], now):
                    print("Recovery acknowledged by coherent successor generation %s run %s" %
                          (snapshot[2]["generation"], snapshot[2]["owner_run_id"]), flush=True)
                    return
                current_incident = incident_identity(snapshot[1], snapshot[2])
                if current_incident != pending["incident"]:
                    print("Incident state changed before acknowledgement; returning to supervision", flush=True)
                    pending = None
                    previous = None
                    continue
                if time.monotonic() >= pending["ack_deadline"]:
                    decision = decide(snapshot[1], snapshot[2], now)
                    if decision.action != "trigger":
                        print("Recovery no longer actionable while awaiting acknowledgement: " + decision.reason, flush=True)
                        pending = None
                        previous = None
                        continue
                    if pending["attempt"] >= MAX_RECOVERY_ATTEMPTS:
                        emit_infrastructure_failure(api, snapshot, pending["attempt"])
                        return
                    pending["attempt"] += 1
                    result = emit_recovery(api, snapshot, decision, pending["attempt"])
                    if result == "changed":
                        pending = None
                        previous = None
                        continue
                    pending["ack_deadline"] = time.monotonic() + ACK_TIMEOUT_SECONDS
                    print("Awaiting recovery acknowledgement after attempt %d" % pending["attempt"], flush=True)
                failures = 0
            else:
                decision = decide(snapshot[1], snapshot[2], now)
                if decision != previous:
                    print(json.dumps(decision.__dict__), flush=True)
                    previous = decision
                if args.dry_run or decision.action == "stop":
                    return
                if decision.action == "trigger":
                    result = emit_recovery(api, snapshot, decision, 1)
                    if result == "done":
                        pending = {"incident": incident_identity(snapshot[1], snapshot[2]),
                                   "hb": copy_dict(snapshot[1]), "owner": copy_dict(snapshot[2]),
                                   "attempt": 1,
                                   "ack_deadline": time.monotonic() + ACK_TIMEOUT_SECONDS}
                        print("Recovery request emitted; waiting for coherent successor acknowledgement", flush=True)
                    elif result == "changed":
                        previous = None
                failures = 0
        except (APIError, OSError, ValueError, KeyError) as error:
            failures += 1
            print("Supervisor check error (%d/3): %s" % (failures, error), file=sys.stderr, flush=True)
            if isinstance(error, APIError) and error.status in (401, 403):
                raise  # Permission failure is actionable, not an automatic retry loop.
            if failures >= 3 or args.once:
                raise
        if args.once:
            return
        time.sleep(POLL_SECONDS)
    raise RuntimeError("Supervisor timebox reached; no further monitoring was scheduled")


if __name__ == "__main__":
    main()
