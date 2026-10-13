"""Run a pinned CPU language model and the actual Kubernetes repair demo.

The model emits each agent action. There is no scripted decision fallback.
Public model weights live only in the disposable worker's local model cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ollama/ollama:0.6.8@sha256:50ab2378567a62b811a2967759dd91f254864c3495cbe50576bd8a85bc6edd56"
MODEL = "qwen2.5-coder:3b-instruct-q4_K_M"
MODEL_DIGEST = "sha256:f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225"
MODEL_LAYER = "sha256:4a188102020e9c9530b687fd6400f775c45e90a0d7baafe65bd0a36963fbb7ba"
BASE_IMAGE = "python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
NODE_IMAGE = "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"


def http(endpoint, method="GET", payload=None, timeout=15):
    request = urllib.request.Request(endpoint,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"}, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise RuntimeError("Model metadata response exceeds limit")
    return json.loads(raw)


def model_entry(tags):
    selected = next((m for m in tags["models"] if m.get("name") == MODEL or m.get("model") == MODEL), None)
    if not selected or canonical_digest(selected.get("digest")) != MODEL_DIGEST:
        raise RuntimeError("Actual model identity differs from the approved manifest digest")
    return selected


def canonical_digest(value):
    raw = str(value or "").removeprefix("sha256:")
    if len(raw) != 64 or any(c not in "0123456789abcdef" for c in raw):
        raise RuntimeError("Model has no valid SHA256 digest")
    return "sha256:" + raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    docker = shutil.which("docker")
    if not docker:
        parser.error("A dedicated Docker worker is required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cache = ROOT / ".tools" / ("ollama-cache-" + uuid.uuid4().hex[:8])
    cache.mkdir(parents=True, exist_ok=False)
    container = "kube-repair-llm-" + uuid.uuid4().hex[:12]
    commands = []
    created, success, error = False, False, None
    base_url = None

    def run(arguments, timeout=120):
        print("Executing:", str(arguments[0]), str(arguments[1]), flush=True)
        result = subprocess.run([str(a) for a in arguments], cwd=ROOT, capture_output=True, timeout=timeout)
        record = {"argv": [str(a) for a in arguments], "actual_exit": result.returncode,
                  "stdout": result.stdout.decode("utf-8", "replace")[-12000:],
                  "stderr": result.stderr.decode("utf-8", "replace")[-12000:]}
        commands.append(record)
        if result.returncode:
            detail = record["stderr"][-1500:] or record["stdout"][-1500:]
            raise RuntimeError("Worker command failed: " + detail)
        return record["stdout"] + (record["stderr"] if "logs" in arguments else "")

    try:
        # Downloads are authorized for this isolated job; all selected versions
        # are bound before inference and the workload is independently tested.
        for image in (IMAGE, NODE_IMAGE, BASE_IMAGE):
            run([docker, "pull", image], timeout=180)
        created = True
        run([docker, "run", "--detach", "--name", container, "--cpus=2", "--memory=4g", "--pids-limit=128",
             "--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp",
             "--cap-drop=ALL", "--security-opt=no-new-privileges=true", "--pull=never",
             "--publish", "127.0.0.1::11434", "--volume", str(cache) + ":/tmp/.ollama",
             "--env", "OLLAMA_NUM_PARALLEL=1", "--env", "OLLAMA_MAX_LOADED_MODELS=1",
             "--env", "OLLAMA_KEEP_ALIVE=30m", "--env", "OLLAMA_CONTEXT_LENGTH=8192",
             "--env", "OLLAMA_VULKAN=0", IMAGE], timeout=30)
        published = run([docker, "port", container, "11434/tcp"], timeout=10).strip()
        if not published.startswith("127.0.0.1:") or not published.split(":")[-1].isdigit():
            raise RuntimeError("Model listener must be bound only to loopback")
        base_url = "http://" + published
        for _ in range(60):
            try:
                version = http(base_url + "/api/version")
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.5)
        else:
            raise RuntimeError("Model server did not become available")
        run([docker, "exec", container, "ollama", "pull", MODEL], timeout=300)
        before = http(base_url + "/api/tags")
        selected = model_entry(before)
        blob = cache / "models" / "blobs" / MODEL_LAYER.replace(":", "-")
        checksum = hashlib.sha256()
        with blob.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
        if "sha256:" + checksum.hexdigest() != MODEL_LAYER:
            raise RuntimeError("Downloaded GGUF weight blob checksum mismatch")
        show = http(base_url + "/api/show", "POST", {"model": MODEL})
        warm = http(base_url + "/api/chat", "POST", {"model": MODEL, "messages": [], "stream": False,
                    "keep_alive": "30m", "options": {"num_ctx": 8192, "num_thread": 2}}, timeout=180)
        before_ps = http(base_url + "/api/ps")
        if not before_ps.get("models") or any(m.get("size_vram") != 0 for m in before_ps["models"]):
            raise RuntimeError("CPU-only model execution could not be confirmed")
        pin = {"model": MODEL, "model_digest": MODEL_DIGEST, "weight_blob_digest": MODEL_LAYER,
               "downloaded_weight_sha256_verified": True, "ollama_image": IMAGE, "ollama_version": version,
               "tags_before": before, "show": show, "warmup_response": warm, "ps_before": before_ps,
               "settings": {"temperature": 0, "num_ctx": 8192, "num_thread": 2},
               "weight_license": "Qwen Research License; weights are not published in this repository",
               "cpu_only": True, "selected_model": selected}
        (output / "model-pin.json").write_text(json.dumps(pin, indent=2) + "\n")
        run([sys.executable, "scripts/kind_demo.py", "--base-image", BASE_IMAGE, "--node-image", NODE_IMAGE,
             "--provider", "ollama", "--model", MODEL, "--endpoint", base_url,
             "--output", output / "kubernetes"], timeout=1050)
        report = json.loads((output / "kubernetes/results/agent/report.json").read_text())
        provider = report["provider"]
        if not (report["accepted"] and report["runtime_verified"] and provider.get("uses_llm") is True
                and provider.get("name") == "ollama" and canonical_digest(provider.get("model_revision")) == MODEL_DIGEST
                and provider["token_usage"]["reported_completion_tokens"] > 0):
            raise RuntimeError("The actual LLM-origin repair and Kubernetes verification were not established")
        after = http(base_url + "/api/tags")
        model_entry(after)
        after_ps = http(base_url + "/api/ps")
        if not after_ps.get("models") or any(m.get("size_vram") != 0 for m in after_ps.get("models", [])):
            raise RuntimeError("Unexpected accelerator use")
        pin.update({"tags_after": after, "ps_after": after_ps,
                    "model_digest_unchanged": True, "agent_provider": provider})
        (output / "model-pin.json").write_text(json.dumps(pin, indent=2) + "\n")
        success = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if created:
            try:
                logs = run([docker, "logs", "--tail=60", container], timeout=10)
                (output / "model-server.log").write_text(logs)
            except Exception:
                pass
            try:
                run([docker, "rm", "--force", container], timeout=15)
            except Exception as exc:
                success = False
                error = (error + "; " if error else "") + "Model container cleanup failed: " + str(exc)
        (output / "model-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        summary = {"status": "passed" if success else "failed", "provider": "ollama", "uses_llm": True,
                   "model": MODEL, "model_digest": MODEL_DIGEST, "cpu_only": True,
                   "backend": "kubernetes", "error": error, "model_cleanup_requested": created,
                   "claim": "Real model-generated actions on one synthetic workload with protected Kubernetes verification."}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
