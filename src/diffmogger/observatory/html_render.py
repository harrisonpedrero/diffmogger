from __future__ import annotations

from .common import *

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Diffmogger Observatory</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101214;
      --panel: #181c20;
      --panel-2: #20262b;
      --text: #f3f1e8;
      --muted: #a8b0aa;
      --line: #333b40;
      --green: #57c785;
      --blue: #67a6ff;
      --amber: #f0b84f;
      --red: #ff6b6b;
      --violet: #b993ff;
      --cyan: #59d0cf;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 24px;
      align-items: end;
      padding: 24px 28px 18px;
      border-bottom: 1px solid var(--line);
      background: #13171a;
    }
    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 56px);
      line-height: .95;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 10px;
      color: var(--muted);
      max-width: 780px;
      font-size: 15px;
    }
    .clock {
      min-width: 260px;
      text-align: right;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }
    main {
      display: grid;
      grid-template-columns: minmax(300px, 1.1fr) minmax(420px, 1.8fr) minmax(300px, 1fr);
      gap: 16px;
      padding: 16px;
    }
    section, .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    section > h2 {
      margin: 0;
      padding: 12px 14px;
      font-size: 13px;
      letter-spacing: 0;
      color: var(--muted);
      text-transform: uppercase;
      border-bottom: 1px solid var(--line);
      background: var(--panel-2);
    }
    .stack { display: grid; gap: 16px; align-content: start; }
    .content { padding: 14px; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #15191c;
      min-height: 88px;
    }
    .metric b {
      display: block;
      font-size: 26px;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }
    .metric span {
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .belt {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 14px;
    }
    .role {
      position: relative;
      min-height: 154px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #14181b;
    }
    .role.running {
      border-color: var(--green);
      box-shadow: 0 0 0 1px rgba(87,199,133,.35) inset;
    }
    .role.next {
      border-color: var(--blue);
    }
    .role h3 {
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
      text-transform: capitalize;
    }
    .role .state {
      margin-top: 10px;
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 4px 8px;
      border-radius: 999px;
      color: #08100c;
      background: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .role.running .state { background: var(--green); }
    .role.next .state { background: var(--blue); color: #07111f; }
    .role .counts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }
    .active-run {
      margin: 0 14px 14px;
      padding: 14px;
      border: 1px solid rgba(87,199,133,.45);
      border-radius: 8px;
      background: rgba(87,199,133,.08);
    }
    .active-run strong { color: var(--green); }
    .queue-list, .timeline, .logs { display: grid; gap: 10px; }
    .health {
      margin: 0 14px 14px;
      padding: 12px 14px;
      border: 1px solid rgba(87,199,133,.45);
      border-radius: 8px;
      background: rgba(87,199,133,.07);
      color: var(--muted);
    }
    .health.warning {
      border-color: rgba(240,184,79,.65);
      background: rgba(240,184,79,.09);
    }
    .health strong { display: block; color: var(--green); margin-bottom: 4px; }
    .health.warning strong { color: var(--amber); }
    .item {
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #14181b;
    }
    .item-title {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 6px;
      font-weight: 700;
    }
    .muted { color: var(--muted); }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .chip {
      display: inline-flex;
      min-height: 24px;
      align-items: center;
      padding: 3px 7px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
    }
    .chip.queued { color: var(--blue); border-color: rgba(103,166,255,.5); }
    .chip.deferred { color: var(--amber); border-color: rgba(240,184,79,.5); }
    .chip.failed { color: var(--red); border-color: rgba(255,107,107,.5); }
    .chip.applied { color: var(--green); border-color: rgba(87,199,133,.5); }
    .chip.skipped { color: var(--muted); border-color: rgba(168,176,170,.45); }
    .mission {
      display: grid;
      gap: 12px;
    }
    .mission p { margin: 0; color: var(--muted); }
    .mission strong { display: block; color: var(--text); margin-bottom: 4px; }
    .review-list, .check-list {
      display: grid;
      gap: 10px;
    }
    .check-list {
      margin-top: 12px;
    }
    .score-summary {
      margin-bottom: 10px;
      color: var(--muted);
    }
    .action-plan {
      margin-bottom: 10px;
    }
    .action-plan .item-title {
      align-items: center;
    }
    .action-plan ol {
      margin: 8px 0 0;
      padding-left: 20px;
      color: var(--muted);
    }
    .scorecard-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .scorecard-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #14181b;
      min-height: 112px;
    }
    .scorecard-item b {
      display: block;
      font-size: 24px;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }
    .scorecard-item strong {
      display: block;
      margin: 8px 0 4px;
    }
    .scorecard-item.good { border-color: rgba(87,199,133,.5); }
    .scorecard-item.warn { border-color: rgba(240,184,79,.6); }
    .scorecard-item.bad { border-color: rgba(255,107,107,.6); }
    .status-line {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .status-pill {
      padding: 6px 9px;
      border-radius: 999px;
      background: #111518;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    .status-pill.good { color: var(--green); }
    .status-pill.warn { color: var(--amber); }
    .status-pill.info { color: var(--cyan); }
    .progress-note {
      color: var(--muted);
      min-height: 72px;
    }
    @media (max-width: 1180px) {
      main { grid-template-columns: 1fr; }
      .belt { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      header { grid-template-columns: 1fr; }
      .clock { text-align: left; min-width: 0; }
    }
    @media (max-width: 640px) {
      main { padding: 10px; }
      header { padding: 18px 16px 14px; }
      .belt, .metric-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>Diffmogger Observatory</h1>
        <div class="subtitle" id="subtitle">Local automation telemetry for a running target.</div>
      </div>
      <div class="clock">
        <div id="generated">Waiting for state...</div>
        <div id="targetName"></div>
      </div>
    </header>
    <main>
      <div class="stack">
        <section>
          <h2>Mission State</h2>
          <div class="content mission" id="mission"></div>
        </section>
        <section>
          <h2>Self Review</h2>
          <div class="content">
            <div class="review-list" id="selfReview"></div>
            <div class="check-list" id="checkList"></div>
          </div>
        </section>
        <section>
          <h2>Scorecard</h2>
          <div class="content">
            <div class="score-summary" id="scoreSummary"></div>
            <div class="action-plan" id="actionPlan"></div>
            <div class="scorecard-grid" id="scorecard"></div>
          </div>
        </section>
        <section>
          <h2>Local State</h2>
          <div class="content">
            <div class="metric-grid" id="metrics"></div>
          </div>
        </section>
        <section>
          <h2>Recent Logs</h2>
          <div class="content logs" id="logs"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Activity Lanes</h2>
          <div class="belt" id="belt"></div>
          <div id="activeRun"></div>
        </section>
        <section>
          <h2>Runtime Health</h2>
          <div class="content" id="health"></div>
        </section>
        <section>
          <h2>Next Up</h2>
          <div class="content queue-list" id="nextUp"></div>
        </section>
        <section>
          <h2>Patch Queue</h2>
          <div class="content queue-list" id="patches"></div>
        </section>
        <section>
          <h2>Recent Outcomes</h2>
          <div class="content queue-list" id="outcomes"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Timeline</h2>
          <div class="content timeline" id="timeline"></div>
        </section>
        <section>
          <h2>Progress Pulse</h2>
          <div class="content progress-note" id="progress"></div>
        </section>
        <section>
          <h2>Local Repo</h2>
          <div class="content" id="repo"></div>
        </section>
      </div>
    </main>
  </div>
  <script>
    const INITIAL_STATE = __INITIAL_STATE__;
    const STATE_URL = __STATE_URL__;
    const ROLES = ["planner", "builder", "hardener", "integrator"];

    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function clear(node) {
      while (node.firstChild) node.removeChild(node.firstChild);
    }

    function renderMetric(label, value) {
      const node = el("div", "metric");
      node.appendChild(el("b", "", String(value)));
      node.appendChild(el("span", "", label));
      return node;
    }

    function historyLabel(item) {
      if (!item.progress_success) return "no progress";
      const role = item.role || "";
      if (role === "integrator") {
        const accepted = ((item.metadata || {}).accepted_by_role) || {};
        const total = Object.values(accepted).reduce((sum, value) => sum + Number(value || 0), 0);
        return total ? "accepted " + total : "integrated";
      }
      if (role === "planner") return "planned";
      if (role === "builder") return "built";
      if (role === "hardener") return "hardened";
      return "progress";
    }

    function acceptedRoleText(item) {
      const accepted = ((item.metadata || {}).accepted_by_role) || {};
      const parts = Object.entries(accepted).filter(([, value]) => Number(value || 0) > 0).map(([role, value]) => role + ": " + value);
      return parts.length ? "accepted by role: " + parts.join(", ") : "";
    }

    function renderManifest(item) {
      const row = el("div", "item");
      const title = el("div", "item-title");
      title.appendChild(el("span", "", item.role + " / " + item.run_id));
      title.appendChild(el("span", "chip " + item.status, item.status));
      row.appendChild(title);
      row.appendChild(el("div", "", item.summary || "No summary."));
      if (item.deferral_reason) row.appendChild(el("div", "muted", "deferral: " + item.deferral_reason));
      if (item.deferral_root_cause) row.appendChild(el("div", "muted", "root cause: " + item.deferral_root_cause));
      if (item.baseline_status) row.appendChild(el("div", "muted", "baseline: " + item.baseline_status + (item.baseline_failure_signature ? " / " + item.baseline_failure_signature : "")));
      const chips = el("div", "chips");
      (item.changed_files || []).forEach(file => chips.appendChild(el("span", "chip", file)));
      if (chips.children.length) row.appendChild(chips);
      return row;
    }

    function checkChipClass(status) {
      if (status === "pass") return "applied";
      if (status === "fail") return "failed";
      if (status === "warn") return "deferred";
      if (status === "pending") return "queued";
      return "skipped";
    }

    function followStatusClass(status) {
      if (status === "followed") return "applied";
      if (status === "superseded") return "deferred";
      if (status === "still_pending") return "queued";
      return "skipped";
    }

    function render(data) {
      document.getElementById("generated").textContent = "Updated " + (data.generated_at || "now");
      document.getElementById("targetName").textContent = data.target_name || "target";
      document.getElementById("subtitle").textContent = "Runtime, queue, role, and verification state for " + (data.target_name || "the selected target") + ".";

      const mission = document.getElementById("mission");
      clear(mission);
      [
        ["Automation status", data.task.status],
        ["Current horizon", data.task.horizon],
        ["Best next milestone", data.task.best_next_milestone],
        ["Suggested next task", data.task.suggested_next_task],
        ["Known issue", data.task.known_issue]
      ].forEach(([title, body]) => {
        const p = el("p");
        p.appendChild(el("strong", "", title));
        p.appendChild(document.createTextNode(body || "unknown"));
        mission.appendChild(p);
      });
      const pills = el("div", "status-line");
      const statusClass = (data.task.status || "").startsWith("ACTIVE") ? "good" : "warn";
      pills.appendChild(el("span", "status-pill " + statusClass, data.task.status || "UNKNOWN"));
      pills.appendChild(el("span", "status-pill info", "horizon: " + (data.task.horizon_decision || "unknown")));
      pills.appendChild(el("span", "status-pill", "last: " + (data.task.last_updated || "unknown")));
      mission.appendChild(pills);

      const review = data.review || {};
      const selfReview = document.getElementById("selfReview");
      clear(selfReview);
      (review.items || []).forEach(item => {
        const row = el("div", "item");
        row.appendChild(el("div", "item-title", item.label || "Review item"));
        row.appendChild(el("div", "muted", item.body || "No detail recorded."));
        selfReview.appendChild(row);
      });
      (review.known_issues || []).slice(0, 3).forEach(issue => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Known issue"));
        title.appendChild(el("span", "chip deferred", "watch"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", issue));
        selfReview.appendChild(row);
      });
      if (!selfReview.children.length) selfReview.appendChild(el("div", "item muted", "No self-review state recorded yet."));

      const checkList = document.getElementById("checkList");
      clear(checkList);
      (review.checks || []).forEach(check => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Validation"));
        title.appendChild(el("span", "chip " + checkChipClass(check.status), check.status || "info"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", check.text || "No check detail."));
        checkList.appendChild(row);
      });
      if (!checkList.children.length) checkList.appendChild(el("div", "item muted", "No validation checks recorded yet."));

      const scorecardState = data.scorecard || {};
      const scoreSummary = document.getElementById("scoreSummary");
      scoreSummary.textContent = (scorecardState.summary || "No scorecard metrics recorded yet.") + " Status: " + (scorecardState.status || "unknown") + ".";
      const actionPlan = document.getElementById("actionPlan");
      clear(actionPlan);
      const plan = scorecardState.action_plan || {};
      if (plan.recommendation) {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", plan.label || "Action Plan"));
        title.appendChild(el("span", "chip " + (plan.priority === "high" || plan.priority === "blocked" ? "deferred" : "queued"), plan.lane || "local"));
        row.appendChild(title);
        row.appendChild(el("div", "", plan.recommendation));
        row.appendChild(el("div", "muted", plan.why || "No rationale recorded."));
        const steps = Array.isArray(plan.next_steps) ? plan.next_steps : [];
        if (steps.length) {
          const list = document.createElement("ol");
          steps.slice(0, 3).forEach(step => list.appendChild(el("li", "", step)));
          row.appendChild(list);
        }
        actionPlan.appendChild(row);
      } else {
        actionPlan.appendChild(el("div", "item muted", "No action plan recorded yet."));
      }
      const follow = data.follow_through || {};
      if (follow.status) {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Action Follow-Through"));
        title.appendChild(el("span", "chip " + followStatusClass(follow.status), String(follow.status || "still_pending").replace("_", " ")));
        row.appendChild(title);
        row.appendChild(el("div", "", follow.previous_recommendation || "No previous recommendation recorded."));
        row.appendChild(el("div", "muted", "expected " + (follow.expected_lane || "unknown") + "; observed " + (follow.observed_lane || "none") + " - " + (follow.observed_result || "No observed result recorded.")));
        if (follow.status_reason) row.appendChild(el("div", "muted", follow.status_reason));
        actionPlan.appendChild(row);
      }
      const historyState = data.recommendation_history || {};
      const historyRecords = Array.isArray(historyState.records) ? historyState.records : [];
      if (historyRecords.length) {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Recommendation History"));
        title.appendChild(el("span", "chip queued", String(historyRecords.length) + " recent"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", historyState.summary || "No recommendation history summary recorded."));
        historyRecords.slice(0, 5).forEach(record => {
          const status = String(record.status || "still_pending").replace("_", " ");
          const line = (record.recorded_at || "unknown") + ": " + status + "; expected " + (record.expected_lane || "unknown") + ", observed " + (record.observed_lane || "none") + " - " + (record.observed_result || "No observed result recorded.");
          row.appendChild(el("div", "", line));
          row.appendChild(el("div", "muted", "no-progress " + (record.no_progress || "inactive") + "; accepted " + String(record.accepted_total || 0) + ", deferred depth " + String(record.deferred_queue_depth || 0)));
        });
        actionPlan.appendChild(row);
      }
      const workerStrategy = data.worker_strategy || {};
      if (workerStrategy.strategy) {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", "Next-Run Worker Strategy"));
        title.appendChild(el("span", "chip queued", workerStrategy.strategy));
        row.appendChild(title);
        row.appendChild(el("div", "", "parallelism budget: " + String(workerStrategy.parallelism_budget || 0)));
        row.appendChild(el("div", "muted", workerStrategy.summary || "No next-run worker strategy recorded yet."));
        const reasons = Array.isArray(workerStrategy.reasons) ? workerStrategy.reasons : [];
        reasons.slice(0, 3).forEach(reason => row.appendChild(el("div", "muted", reason)));
        actionPlan.appendChild(row);
      }
      const scorecard = document.getElementById("scorecard");
      clear(scorecard);
      (scorecardState.items || []).forEach(item => {
        const row = el("div", "scorecard-item " + (item.kind || "info"));
        row.appendChild(el("b", "", String(item.value ?? "0")));
        row.appendChild(el("strong", "", item.label || "Metric"));
        row.appendChild(el("div", "muted", item.detail || "No detail recorded."));
        scorecard.appendChild(row);
      });
      if (!scorecard.children.length) scorecard.appendChild(el("div", "item muted", "No scorecard metrics recorded yet."));

      const metrics = document.getElementById("metrics");
      clear(metrics);
      metrics.appendChild(renderMetric("Queued patches", data.queue.totals.queued || 0));
      metrics.appendChild(renderMetric("Deferred patches", data.queue.totals.deferred || 0));
      metrics.appendChild(renderMetric("Unhandled inbox", data.human.unhandled_inbox || 0));
      metrics.appendChild(renderMetric("Activity cycles", data.conveyor.cycles || 0));

      const active = data.conveyor.active_role_run || {};
      const visibleDecisionQueue = (data.conveyor.decision_queue || []).filter(item => !(active.status === "running" && item.role === active.role));
      const nextRoles = new Set(visibleDecisionQueue.map(item => item.role));
      const belt = document.getElementById("belt");
      clear(belt);
      ROLES.forEach(role => {
        const counts = (data.queue.counts_by_role || {})[role] || {};
        const card = el("div", "role" + (active.role === role && active.status === "running" ? " running" : "") + (nextRoles.has(role) ? " next" : ""));
        card.appendChild(el("h3", "", role));
        const state = active.role === role && active.status === "running" ? "running" : (nextRoles.has(role) ? "next" : "standby");
        card.appendChild(el("div", "state", state));
        const countGrid = el("div", "counts");
        ["queued", "deferred", "applied", "failed", "skipped"].forEach(status => {
          countGrid.appendChild(el("div", "", status + ": " + (counts[status] || 0)));
        });
        card.appendChild(countGrid);
        belt.appendChild(card);
      });

      const activeRun = document.getElementById("activeRun");
      clear(activeRun);
      if (active.role) {
        const node = el("div", "active-run");
        node.appendChild(el("strong", "", active.status === "running" ? "Running now: " + active.role : "Last active run looks stale: " + active.role));
        node.appendChild(el("div", "muted", (active.run_id || "unknown") + " | " + (active.reason || "no reason recorded")));
          activeRun.appendChild(node);
      }

      const health = document.getElementById("health");
      clear(health);
      const healthData = (data.conveyor || {}).health || {};
      const healthNode = el("div", "health " + (healthData.status || "ok"));
      healthNode.appendChild(el("strong", "", (healthData.status || "ok").toUpperCase()));
      healthNode.appendChild(el("div", "", healthData.summary || "runtime policy active."));
      if ((healthData.recent_roles || []).length) healthNode.appendChild(el("div", "muted", "recent roles: " + healthData.recent_roles.join(" -> ")));
      health.appendChild(healthNode);
      const noProgress = ((data.conveyor || {}).no_progress) || {};
      if (noProgress.active) {
        const noProgressNode = el("div", "health warning");
        noProgressNode.appendChild(el("strong", "", "NO-PROGRESS CIRCUIT"));
        const streak = Number(noProgress.streak || 0);
        const threshold = Number(noProgress.threshold || 0);
        const countText = threshold ? streak + "/" + threshold : String(streak);
        noProgressNode.appendChild(el("div", "", "No-progress circuit breaker active after " + countText + " integrator cycle(s)."));
        noProgressNode.appendChild(el("div", "muted", noProgress.reason || "Integrator made no patch progress."));
        if (noProgress.planner_requested_at) noProgressNode.appendChild(el("div", "muted", "planner handoff requested at " + noProgress.planner_requested_at));
        health.appendChild(noProgressNode);
      }

      const nextUp = document.getElementById("nextUp");
      clear(nextUp);
      visibleDecisionQueue.forEach(item => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", item.role || "idle"));
        title.appendChild(el("span", "chip " + (item.state || ""), item.state || "planned"));
        row.appendChild(title);
        row.appendChild(el("div", "muted", item.reason || "No reason recorded."));
        nextUp.appendChild(row);
      });
      const emptyStates = data.empty_states || {};
      if (!nextUp.children.length) nextUp.appendChild(el("div", "item muted", active.status === "running" ? "Current role is running; next decision refreshes after it exits." : (emptyStates.next_up || "No activity decision recorded yet.")));

      const patches = document.getElementById("patches");
      clear(patches);
      (data.queue.manifests || []).forEach(item => {
        patches.appendChild(renderManifest(item));
      });
      if (!patches.children.length) patches.appendChild(el("div", "item muted", emptyStates.patch_queue || "No queued or deferred patches yet."));

      const outcomes = document.getElementById("outcomes");
      clear(outcomes);
      (data.queue.recent_outcomes || []).forEach(item => {
        outcomes.appendChild(renderManifest(item));
      });
      if (!outcomes.children.length) outcomes.appendChild(el("div", "item muted", emptyStates.recent_outcomes || "No recent applied, failed, or skipped role outputs yet."));

      const timeline = document.getElementById("timeline");
      clear(timeline);
      (data.conveyor.history || []).slice().reverse().forEach(item => {
        const row = el("div", "item");
        const title = el("div", "item-title");
        title.appendChild(el("span", "", item.role || "role"));
        title.appendChild(el("span", "chip " + (item.progress_success ? "applied" : "deferred"), historyLabel(item)));
        row.appendChild(title);
        row.appendChild(el("div", "muted", (item.finished_at || "") + " | exit " + item.exit_code));
        row.appendChild(el("div", "", item.reason || "No reason recorded."));
        const acceptedText = acceptedRoleText(item);
        if (acceptedText) row.appendChild(el("div", "muted", acceptedText));
        timeline.appendChild(row);
      });
      if (!timeline.children.length) timeline.appendChild(el("div", "item muted", emptyStates.timeline || "No activity history yet."));

      const progress = document.getElementById("progress");
      progress.textContent = data.progress_recent || "No progress pulse yet.";

      const logs = document.getElementById("logs");
      clear(logs);
      (data.logs || []).forEach(item => {
        const row = el("div", "item");
        row.appendChild(el("div", "item-title", item.name || "log"));
        row.appendChild(el("div", "muted", item.tail || "No log lines."));
        logs.appendChild(row);
      });
      if (!logs.children.length) logs.appendChild(el("div", "item muted", "No automation logs yet."));

      const repo = document.getElementById("repo");
      clear(repo);
      repo.appendChild(renderMetric("Dirty files", data.git.dirty_count || 0));
      const commits = el("div", "chips");
      (data.git.recent_commits || []).forEach(commit => commits.appendChild(el("span", "chip", commit)));
      repo.appendChild(commits);
    }

    async function refresh() {
      if (!STATE_URL) {
        render(INITIAL_STATE);
        return;
      }
      try {
        const response = await fetch(STATE_URL + "?t=" + Date.now(), {cache: "no-store"});
        render(await response.json());
      } catch (error) {
        const fallback = INITIAL_STATE || {target_name: "target", generated_at: new Date().toISOString(), task: {}, human: {}, git: {}, queue: {totals: {}, counts_by_role: {}, manifests: []}, conveyor: {decision_queue: [], history: []}, scorecard: {items: []}, first_review: {}, follow_through: {}, recommendation_history: {records: []}, worker_strategy: {}, review: {items: [], checks: [], known_issues: []}, empty_states: {}, logs: []};
        fallback.progress_recent = "Observatory refresh failed: " + error;
        render(fallback);
      }
    }

    refresh();
    if (STATE_URL) setInterval(refresh, 2500);
  </script>
</body>
</html>
"""

REPLAY_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Diffmogger Observatory</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f1316;
      --panel: #1b2227;
      --panel-dark: #13181c;
      --panel-head: #222a30;
      --line: #334048;
      --text: #f4f1ea;
      --muted: #aab2b4;
      --subtle: #77828a;
      --green: #5fd68b;
      --blue: #70a8ff;
      --amber: #eebe4e;
      --red: #f46b69;
      --cyan: #4fd3df;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 14px;
      padding: 28px 30px 18px;
    }
    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: end;
    }
    h1 {
      margin: 0;
      font-size: clamp(34px, 5vw, 62px);
      line-height: .95;
      letter-spacing: 0;
    }
    .subtitle { margin-top: 10px; color: var(--muted); font-size: 17px; }
    .clock { color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
    .chips, .meta-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .chip {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: none;
    }
    .chip.good, .chip.applied, .chip.accepted { color: var(--green); border-color: rgba(95,214,139,.55); }
    .chip.info, .chip.queued, .chip.built { color: var(--blue); border-color: rgba(112,168,255,.55); }
    .chip.warn, .chip.deferred, .chip.planned, .chip.no-progress { color: var(--amber); border-color: rgba(238,190,78,.6); }
    .chip.bad, .chip.failed, .chip.retry { color: var(--red); border-color: rgba(244,107,105,.6); }
    .grid {
      display: grid;
      grid-template-columns: minmax(280px, .88fr) minmax(560px, 1.65fr) minmax(340px, 1fr);
      gap: 18px;
      min-height: 0;
    }
    .stack { display: grid; align-content: start; gap: 18px; min-height: 0; }
    section {
      min-width: 0;
      overflow: hidden;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    section > h2 {
      margin: 0;
      padding: 12px 16px;
      color: var(--muted);
      background: var(--panel-head);
      border-bottom: 1px solid var(--line);
      font-size: 13px;
      letter-spacing: 0;
      text-transform: uppercase;
    }
    .content { padding: 16px; }
    .mission { display: grid; gap: 18px; }
    .mission-block strong { display: block; margin-bottom: 5px; color: var(--text); }
    .mission-block div { color: var(--muted); overflow-wrap: anywhere; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .metric {
      min-height: 92px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-dark);
    }
    .metric b { display: block; font-size: 42px; line-height: .95; font-variant-numeric: tabular-nums; }
    .metric span { display: block; margin-top: 8px; color: var(--muted); }
    .belt {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      padding: 16px;
    }
    .role {
      min-height: 178px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-dark);
    }
    .role.active { border-color: var(--green); box-shadow: 0 0 0 1px rgba(95,214,139,.35) inset; }
    .role.next { border-color: var(--blue); }
    .role h3 { margin: 0 0 12px; font-size: 24px; letter-spacing: 0; text-transform: capitalize; }
    .role-counts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px 14px;
      margin-top: 15px;
      color: var(--muted);
      font-size: 13px;
      font-variant-numeric: tabular-nums;
    }
    .runner-strip {
      margin: 0 16px 16px;
      padding: 14px 16px;
      border: 1px solid rgba(95,214,139,.45);
      border-radius: 8px;
      background: rgba(95,214,139,.08);
    }
    .runner-strip strong { color: var(--green); }
    .runner-strip div { color: var(--muted); overflow-wrap: anywhere; }
    .story-panel {
      min-height: 330px;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .story-body {
      min-height: 0;
      overflow: auto;
      padding: 16px;
    }
    .story-title-row { display: flex; justify-content: space-between; gap: 14px; align-items: start; }
    .story-title {
      min-width: 0;
      margin: 0;
      font-size: clamp(28px, 3.2vw, 42px);
      line-height: 1.08;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }
    .story-detail {
      margin-top: 12px;
      color: var(--muted);
      font-size: 18px;
      overflow-wrap: anywhere;
    }
    .landed-now {
      margin-top: 24px;
      display: grid;
      gap: 10px;
    }
    .commit-title {
      color: var(--text);
      font-size: 20px;
      font-weight: 800;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .commit-summary { color: var(--muted); overflow-wrap: anywhere; }
    .file-row {
      display: grid;
      grid-template-columns: 92px minmax(120px, .9fr) minmax(120px, 1fr);
      gap: 12px;
      align-items: baseline;
      color: var(--muted);
      font-size: 13px;
    }
    .file-row code { color: var(--subtle); overflow-wrap: anywhere; }
    .stat { color: var(--green); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .commit-list {
      max-height: calc(100vh - 250px);
      overflow: auto;
      display: grid;
      gap: 12px;
    }
    .commit-card, .support-card, .timeline-card {
      padding: 13px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-dark);
    }
    .commit-meta { margin-top: 8px; color: var(--subtle); font-variant-numeric: tabular-nums; }
    .support-grid { display: grid; gap: 12px; }
    .support-card strong { display: block; margin-bottom: 6px; }
    .support-card div { color: var(--muted); overflow-wrap: anywhere; }
    .timeline-shell {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }
    .timeline-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      color: var(--muted);
      background: var(--panel-head);
      border-bottom: 1px solid var(--line);
      text-transform: uppercase;
      font-size: 13px;
      font-weight: 800;
    }
    .timeline-track {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      overscroll-behavior-x: contain;
      padding: 12px 14px 14px;
      scroll-snap-type: x proximity;
    }
    .timeline-card {
      flex: 0 0 260px;
      cursor: pointer;
      scroll-snap-align: start;
      text-align: left;
      color: inherit;
    }
    .timeline-card.selected { border-color: var(--green); box-shadow: 0 0 0 1px rgba(95,214,139,.35) inset; }
    .timeline-role { display: flex; justify-content: space-between; gap: 8px; font-weight: 800; text-transform: capitalize; }
    .timeline-time { margin-top: 6px; color: var(--subtle); font-size: 12px; font-variant-numeric: tabular-nums; }
    .timeline-reason { margin-top: 6px; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
    @media (max-width: 1260px) {
      .grid { grid-template-columns: 1fr; }
      .commit-list { max-height: none; }
    }
    @media (max-width: 760px) {
      .app { padding: 18px 12px 12px; }
      header { grid-template-columns: 1fr; }
      .clock { text-align: left; }
      .belt, .metric-grid { grid-template-columns: 1fr; }
      .file-row { grid-template-columns: 1fr; gap: 2px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div>
        <h1>Diffmogger Autonomous Build Log</h1>
        <div class="subtitle">Diffmogger Observatory view: replay-style automation progress reconstructed from runtime events, commits, and diff stats.</div>
      </div>
      <div class="clock">
        <div id="generated">Waiting for state...</div>
        <div id="targetName"></div>
      </div>
    </header>
    <main class="grid">
      <div class="stack">
        <section>
          <h2>Mission State</h2>
          <div class="content mission" id="mission"></div>
        </section>
        <section>
          <h2>Scorecard</h2>
          <div class="content">
            <div class="metric-grid" id="metrics"></div>
          </div>
        </section>
        <section>
          <h2>Action Plan</h2>
          <div class="content support-grid" id="actionPlan"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Activity Lanes</h2>
          <div class="belt" id="belt"></div>
          <div id="activeRun"></div>
        </section>
        <section class="story-panel">
          <h2>Progress Story</h2>
          <div class="story-body" id="progressStory"></div>
        </section>
        <section>
          <h2>Runtime Health</h2>
          <div class="content support-grid" id="health"></div>
        </section>
      </div>
      <div class="stack">
        <section>
          <h2>Landed Work</h2>
          <div class="content commit-list" id="landedWork"></div>
        </section>
        <section>
          <h2>Recent Outcomes</h2>
          <div class="content support-grid" id="recentOutcomes"></div>
        </section>
        <section>
          <h2>First Review / Runtime State</h2>
          <div class="content support-grid" id="support"></div>
        </section>
      </div>
    </main>
    <section class="timeline-shell">
      <div class="timeline-header">
        <span>Event Timeline</span>
        <span id="timelineCount">0 events</span>
      </div>
      <div class="timeline-track" id="timeline"></div>
    </section>
  </div>
  <script>
    const INITIAL_STATE = __INITIAL_STATE__;
    const STATE_URL = __STATE_URL__;
    const ROLES = ["planner", "builder", "hardener", "integrator"];
    let selectedEventIndex = null;
    let currentData = null;

    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
    function text(value, fallback = "") { return value === undefined || value === null || value === "" ? fallback : String(value); }
    function timeLabel(value) {
      if (!value) return "unknown";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(11, 19) + " UTC";
    }
    function metric(label, value, colorClass = "") {
      const node = el("div", "metric");
      const number = el("b", colorClass, text(value, "0"));
      node.appendChild(number);
      node.appendChild(el("span", "", label));
      return node;
    }
    function chip(label, cls = "") { return el("span", "chip " + cls, label); }
    function eventStatus(event) {
      if (event.status === "running") return "running";
      if (event.role === "integrator") {
        const accepted = Number(((event.metadata || {}).accepted_delta) || 0);
        const deferred = Number(((event.metadata || {}).deferred_delta) || 0);
        if (accepted) return "accepted";
        if (deferred) return "deferred";
        return event.progress_success ? "accepted" : "no-progress";
      }
      if (event.exit_code !== 0 && event.exit_code !== undefined && event.exit_code !== null) return "retry";
      if (event.role === "planner") return "planned";
      if (event.role === "builder") return "built";
      if (event.role === "hardener") return "accepted";
      return event.progress_success ? "accepted" : "no-progress";
    }
    function eventTitle(event) {
      const role = text(event.role, "role");
      if (event.status === "running") return role + " is running now";
      if (role === "integrator") {
        const accepted = Number(((event.metadata || {}).accepted_delta) || 0);
        const deferred = Number(((event.metadata || {}).deferred_delta) || 0);
        if (accepted) return "Integrator accepted " + accepted + " patch" + (accepted === 1 ? "" : "es");
        if (deferred) return "Integrator deferred " + deferred + " patch" + (deferred === 1 ? "" : "es");
        return "Integrator checked the queue";
      }
      if (role === "planner") return "Planner refreshed the plan";
      if (role === "builder") return "Builder produced a patch";
      if (role === "hardener") return "Hardener verified the lane";
      return role + " completed";
    }
    function eventTime(event) { return event.finished_at || event.started_at || event.time || ""; }
    function eventsFor(data) {
      const history = Array.isArray(data.conveyor?.history) ? data.conveyor.history.slice() : [];
      const active = data.conveyor?.active_role_run || {};
      if (active.role) {
        history.push({
          role: active.role,
          reason: active.reason,
          started_at: active.started_at,
          finished_at: active.started_at,
          status: active.status,
          progress_success: active.status === "running",
          exit_code: null,
        });
      }
      return history;
    }
    function commitsFor(data) { return Array.isArray(data.git?.commits) ? data.git.commits.slice() : []; }
    function latestCommitFor(data, event) {
      const commits = commitsFor(data).sort((a, b) => new Date(a.time || 0) - new Date(b.time || 0));
      const eventDate = new Date(eventTime(event) || Date.now());
      let latest = commits[commits.length - 1] || null;
      for (const commit of commits) {
        const commitDate = new Date(commit.time || 0);
        if (!Number.isNaN(eventDate.getTime()) && commitDate <= eventDate) latest = commit;
      }
      return latest;
    }
    function renderCommit(commit, compact = false) {
      const card = el("div", compact ? "support-card" : "commit-card");
      card.appendChild(el("div", "commit-title", text(commit.subject, "Commit landed")));
      const meta = el("div", "meta-row commit-meta");
      meta.appendChild(chip(text(commit.hash, ""), "info"));
      meta.appendChild(el("span", "", timeLabel(commit.time)));
      meta.appendChild(el("span", "", text(commit.file_count, 0) + " files"));
      meta.appendChild(el("span", "stat", "+" + text(commit.additions, 0) + " / -" + text(commit.deletions, 0)));
      card.appendChild(meta);
      if (commit.summary) card.appendChild(el("div", "commit-summary", commit.summary));
      (commit.files || []).slice(0, compact ? 3 : 4).forEach(file => {
        const row = el("div", "file-row");
        row.appendChild(el("span", "stat", "+" + text(file.additions, 0) + " / -" + text(file.deletions, 0)));
        row.appendChild(el("strong", "", text(file.label, file.area || "change")));
        row.appendChild(el("code", "", text(file.path, "")));
        card.appendChild(row);
      });
      return card;
    }
    function renderMission(data) {
      const mission = document.getElementById("mission");
      clear(mission);
      [
        ["Automation status", data.task?.status],
        ["Current horizon", data.task?.horizon],
        ["Mission", data.task?.current_assessment],
        ["Best next milestone", data.task?.best_next_milestone],
        ["Known issue", data.task?.known_issue],
      ].forEach(([label, value]) => {
        const block = el("div", "mission-block");
        block.appendChild(el("strong", "", label));
        block.appendChild(el("div", "", text(value, "unknown")));
        mission.appendChild(block);
      });
      const chips = el("div", "chips");
      chips.appendChild(chip(text(data.task?.status, "UNKNOWN"), String(data.task?.status || "").startsWith("ACTIVE") ? "good" : "warn"));
      chips.appendChild(chip("horizon: " + text(data.task?.horizon_decision, "unknown"), "info"));
      chips.appendChild(chip("last: " + text(data.task?.last_updated, "unknown")));
      mission.appendChild(chips);
    }
    function renderMetrics(data) {
      const metrics = document.getElementById("metrics");
      clear(metrics);
      const totals = data.queue?.totals || {};
      const progress = data.progress || {};
      metrics.appendChild(metric("Activity cycles", data.conveyor?.cycles || 0, "info"));
      metrics.appendChild(metric("Accepted patches", progress.accepted_total || totals.applied || 0, "good"));
      metrics.appendChild(metric("Deferred patches", totals.deferred || progress.deferred_queue_depth || 0, "warn"));
      metrics.appendChild(metric("Unhandled inbox", data.human?.unhandled_inbox || 0));
    }
    function renderBelt(data) {
      const belt = document.getElementById("belt");
      clear(belt);
      const active = data.conveyor?.active_role_run || {};
      const decisions = Array.isArray(data.conveyor?.decision_queue) ? data.conveyor.decision_queue : [];
      const nextRoles = new Set(decisions.map(item => item.role));
      ROLES.forEach(role => {
        const counts = (data.queue?.counts_by_role || {})[role] || {};
        const state = active.role === role && active.status === "running" ? "active" : (nextRoles.has(role) ? "next" : "");
        const card = el("div", "role " + state);
        card.appendChild(el("h3", "", role));
        card.appendChild(chip(state === "active" ? "running" : (state === "next" ? "next" : "standby"), state === "active" ? "good" : (state === "next" ? "info" : "")));
        const grid = el("div", "role-counts");
        ["queued", "deferred", "applied", "failed", "skipped"].forEach(status => grid.appendChild(el("div", "", status + ": " + text(counts[status], 0))));
        card.appendChild(grid);
        belt.appendChild(card);
      });
      const activeRun = document.getElementById("activeRun");
      clear(activeRun);
      if (active.role) {
        const node = el("div", "runner-strip");
        node.appendChild(el("strong", "", active.status === "running" ? "Running now: " + active.role : "Last active role: " + active.role));
        node.appendChild(el("div", "", text(active.run_id, "unknown") + " | " + text(active.reason, "no reason recorded")));
        activeRun.appendChild(node);
      }
    }
    function renderStory(data) {
      const story = document.getElementById("progressStory");
      clear(story);
      const events = eventsFor(data);
      const index = events.length ? Math.min(selectedEventIndex ?? events.length - 1, events.length - 1) : -1;
      const event = index >= 0 ? events[index] : null;
      const titleRow = el("div", "story-title-row");
      const title = el("h3", "story-title", event ? eventTitle(event) : "No activity timeline yet");
      titleRow.appendChild(title);
      if (event) titleRow.appendChild(chip(eventStatus(event), eventStatus(event)));
      story.appendChild(titleRow);
      story.appendChild(el("div", "story-detail", event ? text(event.reason, "No reason recorded.") : text(data.empty_states?.timeline, "No activity timeline yet.")));
      const commit = event ? latestCommitFor(data, event) : commitsFor(data)[0];
      const latest = el("div", "landed-now");
      latest.appendChild(el("strong", "", "Latest landed work"));
      if (commit) latest.appendChild(renderCommit(commit, true));
      else latest.appendChild(el("div", "support-card", "No commits recorded yet."));
      story.appendChild(latest);
    }
    function renderLanded(data) {
      const node = document.getElementById("landedWork");
      clear(node);
      const commits = commitsFor(data);
      commits.slice(0, 10).forEach(commit => node.appendChild(renderCommit(commit)));
      if (!node.children.length) node.appendChild(el("div", "commit-card", "No landed work recorded yet."));
    }
    function renderSupport(data) {
      const action = document.getElementById("actionPlan");
      clear(action);
      const plan = data.scorecard?.action_plan || {};
      const planCard = el("div", "support-card");
      planCard.appendChild(el("strong", "", text(plan.label, "Action Plan")));
      planCard.appendChild(el("div", "", text(plan.recommendation, "No action plan recorded yet.")));
      if (plan.why) planCard.appendChild(el("div", "", plan.why));
      action.appendChild(planCard);
      const follow = data.follow_through || {};
      const followCard = el("div", "support-card");
      followCard.appendChild(el("strong", "", "Action Follow-Through"));
      followCard.appendChild(el("div", "", text(follow.status, "No follow-through record yet.")));
      followCard.appendChild(el("div", "", text(follow.observed_result, "")));
      action.appendChild(followCard);
      const historyCard = el("div", "support-card");
      historyCard.appendChild(el("strong", "", "Recommendation History"));
      historyCard.appendChild(el("div", "", text(data.recommendation_history?.summary, "No recommendation history recorded.")));
      action.appendChild(historyCard);
      const workerCard = el("div", "support-card");
      const workerStrategy = data.worker_strategy || {};
      workerCard.appendChild(el("strong", "", "Next-Run Worker Strategy"));
      workerCard.appendChild(el("div", "", text(workerStrategy.strategy, "NO_WORKERS") + " / budget " + text(workerStrategy.parallelism_budget, 0)));
      workerCard.appendChild(el("div", "", text(workerStrategy.summary, "No next-run worker strategy recorded.")));
      action.appendChild(workerCard);

      const health = document.getElementById("health");
      clear(health);
      const healthData = data.conveyor?.health || {};
      const healthCard = el("div", "support-card");
      healthCard.appendChild(el("strong", "", "Runtime Health"));
      healthCard.appendChild(el("div", "", text(healthData.summary, "No runtime health recorded.")));
      if (Array.isArray(healthData.recent_roles)) healthCard.appendChild(el("div", "", "recent roles: " + healthData.recent_roles.join(" -> ")));
      health.appendChild(healthCard);
      const noProgress = data.conveyor?.no_progress || {};
      if (noProgress.active) {
        const card = el("div", "support-card");
        card.appendChild(el("strong", "", "NO-PROGRESS CIRCUIT"));
        card.appendChild(el("div", "", "no_progress_circuit: active after " + text(noProgress.streak, 0) + "/" + text(noProgress.threshold, "?")));
        card.appendChild(el("div", "", text(noProgress.reason, "")));
        health.appendChild(card);
      }

      const outcomes = document.getElementById("recentOutcomes");
      clear(outcomes);
      (data.queue?.recent_outcomes || []).slice(0, 5).forEach(item => {
        const card = el("div", "support-card");
        card.appendChild(el("strong", "", text(item.role, "role") + " / " + text(item.run_id, "run")));
        card.appendChild(el("div", "", text(item.status, "status") + ": " + text(item.summary, "No summary.")));
        outcomes.appendChild(card);
      });
      if (!outcomes.children.length) outcomes.appendChild(el("div", "support-card", text(data.empty_states?.recent_outcomes, "No recent outcomes.")));

      const support = document.getElementById("support");
      clear(support);
      const first = el("div", "support-card");
      first.appendChild(el("strong", "", "First review"));
      first.appendChild(el("div", "", text(data.first_review?.summary, "No first review state recorded.")));
      support.appendChild(first);
      const safety = el("div", "support-card");
      safety.appendChild(el("strong", "", "Integration safety"));
      safety.appendChild(el("div", "", text(data.task?.integration_safety?.summary, "Integration safety check has not run yet.")));
      support.appendChild(safety);
      const triage = el("div", "support-card");
      triage.appendChild(el("strong", "", "Deferred triage"));
      triage.appendChild(el("div", "", text(data.progress?.deferred_triage?.summary, "No deferred patch backlog recorded.")));
      support.appendChild(triage);
    }
    function renderTimeline(data) {
      const events = eventsFor(data);
      const timeline = document.getElementById("timeline");
      clear(timeline);
      document.getElementById("timelineCount").textContent = events.length + " event" + (events.length === 1 ? "" : "s");
      if (!events.length) {
        timeline.appendChild(el("div", "timeline-card selected", text(data.empty_states?.timeline, "No activity timeline yet.")));
        return;
      }
      if (selectedEventIndex === null || selectedEventIndex >= events.length) selectedEventIndex = events.length - 1;
      events.forEach((event, index) => {
        const card = el("button", "timeline-card" + (index === selectedEventIndex ? " selected" : ""));
        card.type = "button";
        const row = el("div", "timeline-role");
        row.appendChild(el("span", "", text(event.role, "role")));
        row.appendChild(chip(eventStatus(event), eventStatus(event)));
        card.appendChild(row);
        card.appendChild(el("div", "timeline-time", timeLabel(eventTime(event)) + " | exit " + text(event.exit_code, "running")));
        card.appendChild(el("div", "timeline-reason", text(event.reason, "No reason recorded.")));
        card.addEventListener("click", () => {
          selectedEventIndex = index;
          renderStory(currentData);
          renderTimeline(currentData);
        });
        timeline.appendChild(card);
      });
    }
    function render(data) {
      currentData = data || {};
      document.getElementById("generated").textContent = "Updated " + text(currentData.generated_at, "now");
      document.getElementById("targetName").textContent = text(currentData.target_name, "target");
      renderMission(currentData);
      renderMetrics(currentData);
      renderBelt(currentData);
      renderStory(currentData);
      renderLanded(currentData);
      renderSupport(currentData);
      renderTimeline(currentData);
    }
    async function refresh() {
      if (!STATE_URL) {
        render(INITIAL_STATE);
        return;
      }
      try {
        const response = await fetch(STATE_URL + "?t=" + Date.now(), {cache: "no-store"});
        render(await response.json());
      } catch (error) {
        const fallback = INITIAL_STATE || {target_name: "target", generated_at: new Date().toISOString(), task: {}, human: {}, git: {commits: []}, queue: {totals: {}, counts_by_role: {}, manifests: [], recent_outcomes: []}, conveyor: {decision_queue: [], history: []}, scorecard: {items: []}, worker_strategy: {}, review: {}, empty_states: {}};
        fallback.progress_recent = "Observatory refresh failed: " + error;
        render(fallback);
      }
    }
    refresh();
    if (STATE_URL) setInterval(refresh, 2500);
  </script>
</body>
</html>
"""

def render_html(snapshot: dict[str, Any], *, live: bool) -> str:
    initial_json = json.dumps(snapshot, sort_keys=True).replace("</", "<\\/")
    state_url = '"/state.json"' if live else "null"
    return (
        REPLAY_HTML_TEMPLATE.replace("__INITIAL_STATE__", initial_json)
        .replace("__STATE_URL__", state_url)
    )
