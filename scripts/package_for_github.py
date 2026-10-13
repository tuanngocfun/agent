"""Package the reviewable project without runs, binaries or private state."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / name for name in ("README.md", "pyproject.toml", ".gitignore")]
    for folder in ("src", "tests", "scripts", "docs", "fixtures", ".github"):
        sources.extend(p for p in (ROOT / folder).rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"))
    sources = sorted(sources)
    inventory = []
    with zipfile.ZipFile(output / "kube-security-remediation.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            data = path.read_bytes()
            name = str(path.relative_to(ROOT))
            data.decode("utf-8")  # source-only publishing package; no model/binary blobs
            inventory.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            archive.writestr(name, data)
    plan = {"status": "prepared_not_published", "repository": None, "branch": "kube-remediation-demo",
            "effect": "Push publishes this source package and starts the exact-branch GitHub Actions worker",
            "merge": False, "private_runtime_state_included": False, "files": inventory}
    (output / "publish-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(output / "publish-plan.json")


if __name__ == "__main__":
    main()
