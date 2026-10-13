"""Browser-level check of the judged 4-minute path (docs/09):

Detect -> Capture -> approve -> OKF -> generate + release exercise -> successor answers
unsafely (not_yet, per criterion) -> retries with a correct paraphrase (demonstrated) ->
actor change to Bob (no area qualifies).

Run with the API on :8000 and the Vite dev server on :5173:
    python e2e/demo_flow.py [screenshot_dir] [--runs N]

Set SB_E2E_BROWSER_CHANNEL=chrome (or msedge) to use an installed browser instead of the
Playwright-managed Chromium. Each run starts with "Reset demo".
"""

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "fixtures" / "oracle"
EXPERT_ANSWER = json.loads((ORACLE / "expert_capture.json").read_text())["answer"]
SUCCESSOR = json.loads((ORACLE / "successor_answers.json").read_text())

parser = argparse.ArgumentParser()
parser.add_argument("shots", nargs="?", type=Path)
parser.add_argument("--runs", type=int, default=1)
args = parser.parse_args()


def shot(page, run, name, element=None):
    """Full page, or one element: the side column scrolls on its own."""
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
        path = str(args.shots / f"run{run}-{name}.png")
        if element is not None:
            element.scroll_into_view_if_needed()
            element.screenshot(path=path)
        else:
            page.screenshot(path=path, full_page=True)


def demo(page, run):
    page.goto("http://localhost:5173")
    page.get_by_role("button", name="Reset demo").click()
    page.get_by_role("button", name="Start handoff and analyse").click()

    # Detect
    first = page.locator(".detect .finding").first
    expect(first.locator("h3")).to_have_text("Settlement recovery")
    expect(first.locator(".priority-num")).to_have_text("88")
    shot(page, run, "1-detect")
    first.get_by_role("button", name="Inspect").click()
    expect(page.locator(".evidence mark").first).to_be_visible()
    page.get_by_role("button", name="Close evidence").click()

    # Capture -> approve -> OKF
    first.get_by_role("button", name="Review with expert").click()
    page.get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator(".question")).to_contain_text("stop and escalate")
    page.get_by_label("Expert answer, in your own words").fill(EXPERT_ANSWER)
    page.get_by_role("button", name="Structure my answer").click()
    expect(page.get_by_label("Stop and escalate 1")).not_to_have_value("")
    page.get_by_role("button", name="Save draft").click()
    page.get_by_role("button", name="Approve revision 1").click()
    expect(page.locator(".versions")).to_contain_text("v1")
    page.get_by_role("button", name="View OKF export").click()
    expect(page.locator(".okf pre")).to_contain_text("type: Operational Playbook")
    expect(page.locator(".okf pre")).to_contain_text("status: active")
    shot(page, run, "2-capture-okf")

    # Verify: expert generates, reviews the private rubric and releases
    verify = page.locator(".verify")
    verify.get_by_role("button", name="Generate exercise").click()
    expect(verify.get_by_text("Private rubric")).to_be_visible()
    verify.get_by_role("button", name="Approve and release exercise").click()
    expect(verify).to_contain_text("released")
    shot(page, run, "3-exercise", verify)

    # Successor: the rubric is not in the page, the unsafe answer is not yet demonstrated
    verify.get_by_label("Successor (bob)").check()
    answer = verify.get_by_label("Your answer")
    expect(answer).to_be_visible()
    expect(verify).not_to_contain_text("rubric")
    expect(verify).not_to_contain_text("Critical")
    answer.fill(SUCCESSOR["unsafe"])
    verify.get_by_role("button", name="Submit answer").click()
    result = verify.locator(".result").first
    expect(result).to_have_text("Not yet demonstrated")
    expect(verify.locator(".verdict-unmet").first).to_be_visible()
    shot(page, run, "4-not-yet", verify)

    # Retry is a new attempt
    verify.get_by_role("button", name="Thử lại").click()
    verify.get_by_label("Your answer").fill(SUCCESSOR["correct_paraphrase"])
    verify.get_by_role("button", name="Submit answer").click()
    expect(result).to_have_text("Demonstrated in this exercise")
    expect(verify.get_by_text("Earlier attempts (1)")).to_be_visible()
    shot(page, run, "5-demonstrated", verify)

    # Actor change
    page.get_by_label("Analyse for").select_option("bob")
    expect(page.locator(".detect .notice")).to_contain_text("No area qualifies")
    shot(page, run, "6-actor-change")


with sync_playwright() as p:
    channel = os.environ.get("SB_E2E_BROWSER_CHANNEL") or None
    browser = p.chromium.launch(channel=channel)
    for run in range(1, args.runs + 1):
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        demo(page, run)
        page.close()
        print(f"run {run}/{args.runs} passed")
    browser.close()
print("e2e demo flow passed")
