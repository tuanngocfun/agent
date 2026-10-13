"""Install checksum-verified pinned demo tools under the project on a CI worker."""
import hashlib
import os
from pathlib import Path
import platform
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "kind": ("https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/kind-linux-amd64",
             "https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/kind-linux-amd64.sha256sum"),
    "kubectl": ("https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl",
                "https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl.sha256"),
}


def fetch(url, limit):
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Tool download exceeds limit")
    return data


def main():
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise RuntimeError("This pinned worker setup supports Linux AMD64 only")
    directory = ROOT / ".tools" / "bin"
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum_url) in TOOLS.items():
        expected = fetch(checksum_url, 4096).decode().split()[0]
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise RuntimeError("Official checksum has an unexpected format")
        data = fetch(url, 100 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("Official tool checksum mismatch: " + name)
        temporary = directory / (name + ".download")
        temporary.write_bytes(data)
        temporary.chmod(0o755)
        temporary.replace(directory / name)
    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with open(github_path, "a", encoding="utf-8") as stream:
            stream.write(str(directory) + "\n")
    print("Pinned tools installed:", directory)


if __name__ == "__main__":
    main()
