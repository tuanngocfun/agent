"""Capture actual dashboard views of saved model runs without loading credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--results", type=Path, default=Path("output/visual-run-20261025"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    results = args.results.resolve()
    output = (args.output or results / "screenshots").resolve()
    output.mkdir(parents=True, exist_ok=True)
    browser_env = dict(os.environ)
    if (root / ".cache/browsers").exists():
        browser_env["PLAYWRIGHT_BROWSERS_PATH"] = str(root / ".cache/browsers")
        # Playwright resolves the executable in its driver before browser launch.
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browser_env["PLAYWRIGHT_BROWSERS_PATH"]
    libraries = root / ".cache/browser-libs/usr/lib/x86_64-linux-gnu"
    if libraries.exists():
        browser_env["LD_LIBRARY_PATH"] = str(libraries) + (
            ":" + browser_env["LD_LIBRARY_PATH"] if browser_env.get("LD_LIBRARY_PATH") else ""
        )
    errors: list[str] = []
    receipts = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            env=browser_env,
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1300}, device_scale_factor=2)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until="load")
        expect(page.locator("#token")).to_have_value("")

        def load(name: str) -> None:
            page.locator("#saved").set_input_files(str(results / name))
            expect(page.locator("#status")).to_contain_text("Loaded saved experiment")

        def print_size_plot(selector: str) -> None:
            page.locator(selector + " .main-svg").first.wait_for(state="visible")
            page.evaluate(
                """async selector => {
                    const el = document.querySelector(selector);
                    await Plotly.relayout(el, {
                      'font.size': 14, 'legend.font.size': 13,
                      'xaxis.tickfont.size': 13, 'yaxis.tickfont.size': 13,
                      'margin.l': 80, 'margin.t': 55,
                      'legend.y': 1.16
                    });
                }""",
                selector,
            )

        def receipt(name: str, sources: list[str], details: dict) -> None:
            target = output / name
            receipts.append({
                "file": name,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "sources": {
                    item: hashlib.sha256((results / item).read_bytes()).hexdigest()
                    for item in sources
                },
                **details,
            })

        load("forecast.json")
        print_size_plot("#fan")
        top = page.locator(".stat-grid").bounding_box()
        bottom = page.locator(".chart-panel").bounding_box()
        assert top and bottom
        clip = {"x": top["x"], "y": top["y"], "width": top["width"],
                "height": bottom["y"] + bottom["height"] - top["y"]}
        page.screenshot(path=str(output / "forecast-dashboard.png"), clip=clip)
        forecast = json.loads((results / "forecast.json").read_text())
        expect(page.locator("#sample-count")).to_contain_text(
            f"{len(forecast['trajectories'])} sample paths"
        )
        receipt("forecast-dashboard.png", ["forecast.json"], {
            "view": "summary cards and retained-path fan",
            "settings": forecast["metadata"]["config"],
        })

        load("evaluation.json")
        expect(page.locator("#evaluation-panel")).to_be_visible()
        expect(page.locator("#metrics tr")).to_have_count(6)
        print_size_plot("#window-chart")
        evaluation = json.loads((results / "evaluation.json").read_text())
        selected = int(page.locator("#window").input_value())
        assert evaluation["per_window"][selected]["split"] == "test"
        page.locator("#evaluation-panel").screenshot(path=str(output / "evaluation-dashboard.png"))
        receipt("evaluation-dashboard.png", ["evaluation.json"], {
            "view": "all test-window aggregate metrics and first chronological test window",
            "selected_origin": evaluation["per_window"][selected]["origin_index"],
            "test_windows": evaluation["metrics"]["model_raw"]["windows"],
        })

        load("comparison.json")
        expect(page.locator("#comparison-panel")).to_be_visible()
        print_size_plot("#comparison-chart")
        page.locator("#comparison-panel").screenshot(path=str(output / "comparison-dashboard.png"))
        receipt("comparison-dashboard.png", ["comparison.json"], {
            "view": "latest paired forward paths; Kronos mean and Chronos native median",
        })
        expect(page.locator("#token")).to_have_value("")
        browser.close()
    if errors:
        raise AssertionError(errors)
    (output / "capture-manifest.json").write_text(json.dumps({
        "dashboard_url": args.url,
        "method": "fresh native model exports loaded by the unmodified dashboard saved-result UI",
        "presentation": "1440px desktop, 2x raster, chart labels enlarged for print; data unmodified",
        "credentials_loaded": False,
        "javascript_errors": errors,
        "captures": receipts,
    }, indent=2) + "\n")
    print(f"Captured {len(receipts)} dashboard views; no credentials loaded; no JavaScript errors")


if __name__ == "__main__":
    main()
