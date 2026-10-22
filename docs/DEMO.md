# SiloBreaker — five-minute demo

A scripted walk through the signed-in website: an administrator sets up a handoff, the
experienced engineer captures missing knowledge, the successor proves they can use it, and the
audit log shows who did what. The same path is automated in `e2e/demo_flow.py`.

## Before you start

```bash
docker compose up -d db
cd backend && alembic upgrade head && python -m app.seed_users && uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

Open http://localhost:5173/login. Demo accounts (passwords for this demo only):

| Username | Password | Plays |
|---|---|---|
| `admin` | `Admin@123` | administrator |
| `alice` | `Alice@123` | experienced engineer handing over |
| `bob` | `Bob@123` | successor |

Each step below lists **what to click or type**, **what you should see**, and **why it matters**.

---

## 1. Administrator sets up the handoff (≈ 1 min)

| # | Do | You see |
|---|---|---|
| 1.1 | Sign in as `admin` / `Admin@123`, click **Sign in**. | The **Administration** overview with account and handoff counts. The header shows *Admin · Administrator*. |
| 1.2 | Click **Handoffs** in the menu, then **Reset demo**, and confirm the dialog. | The evidence bundle `payment-platform` with its source inventory, and *No handoffs yet.* |
| 1.3 | In **Experienced engineer (must appear in the evidence)** choose *Alice Tran*; in **Successor (any active member)** choose *Bob Nguyen*. Click **Create handoff**. | The handoff *Alice Tran → Bob Nguyen* appears under **All handoffs**. |
| 1.4 | Click **Run analysis**. | The Detect page for the handoff, with ranked candidates. There is no **Review with expert** button. |
| 1.5 | Click **Log out**. | The sign-in page. |

**Why it matters:** the administrator can set up work and read every result, but cannot review or
approve knowledge. Approval belongs to the person who has the knowledge (separation of duties).
The successor list accepts any active member, so a new hire from outside the project can be the
successor even though they appear nowhere in the evidence.

## 2. Experienced engineer captures the missing knowledge (≈ 2 min)

| # | Do | You see |
|---|---|---|
| 2.1 | Sign in as `alice` / `Alice@123`. | **My handoffs**, listing *payment-platform · successor bob*. |
| 2.2 | Click **Open Detect**. | **Settlement recovery** on top with review priority **88**, a stacked bar *Raw 87.5 → priority 88* and five signal bars. **Webhooks recovery** shows **60** with a red dashed line and *Capped at 60*, plus the two reasons. |
| 2.3 | On Settlement recovery click **Show calculation**, then **Hide calculation**. | A table of value, weight and points per signal, ending in *Raw score 87.5 → review priority 88*. |
| 2.4 | Click **Inspect 8 citations**, then **Close**. | The cited Jira, Slack, GitHub and runbook text, with the exact quote highlighted. |
| 2.5 | Click **Review with expert**, then **Confirm**. | The finding is *confirmed*; a targeted question asks what to check and when to stop and escalate. |
| 2.6 | Paste the **expert answer** (below) into **Expert answer, in your own words** and click **Structure my answer**. | The draft fills in: preconditions, ordered steps, stop and escalate, success checks. |
| 2.7 | Click **Save draft**, then **Approve revision 1**. | *Approved versions: v1 · approved by alice*. |
| 2.8 | Click **View OKF export**. | The Markdown export with `type: Operational Playbook` and `status: active`, and a **Download** link. |
| 2.9 | Click **Open exercise for v1**, then **Generate exercise**. | A scenario plus a **Private rubric** of criteria, each traced to a line of the approved knowledge; some are marked critical. |
| 2.10 | Click **Approve and release exercise**, then **Log out**. | Status *released*. |

**Why it matters:** the score is a review priority computed by deterministic rules from evidence
anyone can open, not a judgement of Alice. The chart shows each signal's contribution, and the
cap shows why Webhooks is lowered: other engineers also recovered it. Nothing becomes knowledge
until the expert approves an exact draft revision, and exercises may only use approved knowledge.

## 3. Successor proves the transfer (≈ 1.5 min)

| # | Do | You see |
|---|---|---|
| 3.1 | Sign in as `bob` / `Bob@123`. | **Your exercises**, with *Settlement recovery · Not started*. |
| 3.2 | Click **Start**. | The scenario and **Your answer**. There is no rubric and nothing marked critical anywhere on the page. |
| 3.3 | Paste the **unsafe answer** (below) and click **Submit answer**. | **Not yet demonstrated**, with per-criterion results; the criterion about not creating a new settlement is *Not met*. (Alice's view marks it critical; Bob's never says which criteria are critical.) |
| 3.4 | Click **Try again**, paste the **correct paraphrase** (below) and click **Submit answer**. | **Demonstrated in this exercise**, every criterion *Met*, and **Earlier attempts (1)** keeps the first answer. |
| 3.5 | Type `/admin` after the address and press Enter. | *You do not have access to this page* (403). |
| 3.6 | Click **Log out**, then press the browser's **Back** button. | You stay on the sign-in page. |

**Why it matters:** the successor never sees the rubric before answering, so a pass means they
understood the procedure. A retry is a new attempt and the old one stays unchanged. A paraphrase
passes because matching is by meaning, not wording. Permissions are enforced on the server: the
admin page is refused, and after logout the session is revoked, so Back cannot reopen it.

## 4. Administrator checks the audit log (≈ 0.5 min)

| # | Do | You see |
|---|---|---|
| 4.1 | Sign in as `admin`, click **Audit log**. | Newest events first: `auth.login`, `handoff.created`, `finding.confirmed`, `knowledge.approved`, `exercise.released`, `attempt.submitted`, `auth.logout`, … by *admin*, *alice* and *bob*. |
| 4.2 | Type `bob` in **Actor** and click **Apply filters**. | Only Bob's sign-in, his two `attempt.submitted` events and his sign-out. |

**Why it matters:** every important state change and every sign-in, including failed ones, is
recorded with the person who did it and cannot be edited afterwards (the database rejects updates
to `audit_event`).

---

## Answers to copy

**Expert answer (step 2.6):**

> Before any retry, check the provider transaction state and the idempotency key on the existing attempt. If the provider says ACCEPTED or SETTLED, never create a new settlement, reconcile the existing one instead. If the provider state is unknown or contradicts ours, pause the retry worker and escalate to the AcmePay contact. Done means the ledger shows exactly one settlement for the order.

**Unsafe successor answer (step 3.3):**

> I would look up the settlement in the admin console and trigger a retry because it has been pending for more than 15 minutes, then confirm the ledger entry.

**Correct paraphrase (step 3.4):**

> First I'd confirm what AcmePay thinks happened to the original attempt using its idempotency key. If they already accepted or settled it I won't submit another one, I'll just reconcile ours. If their answer is unclear I stop the retry worker and raise it with the AcmePay contact. I'm done when there is a single settlement in the ledger for that order.

## If something goes wrong

- *Invalid username or password.* is shown for a wrong password and for an unknown username
  alike, by design. Re-run `python -m app.seed_users` to restore the demo accounts.
- *Cannot reach the SiloBreaker API* means the backend on :8000 is not running.
- To start over, sign in as `admin` and use **Handoffs → Reset demo**. Accounts are kept.
