"""Explicitly fetch four pinned, MIT-licensed upstream source subsets inside this repo."""

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path

PINS = {
    "agentdojo": ("ethz-spylab/agentdojo", "089ed468cf3ed0322acc66b0211f26d9d90dbf60", None),
    "injecagent": ("uiuc-kang-lab/InjecAgent", "f19c9f2c79a41046eb13c03c51a24c567a8ffa07", None),
    "msb": ("dongsenzhang/MSB", "c1d6a70171e4d2c44c87a2ae909d13df00c6aa8d", None),
    "tau3": ("sierra-research/tau2-bench", "fc0055dc4e0a316c3f83133267fbd6faaa770992", "v1.0.1"),
}
PATHS = {
    "agentdojo": ["/src/agentdojo/", "/README.md", "/LICEN*", "/pyproject.toml"],
    "injecagent": ["/src/", "/data/", "/requirements.txt", "/README.md", "/LICEN*"],
    "msb": [
        "/data/",
        "/config/",
        "/scripts/",
        "/metrics.py",
        "/agent_attack.py",
        "/main.py",
        "/requirements.txt",
        "/README.md",
        "/LICEN*",
    ],
    "tau3": [
        "/src/tau2/",
        "/data/tau2/domains/retail/",
        "/data/tau2/domains/mock/",
        "/docs/evaluation.md",
        "/pyproject.toml",
        "/README.md",
        "/LICEN*",
    ],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-download", action="store_true", required=True)
    args = parser.parse_args()
    if not args.enable_download:
        parser.error("Downloads require explicit enablement")
    root = Path(__file__).resolve().parents[1]
    parent = root / ".cache" / "p8-checkouts"
    parent.mkdir(parents=True, exist_ok=True)
    # Do not edit proxy/credential config; Git needs the system proxy on this host.
    proxies = urllib.request.getproxies()
    proxy = proxies.get("https") or proxies.get("http")
    command = ["git"] + (["-c", "http.proxy=" + proxy] if proxy else [])
    output = {}
    for name, (repo, commit, tag) in PINS.items():
        target = parent / name
        if target.exists():
            head = subprocess.run(
                ["git", "-C", str(target), "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            if head != commit:
                raise ValueError("Existing upstream version differs; no overwrite performed")
        else:
            clone = ["clone", "--filter=blob:none", "--depth", "1", "--no-checkout"]
            if tag:
                clone += ["--branch", tag]
            clone += ["https://github.com/" + repo + ".git", str(target)]
            for step in (
                clone,
                ["-C", str(target), "sparse-checkout", "set", "--no-cone", *PATHS[name]],
                ["-C", str(target), "checkout", commit],
            ):
                # Never display Git's proxy/auth diagnostics verbatim.
                process = subprocess.run(command + step, cwd=root, capture_output=True, timeout=180)
                if process.returncode:
                    raise RuntimeError("Pinned source fetch failed: " + name)
        output[name] = {"repository": repo, "commit": commit, "license": "MIT", "tag": tag}
    (root / "reports" / "generated" / "P8-upstream-pins.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print("Verified four pinned source checkouts; no upstream code executed")


if __name__ == "__main__":
    main()
