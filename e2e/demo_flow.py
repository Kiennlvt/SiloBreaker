"""Browser-level check of the judged path: Detect -> Capture -> approve -> OKF export.

Run with the API on :8000 and the Vite dev server on :5173:
    python e2e/demo_flow.py [screenshot_dir]
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None
ANSWER = json.loads((ROOT / "fixtures/oracle/expert_capture.json").read_text())["answer"]


def shot(page, name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1360, "height": 900})
    page.goto("http://localhost:5173")
    page.get_by_role("button", name="Reset demo").click()
    page.get_by_role("button", name="Start handoff and analyse").click()

    first = page.locator(".detect .finding").first
    expect(first.locator("h3")).to_have_text("Settlement recovery")
    expect(first.locator(".priority-num")).to_have_text("88")
    shot(page, "1-detect")

    first.get_by_role("button", name="Inspect").click()
    expect(page.locator(".evidence mark").first).to_be_visible()
    shot(page, "2-evidence")
    page.get_by_role("button", name="Close evidence").click()

    first.get_by_role("button", name="Review with expert").click()
    page.get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator(".question")).to_contain_text("stop and escalate")
    page.get_by_label("Expert answer, in your own words").fill(ANSWER)
    page.get_by_role("button", name="Structure my answer").click()
    expect(page.get_by_label("Stop and escalate 1")).not_to_have_value("")
    page.get_by_role("button", name="Save draft").click()
    page.get_by_role("button", name="Approve revision 1").click()
    expect(page.locator(".versions")).to_contain_text("v1")
    page.get_by_role("button", name="View OKF export").click()
    expect(page.locator(".okf pre")).to_contain_text("type: Operational Playbook")
    shot(page, "3-capture-okf")

    page.get_by_label("Analyse for").select_option("bob")
    expect(page.locator(".notice")).to_contain_text("No area qualifies")
    shot(page, "4-actor-change")
    browser.close()
print("e2e demo flow passed")
