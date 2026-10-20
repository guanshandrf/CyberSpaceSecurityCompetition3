"""Opt-in REAL DeepSeek tool smoke: at most 2 requests, no raw content/key logging."""

import argparse
import json
import logging
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-real-api", action="store_true", required=True)
    parser.parse_args(argv)
    # Optional demo imports stay outside the independent SDK and offline phase runner.
    import httpx
    from agentguard_demo.api import create_app
    from agentguard_demo.providers import make_provider
    from agentguard_demo.settings import DemoSettings
    from dotenv import dotenv_values
    from fastapi.testclient import TestClient

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    env_file = ROOT / ".env"
    if not key and env_file.is_file():
        if env_file.is_symlink() or not env_file.resolve().is_relative_to(ROOT):
            print("Refusing environment file outside the repository")
            return 3
        key = str(dotenv_values(env_file).get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        print("DeepSeek key missing; real API NOT_RUN. Configure it locally, never in chat.")
        return 3

    sandbox = ROOT / ".cache" / "deepseek-real-smoke" / uuid4().hex
    source = sandbox / "input"
    source.mkdir(parents=True)
    marker = "PUBLIC_AGENTGUARD_PROBE_" + uuid4().hex[:12]
    (source / "probe.txt").write_text(marker, encoding="utf-8")
    settings = DemoSettings(
        enable_baseline=True,
        provider="deepseek",
        enable_real_api=True,
        api_key=key,
        sandbox_root=sandbox,
        max_provider_calls=2,
        max_total_provider_calls=2,
        max_tokens=128,
    )
    requests, responses = [], []

    def request_hook(request):
        if (
            len(requests) >= 2
            or request.url.host != "api.deepseek.com"
            or request.url.scheme != "https"
        ):
            raise RuntimeError("Real smoke request boundary rejected")
        requests.append({"method": request.method, "path": request.url.path})

    def response_hook(response):
        item = {"status_code": response.status_code}
        response.read()
        try:
            usage = response.json().get("usage", {})
            item["usage"] = {
                name: usage[name]
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                if type(usage.get(name)) is int and usage[name] >= 0
            }
        except (ValueError, TypeError, AttributeError):
            pass
        responses.append(item)

    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with httpx.Client(
            timeout=15,
            trust_env=False,
            follow_redirects=False,
            event_hooks={"request": [request_hook], "response": [response_hook]},
        ) as client:
            # A normal, real HTTPX transport; no MockTransport, Fake LLM or patched API.
            provider = make_provider(settings, http_client=client)
            with TestClient(create_app(settings, provider=provider)) as api:
                session = api.post("/sessions").json()["session_id"]
                response = api.post(
                    f"/sessions/{session}/chat",
                    json={
                        "message": (
                            "Call read_file exactly once with path probe.txt. Do not guess its "
                            "contents and do not call write_note. After reading, reply only with "
                            "the file contents."
                        )
                    },
                )
                events = response.json().get("events", [])
                call_count = api.get(f"/sessions/{session}").json()["provider_calls"]
    except Exception:
        events, call_count = [], len(requests)
    finally:
        logging.disable(previous_logging)
    calls = [event["data"] for event in events if event["event"] == "tool_call"]
    results = [event["data"] for event in events if event["event"] == "tool_result"]
    messages = [event["data"]["content"] for event in events if event["event"] == "message"]
    checks = {
        "two_real_https_responses": len(responses) == 2
        and all(r["status_code"] == 200 for r in responses),
        "one_read_tool": len(calls) == 1 and calls[0]["name"] == "read_file",
        "matching_call_result": len(calls) == len(results) == 1
        and calls[0]["tool_call_id"] == results[0]["tool_call_id"],
        "sandbox_content_read": len(results) == 1
        and results[0]["result"] == {"ok": True, "content": marker},
        "final_reply_matches": len(messages) == 1 and messages[0].strip() == marker,
        "turn_completed": bool(events)
        and events[-1]["event"] == "done"
        and events[-1]["data"].get("ok") is True,
        "no_note_writes": not list((sandbox / "notes").rglob("*.*")),
    }
    result = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "provider": "deepseek",
        "model": "deepseek-chat",
        "real_transport": True,
        "max_requests": 2,
        "max_output_tokens_per_request": 128,
        "retries": 0,
        "provider_calls": call_count,
        "http_requests": requests,
        "http_responses": responses,
        "checks": checks,
        "conclusion": "PASS" if all(checks.values()) else "FAIL",
        "cost": "NOT_CALCULATED",
        "raw_content_saved": False,
    }
    destination = ROOT / "reports" / "generated" / "P1-deepseek-real.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["conclusion"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
