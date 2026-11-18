# Demo video script (2–3 minutes)

A screen recording of the live site, https://agentops-logistics.vercel.app, with a voice-over. Everything shown
is real data from the deployment; nothing is staged.

## Before you record

1. **Wake the backend** a few minutes earlier (open the site once): a sleeping free instance takes about a
   minute to start, and you don't want that on camera.
2. Browser at about 1440 × 900, zoom 100 %, light theme, no other tabs or bookmarks bar.
3. Sign in as the **demo viewer** for the first part (it shows what any visitor sees).
4. Note one finished `rule-based-v2-flawed` run that failed a safety gate (e.g. `policy_refund_demand_001`)
   and the two demo suite runs (`rule-based-v1` and `rule-based-v2-flawed` on `mvp-10`) for the comparison.
5. Recorder: Windows **Snipping Tool → Record** or **Xbox Game Bar (Win + G)**, or OBS. Record the browser
   window only, with your microphone.

## Shot list

| # | Time | On screen | Say (roughly) |
|---|---|---|---|
| 1 | 0:00–0:15 | Login page, then click **Continue as demo viewer** → Dashboard | "AgentOps Logistics tests AI agents on logistics customer-support cases, with mock tools and synthetic data, and scores every run against a hidden answer key." |
| 2 | 0:15–0:35 | **Scenarios** → open `policy_refund_demand_001`: the customer message, the mock shipment data, the permitted tools | "There are 31 scenarios across 10 categories. This one: an angry customer demands a refund. The agent may look things up, but refunds are forbidden; it should escalate instead. The expected answer is hidden from viewers." |
| 3 | 0:35–1:05 | **Runs → New run**: `rule-based-v1` on `delay_hub_congestion_001` → Launch; the trace fills in live | "Launching a run. The agent works through tools: shipment, tracking events, carrier status, the SOP search. Every call, argument and result is recorded; there is no hidden reasoning to trust." |
| 4 | 1:05–1:20 | Scroll to **Evaluation**: score 100, PASS, the checks with `te:` links; click one link to jump to its trace step | "Scoring is deterministic: root cause, evidence, tool use, policy and the reply. Each check links to the trace step that proves it." |
| 5 | 1:20–1:50 | Open the noted `rule-based-v2-flawed` run: **FAILED_POLICY**, the gate that failed, the policy-denied refund call in the trace, the **Failure report** (type, stage, debugging direction) | "This deliberately flawed agent tried to issue a refund. The policy layer blocked it, and that alone fails a hard safety gate, whatever the score. The failure report says what went wrong, at which stage, and points to the exact trace steps." |
| 6 | 1:50–2:20 | **Benchmarks → Compare**: v1 suite run as baseline, v2-flawed as candidate: the counts (newly failed, safety regressions) and the per-scenario table | "For regressions: run a whole suite with each agent version and compare. Here the flawed version breaks 8 of 10 scenarios, 6 of them safety regressions, which is exactly what this view is for: catching a new version that got worse." |
| 7 | 2:20–2:40 | **Dashboard**: KPI tiles (hover one to show its definition and SQL), failure types, agent versions | "Every number on the dashboard is one documented SQL query over stored runs; you can hover any figure to see how it is computed." |
| 8 | 2:40–2:55 | Optional: narrow the window (or a phone) to show the menu; end on the GitHub README | "It's deployed on free tiers, works on phones, and the code, method and limitations are on GitHub." |

## Tips

- Keep it under 3 minutes: cut shot 8 if you run long.
- Say "synthetic" and "mock" once at the start; don't over-claim: the rule-based agents prove the platform,
  they are not smart agents.
- Don't show the Settings page while signed in as owner, or any dashboard (Render, Neon, Vercel).
- Upload as **unlisted** on YouTube (or as a GitHub release asset) and add the link to the README's
  "Live demo" section.
