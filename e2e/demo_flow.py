"""Browser-level check of the demo path on the multi-page, signed-in website (docs/09):

admin: sign in -> Reset demo -> handoff Alice -> Bob -> run analysis -> log out
alice: sign in -> Settlement 88 -> Confirm -> answer -> Save draft -> Approve -> OKF ->
       generate + release exercise -> log out
bob:   sign in -> /learn -> unsafe answer (Not yet demonstrated) -> Try again with a correct
       paraphrase (Demonstrated) -> /admin shows 403 -> log out
admin: sign in -> /admin/audit shows actions by all three

Run with the API on :8000 (demo accounts seeded: python -m app.seed_users) and the Vite dev
server on :5173:
    python e2e/demo_flow.py [screenshot_dir] [--runs N]

Set SB_E2E_BROWSER_CHANNEL=chrome (or msedge) to use an installed browser instead of the
Playwright-managed Chromium. Each run uses a fresh browser context and starts with Reset demo.
"""

import argparse
import json
import os
import re
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = os.environ.get("SB_E2E_BASE_URL", "http://localhost:5173")
ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "fixtures" / "oracle"
EXPERT_ANSWER = json.loads((ORACLE / "expert_capture.json").read_text())["answer"]
SUCCESSOR = json.loads((ORACLE / "successor_answers.json").read_text())
# Demo-only accounts created by `python -m app.seed_users`.
ACCOUNTS = {"admin": "Admin@123", "alice": "Alice@123", "bob": "Bob@123"}

parser = argparse.ArgumentParser()
parser.add_argument("shots", nargs="?", type=Path)
parser.add_argument("--runs", type=int, default=1)
args = parser.parse_args()


def shot(page: Page, run: int, name: str) -> None:
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.shots / f"run{run}-{name}.png"), full_page=True)


def at(page: Page, path: str) -> None:
    """Client-side routes change the URL without a page load, so poll the URL."""
    expect(page).to_have_url(re.compile("^" + re.escape(BASE) + path + "$"))


def nav(page: Page, label: str) -> None:
    page.get_by_role("navigation", name="Main").get_by_role("link", name=label, exact=True).click()


def login(page: Page, user: str) -> None:
    page.goto(f"{BASE}/login")
    page.get_by_label("Username").fill(user)
    page.get_by_label("Password").fill(ACCOUNTS[user])
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("button", name="Log out")).to_be_visible()


def logout(page: Page) -> None:
    page.get_by_role("button", name="Log out").click()
    at(page, "/login")


def admin_setup(page: Page, run: int) -> None:
    login(page, "admin")
    at(page, "/admin")
    nav(page, "Handoffs")
    at(page, "/admin/handoffs")
    page.get_by_role("button", name="Reset demo").click()  # confirm dialog is accepted
    expect(page.get_by_text("No handoffs yet.")).to_be_visible(timeout=30_000)
    page.get_by_label("Experienced engineer (must appear in the evidence)").select_option("alice")
    page.get_by_label("Successor (any active member)").select_option("bob")
    page.get_by_role("button", name="Create handoff").click()
    page.get_by_role("button", name="Run analysis").click()
    at(page, "/expert/handoffs/[^/]+/detect")
    expect(page.get_by_role("article", name="Settlement recovery")).to_be_visible()
    # The admin reads results but cannot capture.
    expect(page.get_by_role("button", name="Review with expert")).to_have_count(0)
    shot(page, run, "1-admin-detect")
    logout(page)


def expert_capture(page: Page, run: int) -> None:
    login(page, "alice")
    at(page, "/expert")
    page.get_by_role("link", name="Open Detect").click()
    first = page.locator(".detect .finding").first
    expect(first.locator("h3")).to_have_text("Settlement recovery")
    expect(first.locator(".priority-num")).to_have_text("88")
    expect(
        first.get_by_role("img", name="Raw score 87.5 of 100, review priority 88")
    ).to_be_visible()
    expect(first.locator("svg.signal-bar")).to_have_count(5)
    first.get_by_role("button", name="Inspect").click()
    expect(page.locator(".evidence mark").first).to_be_visible()
    page.get_by_role("button", name="Close evidence").click()
    shot(page, run, "2-expert-detect")

    first.get_by_role("button", name="Review with expert").click()
    at(page, "/expert/findings/[^/]+")
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
    shot(page, run, "3-capture-okf")

    page.get_by_role("link", name="Open exercise for v1").click()
    at(page, "/expert/knowledge/[^/]+/exercise")
    verify = page.locator(".verify")
    verify.get_by_role("button", name="Generate exercise").click()
    expect(verify.get_by_text("Private rubric")).to_be_visible()
    verify.get_by_role("button", name="Approve and release exercise").click()
    expect(verify).to_contain_text("released")
    shot(page, run, "4-exercise")
    logout(page)


def successor_answers(page: Page, run: int) -> None:
    login(page, "bob")
    at(page, "/learn")
    page.get_by_role("link", name="Start").click()
    at(page, "/learn/exercises/[^/]+")
    verify = page.locator(".verify")
    answer = verify.get_by_label("Your answer")
    expect(answer).to_be_visible()
    expect(verify).not_to_contain_text("rubric")
    expect(verify).not_to_contain_text("Critical")
    answer.fill(SUCCESSOR["unsafe"])
    verify.get_by_role("button", name="Submit answer").click()
    result = verify.locator(".result").first
    expect(result).to_have_text("Not yet demonstrated")
    expect(verify.locator(".verdict-unmet").first).to_be_visible()
    shot(page, run, "5-not-yet")

    verify.get_by_role("button", name="Try again").click()
    verify.get_by_label("Your answer").fill(SUCCESSOR["correct_paraphrase"])
    verify.get_by_role("button", name="Submit answer").click()
    expect(result).to_have_text("Demonstrated in this exercise")
    expect(verify.get_by_text("Earlier attempts (1)")).to_be_visible()
    shot(page, run, "6-demonstrated")

    page.goto(f"{BASE}/admin")
    at(page, "/403")
    expect(page.get_by_role("heading", name="You do not have access to this page")).to_be_visible()
    logout(page)


def admin_audit(page: Page, run: int) -> None:
    login(page, "admin")
    nav(page, "Audit log")
    at(page, "/admin/audit")
    actors = page.locator("table.data tbody tr td:nth-child(2)")
    expect(actors.first).to_be_visible()
    seen = set(actors.all_inner_texts())
    assert {"admin", "alice", "bob"} <= seen, f"audit actors on the first page: {sorted(seen)}"
    # Each person's own actions, through the actor filter.
    for actor, action in (
        ("admin", "handoff.created"),
        ("alice", "knowledge.approved"),
        ("bob", "attempt.submitted"),
    ):
        page.get_by_label("Actor").fill(actor)
        page.get_by_role("button", name="Apply filters").click()
        expect(page.locator("table.data tbody")).to_contain_text(action)
        expect(
            page.locator("table.data tbody tr td:nth-child(2)").filter(has_not_text=actor)
        ).to_have_count(0)
    shot(page, run, "7-audit")
    logout(page)


with sync_playwright() as p:
    channel = os.environ.get("SB_E2E_BROWSER_CHANNEL") or None
    browser = p.chromium.launch(channel=channel)
    for run in range(1, args.runs + 1):
        context = browser.new_context(viewport={"width": 1360, "height": 900})
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())
        admin_setup(page, run)
        expert_capture(page, run)
        successor_answers(page, run)
        admin_audit(page, run)
        context.close()
        print(f"run {run}/{args.runs} passed")
    browser.close()
print("e2e demo flow passed")
