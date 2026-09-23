"use strict";

const tokenFromHash = window.location.hash.slice(1);
if (tokenFromHash) {
  sessionStorage.setItem("wb-setup-token", tokenFromHash);
  history.replaceState(null, "", window.location.pathname);
}
const token = tokenFromHash || sessionStorage.getItem("wb-setup-token") || "";

let manifest = null;
let snapshot = null;
let activeStage = sessionStorage.getItem("wb-setup-stage") || "";
let viewMode = sessionStorage.getItem("wb-setup-view") || "client";
let currentGuideStepId = "";
let jobTimer = null;
let metadataTimer = null;
let automationActive = false;
let stateRefreshTimer = null;
let statePollActive = false;
let connectionFailures = 0;
let connectionOnline = false;
let lastStateRefresh = null;
let guideCheckTimer = null;
let guideCheckActive = false;

const permissionStepIds = [
  "connect.screen-sharing",
  "connect.full-disk-access",
  "connect.accessibility",
  "connect.screen-recording",
  "connect.automation-dialog",
  "connect.remote-login",
  "connect.background-items",
];

const liveCheckIds = new Set([
  "P0-FDA",
  "P0-AX",
  "P0-SCREEN",
  "P0-AUTOMATION",
  "P0-SSH",
  "P0-SCREENSHARING",
  "P0-SLEEP",
]);

const $ = (selector) => document.querySelector(selector);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function api(path, options = {}) {
  const headers = { "X-Wideband-Token": token, ...(options.headers || {}) };
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { ...options, headers });
  let payload;
  try {
    payload = await response.json();
  } catch (_) {
    payload = { error: `Unexpected response (${response.status})` };
  }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function toast(message, timeout = 2800) {
  const node = $("#toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => { node.hidden = true; }, timeout);
}

function savedAtLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Progress saves privately on this Mac.";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 15) return "Saved just now on this Mac · safe to close and resume later.";
  if (seconds < 90) return "Saved about a minute ago on this Mac · safe to close and resume later.";
  if (seconds < 3600) return `Saved ${Math.round(seconds / 60)} minutes ago on this Mac · safe to resume later.`;
  return `Last saved ${date.toLocaleString()} · reopen Wideband Setup to resume here.`;
}

function localTimeLabel(value) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "not recorded yet";
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function allSteps() {
  return manifest.stages.flatMap((stage) => stage.steps);
}

function clientSteps() {
  return allSteps()
    .filter((step) => step.actor === "client" && step.client_guide)
    .map((step, sourceIndex) => ({ step, sourceIndex }))
    .sort((left, right) => {
      const leftPriority = left.step.client_priority ?? 1000;
      const rightPriority = right.step.client_priority ?? 1000;
      return leftPriority - rightPriority || left.sourceIndex - right.sourceIndex;
    })
    .map(({ step }) => step);
}

function immediateClientSteps() {
  return clientSteps().filter((step) => step.client_phase === "now");
}

function stageForStep(stepId) {
  return manifest.stages.find((stage) => stage.steps.some((step) => step.id === stepId));
}

function checkStatus(step) {
  const completed = snapshot.state.completed[step.id];
  if (step.id === "identify.run-bootstrap" && snapshot.facts.bootstrap_ready) {
    return { state: "done", label: "Detected", source: "machine" };
  }

  const checks = step.checks || [];
  if (checks.length) {
    const values = checks.map((id) => snapshot.verification_rollup[id] || "unknown");
    if (values.includes("fail")) return { state: "failed", label: "Needs attention", source: "verification" };
    if (values.every((value) => value === "pass")) {
      if (step.requires_confirmation && !completed) {
        return { state: "pending", label: "Verified — confirm", source: "verification" };
      }
      return { state: "done", label: step.requires_confirmation ? "Verified and confirmed" : "Verified", source: "verification" };
    }
    if (values.includes("skip")) return { state: "skipped", label: "Not checked", source: "verification" };
    return { state: "pending", label: "Awaiting verification", source: "verification" };
  }

  if (completed) return { state: "done", label: "Confirmed", source: completed.source || "human" };

  if (step.action && snapshot.state.action_runs[step.action]) {
    const run = snapshot.state.action_runs[step.action];
    return run.status === "complete"
      ? { state: "done", label: "Complete", source: "action" }
      : { state: "skipped", label: "Review output", source: "action" };
  }
  return { state: "pending", label: "Not complete", source: "none" };
}

function evidenceLabel(status) {
  if (status.state === "failed") return "Machine check needs attention";
  if (status.state === "skipped") return "Waiting for a usable check";
  if (status.state !== "done") {
    return status.source === "verification" ? "Waiting for machine check" : "Waiting for proof";
  }
  if (status.source === "verification" || status.source === "machine") {
    return status.label.includes("confirmed") ? "Machine verified + you confirmed" : "Machine verified";
  }
  if (["human", "interview"].includes(status.source)) return "You confirmed";
  if (status.source === "action" && status.state === "done") return "Installer completed";
  return "Waiting for proof";
}

function responsibilityLabel(step) {
  if (step.actor === "client") return "You approve · Wideband verifies";
  if (step.actor === "machine") return "Wideband installs and verifies";
  if (step.actor === "agent") return "Wideband customizes";
  return "Complete with Wideband";
}

function supportsLiveCheck(step) {
  return (step.checks || []).some((checkId) => liveCheckIds.has(checkId));
}

function requiredSteps() {
  return allSteps().filter((step) => !step.optional);
}

function stageStats(stage) {
  const required = stage.steps.filter((step) => !step.optional);
  const complete = required.filter((step) => checkStatus(step).state === "done").length;
  return { complete, total: required.length };
}

/* -------------------------------------------------------------------------
   Client experience
   ------------------------------------------------------------------------- */

function setView(mode, shouldScroll = true) {
  viewMode = mode === "operator" ? "operator" : "client";
  sessionStorage.setItem("wb-setup-view", viewMode);
  $("#client-view").hidden = viewMode !== "client";
  $("#operator-view").hidden = viewMode !== "operator";
  $("#view-toggle").textContent = viewMode === "client" ? "Operator view" : "Back to client";
  if (shouldScroll) window.scrollTo({ top: 0, behavior: "smooth" });
}

function setConnectionState(online, force = false) {
  if (online) {
    connectionFailures = 0;
    connectionOnline = true;
  } else {
    connectionFailures += 1;
    if (!force && connectionFailures < 2) return;
    connectionOnline = false;
  }
  const pill = $("#connection-pill");
  pill.classList.toggle("offline", !connectionOnline);
  pill.classList.toggle("connecting", false);
  $("#connection-label").textContent = connectionOnline ? "Connected on this Mac" : "Reconnect needed";
  $("#connection-alert").hidden = connectionOnline;
  if (!connectionOnline) {
    $("#live-state").textContent = "Live page disconnected · progress remains saved";
    $("#status-connection-detail").textContent = "This browser is no longer connected to the Wideband setup engine. Reopen the app to continue.";
  }
}

function renderConnection() {
  if (!connectionOnline || !snapshot) return;
  const port = snapshot.connection?.port || window.location.port || "8803";
  const release = snapshot.connection?.release || manifest?.release || "unknown";
  const build = snapshot.connection?.build_id || "development build";
  $("#live-state").textContent = `Live page · connected locally on port ${port}`;
  const proof = snapshot.state.last_verification?.generated_at;
  $("#proof-state").textContent = proof
    ? `Last machine proof · ${localTimeLabel(proof)}`
    : "No machine proof yet · run a readiness check";
  $("#status-connection-detail").textContent = `Connected only on this Mac at 127.0.0.1:${port} · release ${release} · ${build}. The page refreshed ${localTimeLabel(lastStateRefresh)}.`;
  $("#connection-pill").title = `Private local connection · port ${port} · release ${release}`;
}

function openStatusHelp() {
  renderConnection();
  const dialog = $("#status-dialog");
  if (!dialog.open) dialog.showModal();
}

function currentClientStep() {
  return immediateClientSteps().find((step) => checkStatus(step).state !== "done") || null;
}

function renderClientProgress() {
  const steps = immediateClientSteps();
  const complete = steps.filter((step) => checkStatus(step).state === "done").length;
  const percent = steps.length ? Math.round((complete / steps.length) * 100) : 0;
  $("#client-progress-label").textContent = complete === steps.length
    ? "Your first-session approvals are complete"
    : `${complete} of ${steps.length} client actions complete`;
  $("#client-progress-percent").textContent = `${percent}%`;
  $("#client-progress-bar").style.width = `${percent}%`;
  const dots = $("#client-progress-dots");
  dots.replaceChildren(...steps.map((step) => {
    const dot = element("i");
    const status = checkStatus(step).state;
    if (status === "done") dot.className = "done";
    else if (step.id === currentClientStep()?.id) dot.className = "current";
    return dot;
  }));
  $("#save-state").textContent = savedAtLabel(snapshot.state.updated_at);
  renderConnection();
}

function renderFocusCard() {
  const steps = immediateClientSteps();
  const step = currentClientStep();
  const action = $("#focus-action");
  const note = $("#focus-note");
  if (!step) {
    $("#focus-count").textContent = "Client handoff ready";
    $("#focus-stage").textContent = "Saved";
    $("#focus-icon").textContent = "✓";
    $("#focus-eyebrow").textContent = "Your part is complete";
    $("#focus-title").textContent = "Wideband can take it from here.";
    $("#focus-description").textContent = "Your account approvals and macOS permissions are saved. Keep this Mac plugged in and online while Wideband finishes the custom layer.";
    action.hidden = true;
    note.hidden = false;
    note.textContent = "The remaining phone and messaging proofs happen with your Wideband operator after the private surfaces are ready.";
    $("#client-complete").hidden = false;
    return;
  }

  const index = steps.findIndex((item) => item.id === step.id);
  const stage = stageForStep(step.id);
  $("#focus-count").textContent = `Client step ${index + 1} of ${steps.length}`;
  $("#focus-stage").textContent = stage?.title || "Setup";
  $("#focus-icon").textContent = String(index + 1).padStart(2, "0");
  $("#focus-eyebrow").textContent = step.client_guide.eyebrow || "Your action";
  $("#focus-title").textContent = step.title;
  $("#focus-description").textContent = step.client_guide.intro || step.description;
  note.hidden = !step.note;
  note.textContent = step.note || "";
  action.hidden = false;
  action.textContent = "Continue setup";
  action.append(element("span", "", "→"));
  action.onclick = () => openGuide(step.id);
  $("#client-complete").hidden = true;
}

function renderClientQueue() {
  const steps = immediateClientSteps();
  const queue = $("#client-queue");
  queue.replaceChildren(...steps.map((step, index) => {
    const status = checkStatus(step);
    const button = element("button", `queue-item ${status.state}`);
    button.type = "button";
    const topline = element("div", "queue-num");
    topline.append(
      element("span", "", status.state === "done" ? "✓ COMPLETE" : String(index + 1).padStart(2, "0")),
      element("span", "", (step.checks || []).length ? "WIDEBAND CHECKS" : "YOU CONFIRM"),
    );
    button.append(topline, element("h3", "", step.title), element("p", "", evidenceLabel(status)));
    button.addEventListener("click", () => openGuide(step.id));
    return button;
  }));
}

function renderHandoff() {
  const steps = clientSteps().filter((step) => step.client_phase !== "now");
  const list = $("#handoff-list");
  list.replaceChildren(...steps.map((step, index) => {
    const status = checkStatus(step);
    const button = element("button", `handoff-item ${status.state}`);
    button.type = "button";
    const number = element("span", "", status.state === "done" ? "✓" : String(index + 1).padStart(2, "0"));
    const copy = element("div");
    copy.append(
      element("strong", "", step.title),
      element("small", "", `${evidenceLabel(status)} · ${step.client_phase === "later" ? "Scheduled follow-up" : "Complete with your Wideband operator"}`),
    );
    button.append(number, copy, element("span", "", "→"));
    button.addEventListener("click", () => openGuide(step.id));
    return button;
  }));
}

function renderCompletion() {
  const section = $("#client-complete");
  const clientReady = !currentClientStep();
  section.hidden = !clientReady;
  if (!clientReady) return;

  const verification = snapshot.state.last_verification?.summary;
  const profile = allSteps().find((step) => step.id === "identify.review-agent-profile");
  const profileReady = profile && checkStatus(profile).state === "done";
  const handoff = readinessForSteps(clientSteps().filter((step) => step.client_phase !== "now"));
  const machineReady = verification && verification.failed === 0;

  $("#completion-title").textContent = machineReady && profileReady && handoff.state === "ready"
    ? "This Wideband build is ready."
    : "Your approvals are complete.";
  $("#completion-summary").textContent = machineReady
    ? "The machine foundation is verified. The remaining cards below distinguish custom-profile review and real-world handoff proofs."
    : "Your work is saved. Wideband can continue machine repair, customization, and final verification without asking you to repeat these approvals.";
  $("#completion-machine").textContent = verification
    ? `${verification.passed} passed · ${verification.failed} need attention · ${verification.skipped} deferred`
    : "Machine verification has not run yet";
  $("#completion-profile").textContent = profileReady
    ? "Approved and installed privately"
    : "Complete the custom operator profile with Wideband";
  $("#completion-handoff").textContent = `${handoff.done} of ${handoff.total} phone, messaging, and scheduled proofs complete`;
}

function readinessForSteps(steps) {
  const statuses = steps.map((step) => checkStatus(step));
  const done = statuses.filter((status) => status.state === "done").length;
  const failed = statuses.filter((status) => status.state === "failed").length;
  const state = failed ? "attention" : (steps.length > 0 && done === steps.length ? "ready" : "waiting");
  return {
    state,
    done,
    total: steps.length,
    next: steps.find((step) => checkStatus(step).state !== "done") || steps[0] || null,
  };
}

function readinessCard(eyebrow, title, state, detail, onOpen) {
  const card = element("button", `readiness-card ${state}`);
  card.type = "button";
  const head = element("div", "readiness-card-head");
  head.append(
    element("span", "", eyebrow),
    element("span", "readiness-status", state === "ready" ? "✓" : state === "attention" ? "!" : "·"),
  );
  card.append(head, element("h3", "", title), element("p", "", detail));
  if (onOpen) card.addEventListener("click", onOpen);
  return card;
}

function renderReadiness() {
  const install = snapshot.state.action_runs.run_install;
  const deactivated = snapshot.facts.deactivated;
  const verification = snapshot.state.last_verification?.summary;
  const foundationState = deactivated
    ? "attention"
    : install?.status === "needs_attention" || (verification?.failed || 0) > 0
      ? "attention"
      : install?.status === "complete" && snapshot.facts.wideband_agent_installed && verification
        ? "ready"
        : "waiting";
  const foundationDetail = deactivated
    ? "Wideband services are deactivated. Repair restores the managed runtime."
    : install?.status === "complete"
      ? verification
        ? `${verification.passed} checks passed · ${verification.failed} need attention · ${verification.skipped} deferred.`
        : "Installed; the first machine proof is still pending."
      : install?.status === "needs_attention"
        ? "The installation finished with an item that needs review."
        : "The managed runtime is being prepared.";

  const permissions = allSteps().filter((step) => permissionStepIds.includes(step.id));
  const permissionState = readinessForSteps(permissions);
  const approvals = immediateClientSteps().filter((step) => !permissionStepIds.includes(step.id));
  const approvalState = readinessForSteps(approvals);
  const proofs = clientSteps().filter((step) => step.client_phase !== "now");
  const proofState = readinessForSteps(proofs);

  $("#readiness-grid").replaceChildren(
    readinessCard("Machine", "Wideband foundation", foundationState, foundationDetail, openSupport),
    readinessCard(
      "macOS",
      "Permissions and support",
      permissionState.state,
      `${permissionState.done} of ${permissionState.total} approvals verified or confirmed.`,
      permissionState.next ? () => openGuide(permissionState.next.id) : null,
    ),
    readinessCard(
      "Client",
      "Accounts and profile",
      approvalState.state,
      `${approvalState.done} of ${approvalState.total} client-owned steps complete.`,
      approvalState.next ? () => openGuide(approvalState.next.id) : null,
    ),
    readinessCard(
      "Handoff",
      "Real-world proofs",
      proofState.state,
      `${proofState.done} of ${proofState.total} phone, messaging, and scheduled proofs observed.`,
      proofState.next ? () => openGuide(proofState.next.id) : null,
    ),
  );

  const states = [foundationState, permissionState.state, approvalState.state];
  if (deactivated) {
    $("#readiness-summary").textContent = "Wideband is safely deactivated. Use Repair Wideband to restore the runtime.";
  } else if (states.includes("attention")) {
    $("#readiness-summary").textContent = "At least one area needs attention. Select its card for the exact next action.";
  } else if (states.every((state) => state === "ready")) {
    $("#readiness-summary").textContent = proofState.state === "ready"
      ? "This Mac has passed setup and the real-world handoff proofs."
      : "The first-session setup is ready. Final real-world proofs remain visible for handoff.";
  } else {
    $("#readiness-summary").textContent = "Setup is in progress. Every completed action is saved automatically.";
  }
}

function machineRow(done, title, detail, running = false) {
  const item = element("li", done ? "done" : "");
  const symbol = element("span", running ? "mini-spinner" : "", done ? "✓" : running ? "" : "·");
  const copy = element("div");
  copy.append(element("strong", "", title), element("small", "", detail));
  item.append(symbol, copy);
  return item;
}

function renderMachineState() {
  const list = $("#machine-list");
  const install = snapshot.state.action_runs.run_install;
  const running = snapshot.jobs.find((job) => job.status === "running");
  const verification = snapshot.state.last_verification?.summary;
  const bootstrapDone = snapshot.facts.bootstrap_ready;
  const bootstrapStatus = snapshot.facts.bootstrap_status || "starting";
  const deactivated = snapshot.facts.deactivated;
  const installDone = install?.status === "complete" && snapshot.facts.wideband_agent_installed && !deactivated;
  const attention = deactivated || install?.status === "needs_attention" || (verification?.failed || 0) > 0;

  list.replaceChildren(
    machineRow(
      bootstrapDone,
      "Core tools",
      bootstrapDone
        ? "Homebrew, Python, and the setup runtime are ready."
        : bootstrapStatus === "needs_admin_password"
          ? "Action needed: enter your Mac password in Terminal, then return here."
          : bootstrapStatus === "needs_developer_tools"
            ? "Action needed: approve Apple's Command Line Tools installer; Wideband checks it automatically."
            : bootstrapStatus === "needs_developer_tools_selection"
              ? "Apple's tools are installed but no longer selected. Terminal shows the exact reselect command."
            : bootstrapStatus === "needs_homebrew_ownership"
              ? "Homebrew was left by another ownership context. Terminal shows the verified repair boundary."
          : bootstrapStatus === "collecting_identity"
            ? "Complete the Wideband setup popup currently on screen."
            : bootstrapStatus === "needs_attention"
              ? "The core tool install needs review in Terminal."
              : "Homebrew and the core tools are installing in Terminal.",
      !bootstrapDone && !["needs_admin_password", "needs_developer_tools", "needs_developer_tools_selection", "needs_homebrew_ownership", "collecting_identity", "needs_attention"].includes(bootstrapStatus),
    ),
    machineRow(installDone, "Wideband layer", installDone ? "Agent context, workspace, and standing services installed." : deactivated ? "Managed services are deactivated; Repair Wideband can restore them." : running?.action === "run_install" ? "Installing automatically now." : attention ? "An operator will review the installation output." : "Queued behind the core tools.", running?.action === "run_install"),
    machineRow(Boolean(verification) && !verification.failed, "Machine checks", verification ? `${verification.passed} passed · ${verification.failed} need attention · ${verification.skipped} deferred` : "Checks run automatically after installation.", running?.action?.includes("verify")),
    machineRow(snapshot.facts.personalized, "Client build profile", snapshot.facts.personalized ? "This installer was prepared for this client." : "Generic pilot build; the operator should verify identity values."),
    machineRow(snapshot.facts.setup_app_installed, "Resume app", snapshot.facts.setup_app_installed ? "Wideband Setup is installed in your Applications folder." : "The setup app is being copied to Applications."),
  );

  if (snapshot.facts.terminal_hosted) {
    $("#runtime-reminder-title").textContent = "Leave Terminal open for this first installation.";
    $("#runtime-reminder-detail").textContent = "It supplies the administrator-approved tool installation. Wideband Setup remains your guide in front.";
  } else if (snapshot.facts.embedded_mode) {
    $("#runtime-reminder-title").textContent = "Keep Wideband Setup open.";
    $("#runtime-reminder-detail").textContent = "The private engine is running quietly on this Mac; no browser or Terminal knowledge is required.";
  } else {
    $("#runtime-reminder-title").textContent = "Keep this guide open.";
    $("#runtime-reminder-detail").textContent = "Progress is saved automatically. Reopen Wideband Setup at any time to resume.";
  }

  const state = $("#machine-state");
  const badge = $("#build-badge");
  badge.classList.remove("complete", "attention");
  state.classList.remove("attention");
  if (!bootstrapDone && bootstrapStatus === "needs_admin_password") {
    state.textContent = "Your action";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Enter your Mac password in Terminal";
    badge.querySelector("small").textContent = "No dots appear while you type. Press Return, then come back to this guide.";
  } else if (!bootstrapDone && bootstrapStatus === "needs_developer_tools") {
    state.textContent = "Your action";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Approve Apple Command Line Tools";
    badge.querySelector("small").textContent = "This is smaller than full Xcode. Select Install in Apple's dialog; Wideband detects completion automatically.";
  } else if (!bootstrapDone && bootstrapStatus === "needs_developer_tools_selection") {
    state.textContent = "Your action";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Reselect Apple Command Line Tools";
    badge.querySelector("small").textContent = "Review the exact sudo command in Terminal, run it in a new Terminal window, then reopen Wideband Setup.";
  } else if (!bootstrapDone && bootstrapStatus === "needs_homebrew_ownership") {
    state.textContent = "Operator review";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Homebrew ownership needs a safe review";
    badge.querySelector("small").textContent = "Review the two scoped commands in Terminal, run them in a new Terminal window, then reopen Wideband Setup. Never use a blind broad chown.";
  } else if (!bootstrapDone && bootstrapStatus === "needs_attention") {
    state.textContent = "Review Terminal";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "The core tool install needs attention";
    badge.querySelector("small").textContent = "Terminal has the exact error. Your saved guide and approvals are safe.";
  } else if (deactivated) {
    state.textContent = "Deactivated";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Wideband services are paused";
    badge.querySelector("small").textContent = "Client work and setup history remain intact; repair is available in Setup tools.";
  } else if (attention) {
    state.textContent = "Operator review";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Wideband is reviewing a check";
    badge.querySelector("small").textContent = "Continue your guided steps; machine issues stay in operator view.";
  } else if (installDone && verification) {
    state.textContent = "Foundation ready";
    badge.classList.add("complete");
    badge.querySelector("strong").textContent = "Your machine foundation is ready";
    badge.querySelector("small").textContent = "Wideband is preserving your progress and finishing the custom layer.";
  } else {
    state.textContent = running ? "Installing" : "Preparing";
    badge.querySelector("strong").textContent = "Preparing your machine";
    badge.querySelector("small").textContent = "You can work through the guide while installation runs.";
  }
}

function renderClient() {
  const name = (snapshot.facts.client_name || snapshot.state.interview?.name || "").trim().split(/\s+/)[0];
  $("#client-greeting").textContent = name ? `${name}, your AI` : "Your AI";
  renderClientProgress();
  renderFocusCard();
  renderClientQueue();
  renderHandoff();
  renderMachineState();
  renderReadiness();
  renderCompletion();
}

function guideActions(step) {
  if (step.client_guide.actions) return step.client_guide.actions;
  if (!step.action) return [];
  return [{ action: step.action, label: step.client_guide.open_label || actionLabel(step.action) }];
}

function stopGuideMonitoring() {
  clearTimeout(guideCheckTimer);
  guideCheckTimer = null;
}

function mergeLiveCheckResult(result) {
  snapshot.state.live_checks = result.live_checks;
  snapshot.state.last_verification = result.verification;
  snapshot.verification_rollup = result.verification_rollup;
  snapshot.facts.live_checks_at = result.live_checks.generated_at;
  snapshot.state.updated_at = result.live_checks.generated_at;
}

async function monitorGuideStep(stepId) {
  stopGuideMonitoring();
  if (guideCheckActive || !$("#guide-dialog").open || currentGuideStepId !== stepId) return;
  const step = allSteps().find((item) => item.id === stepId);
  if (!step || !supportsLiveCheck(step)) return;
  guideCheckActive = true;
  try {
    const result = await api("/api/live-checks", { method: "POST", body: {} });
    mergeLiveCheckResult(result);
    renderClient();
    const status = checkStatus(step);
    const message = $("#guide-message");
    if (status.state === "done") {
      message.className = "guide-message success";
      message.textContent = `${evidenceLabel(status)}. Return to Wideband Setup and select Continue.`;
      $("#guide-confirm").textContent = "Continue";
      $("#guide-confirm").append(element("span", "", "→"));
      return;
    }
    const failures = latestChecks(step.checks || [])
      .filter((check) => check.status === "fail")
      .map((check) => check.message)
      .slice(0, 1);
    message.className = "guide-message";
    message.textContent = failures.length
      ? `Waiting for macOS approval · ${failures[0]} This updates automatically.`
      : "Waiting for macOS to publish the new setting. This updates automatically.";
  } catch (error) {
    $("#guide-message").className = "guide-message error";
    $("#guide-message").textContent = `Automatic check paused: ${error.message}`;
  } finally {
    guideCheckActive = false;
  }
  if ($("#guide-dialog").open && currentGuideStepId === stepId && checkStatus(step).state !== "done") {
    guideCheckTimer = setTimeout(() => monitorGuideStep(stepId), 2800);
  }
}

function startGuideMonitoring(stepId, immediate = false) {
  stopGuideMonitoring();
  guideCheckTimer = setTimeout(() => monitorGuideStep(stepId), immediate ? 250 : 1200);
}

function openGuide(stepId) {
  const step = allSteps().find((item) => item.id === stepId);
  if (!step?.client_guide) return;
  currentGuideStepId = stepId;
  const steps = clientSteps();
  const index = steps.findIndex((item) => item.id === stepId);
  const guide = step.client_guide;
  const status = checkStatus(step);
  $("#guide-progress-label").textContent = `Client step ${index + 1} of ${steps.length}`;
  $("#guide-progress-bar").style.width = `${Math.round(((index + 1) / steps.length) * 100)}%`;
  $("#guide-owner").textContent = responsibilityLabel(step);
  $("#guide-eyebrow").textContent = guide.eyebrow || "Your action";
  $("#guide-title").textContent = step.title;
  $("#guide-intro").textContent = guide.intro || step.description;
  $("#guide-purpose").textContent = guide.purpose || guide.intro || step.description;
  $("#guide-success").textContent = guide.success || ((step.checks || []).length
    ? "Wideband's local check reports this permission or service as ready."
    : "You confirm the account or action is complete, and the guide saves your place.");
  $("#guide-instructions").replaceChildren(...(guide.instructions || [step.description]).map((item) => element("li", "", item)));

  const privacy = $("#guide-privacy");
  privacy.hidden = !guide.privacy;
  privacy.querySelector("p").textContent = guide.privacy || "";
  $("#guide-message").textContent = status.state === "done" ? `✓ ${evidenceLabel(status)}. You can review or check it again.` : "";
  $("#guide-message").className = status.state === "done" ? "guide-message success" : "guide-message";

  const actions = $("#guide-open-actions");
  actions.replaceChildren(...guideActions(step).map((item) => {
    const button = element("button", "", item.label || actionLabel(item.action));
    button.type = "button";
    button.addEventListener("click", () => invokeGuideAction(item.action, button, item.message));
    return button;
  }));

  const confirm = $("#guide-confirm");
  confirm.disabled = false;
  confirm.textContent = status.state === "done"
    ? "Continue"
    : guide.confirm_label || ((step.checks || []).length ? "Check this step" : "I finished this");
  confirm.append(element("span", "", "→"));
  confirm.onclick = () => completeGuideStep(step);
  $("#guide-later").textContent = status.state === "done" ? "Close" : "Do this later";

  const dialog = $("#guide-dialog");
  if (!dialog.open) dialog.showModal();
  if (supportsLiveCheck(step) && status.state !== "done") startGuideMonitoring(step.id, false);
}

async function invokeGuideAction(action, button, openedMessage = "") {
  if (action === "open_interview") {
    $("#guide-dialog").close();
    openInterview();
    return;
  }
  button.disabled = true;
  const message = $("#guide-message");
  message.className = "guide-message";
  message.textContent = "Opening the right place…";
  try {
    const result = await api(`/api/actions/${action}`, { method: "POST", body: {} });
    if (result.opened) {
      message.textContent = openedMessage || "Opened. Follow the numbered instructions, then return here.";
      const step = allSteps().find((item) => item.id === currentGuideStepId);
      if (step && supportsLiveCheck(step)) startGuideMonitoring(step.id, true);
    } else if (result.id) {
      message.textContent = "Wideband is running that step now…";
      await waitForJob(result.id, false);
      await refreshState();
      message.textContent = "That action finished. Review the result, then continue.";
    }
  } catch (error) {
    message.className = "guide-message error";
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function waitForCurrentJob() {
  const running = snapshot.jobs.find((job) => job.status === "running");
  if (!running) return;
  $("#guide-message").textContent = "Wideband is finishing the machine installation, then this check will run automatically…";
  await waitForJob(running.id, false);
  await refreshState();
}

async function completeGuideStep(step) {
  const button = $("#guide-confirm");
  const message = $("#guide-message");
  if (checkStatus(step).state === "done") {
    stopGuideMonitoring();
    $("#guide-dialog").close();
    const next = currentClientStep();
    if (next && step.client_phase === "now") setTimeout(() => openGuide(next.id), 220);
    return;
  }
  stopGuideMonitoring();
  button.disabled = true;
  message.className = "guide-message";
  message.textContent = (step.checks || []).length ? "Checking this Mac…" : "Saving your progress…";
  try {
    await waitForCurrentJob();
    const checks = step.checks || [];
    if (!checks.length || step.requires_confirmation) {
      await api(`/api/steps/${encodeURIComponent(step.id)}`, { method: "POST", body: { complete: true } });
    }
    if (checks.length) {
      if (supportsLiveCheck(step)) {
        const result = await api("/api/live-checks", { method: "POST", body: {} });
        mergeLiveCheckResult(result);
      } else {
        const job = await api("/api/actions/run_verify_quick", { method: "POST", body: {} });
        await waitForJob(job.id, false);
      }
    }
    await refreshState();
    const status = checkStatus(step);
    if (status.state !== "done") {
      message.className = "guide-message error";
      const failures = latestChecks(step.checks || [])
        .filter((check) => check.status === "fail")
        .map((check) => check.message)
        .slice(0, 2);
      message.textContent = failures.length
        ? `Not verified yet: ${failures.join(" ")} Review the numbered instructions, then retry.`
        : "The action is saved, but macOS has not exposed a verifiable result yet. Wait a moment, review the instructions, then retry.";
      button.textContent = "Try check again";
      button.append(element("span", "", "→"));
      if (supportsLiveCheck(step)) startGuideMonitoring(step.id, false);
      return;
    }
    message.className = "guide-message success";
    message.textContent = `${evidenceLabel(status)}. Moving to your next step…`;
    await delay(450);
    $("#guide-dialog").close();
    const next = currentClientStep();
    if (next && step.client_phase === "now") setTimeout(() => openGuide(next.id), 220);
  } catch (error) {
    message.className = "guide-message error";
    message.textContent = error.message;
    button.textContent = "Try again";
    button.append(element("span", "", "→"));
    if (supportsLiveCheck(step)) startGuideMonitoring(step.id, false);
  } finally {
    button.disabled = false;
  }
}

function showWelcome(force = false) {
  const key = `wb-setup-client-welcome-${manifest.release}`;
  if (!force && localStorage.getItem(key) === "1") return;
  const completed = immediateClientSteps().filter((step) => checkStatus(step).state === "done").length;
  $("#welcome-personalized").textContent = completed
    ? `Welcome back. ${completed} client action${completed === 1 ? " is" : "s are"} already saved; Wideband will resume at the next unfinished step.`
    : snapshot.facts.personalized
      ? "Your Wideband build profile is already loaded. The installer will do the machine work and pause only when macOS or an account needs you."
      : "This pilot will guide the machine work and every approval. Your Wideband operator should verify the build identity before final handoff.";
  $("#welcome-begin").textContent = completed ? "Resume guided setup" : "Begin guided setup";
  $("#welcome-begin").append(element("span", "", "→"));
  const dialog = $("#welcome-dialog");
  if (!dialog.open) dialog.showModal();
}

function dismissWelcome(begin = false) {
  localStorage.setItem(`wb-setup-client-welcome-${manifest.release}`, "1");
  $("#welcome-dialog").close();
  if (begin) {
    const step = currentClientStep();
    if (step) setTimeout(() => openGuide(step.id), 180);
  }
}

async function runAutomaticMachineWork() {
  if (automationActive || !snapshot.facts.client_mode || !snapshot.facts.bootstrap_ready) return;
  automationActive = true;
  try {
    let running = snapshot.jobs.find((job) => job.status === "running");
    if (running) {
      await waitForJob(running.id, false);
      await refreshState();
    }
    const install = snapshot.state.action_runs.run_install;
    if (!install || install.status === "interrupted") {
      const job = await api("/api/actions/run_install", { method: "POST", body: {} });
      await refreshState();
      await waitForJob(job.id, false);
      await refreshState();
      toast("Wideband machine layer installed");
    } else if (!snapshot.state.last_verification && install.status === "complete") {
      const job = await api("/api/actions/run_verify_quick", { method: "POST", body: {} });
      await waitForJob(job.id, false);
      await refreshState();
    }
  } catch (error) {
    toast(`Machine setup needs operator review: ${error.message}`, 5200);
  } finally {
    automationActive = false;
  }
}

/* -------------------------------------------------------------------------
   Readiness, support, and recovery
   ------------------------------------------------------------------------- */

function openSupport() {
  $("#support-message").textContent = "";
  $("#support-message").className = "support-message";
  const dialog = $("#support-dialog");
  if (!dialog.open) dialog.showModal();
}

async function runSupportJob(action, button, pendingText, completeText) {
  const message = $("#support-message");
  button.disabled = true;
  message.className = "support-message";
  message.textContent = pendingText;
  try {
    const result = await api(`/api/actions/${action}`, { method: "POST", body: {} });
    showJob(result);
    const job = await waitForJob(result.id, true);
    await refreshState();
    if (job.status === "complete") {
      message.textContent = completeText;
    } else {
      message.className = "support-message error";
      message.textContent = "The task finished, but something needs attention. The result panel has the exact check output.";
    }
    return job;
  } catch (error) {
    message.className = "support-message error";
    message.textContent = error.message;
    return null;
  } finally {
    button.disabled = false;
  }
}

async function runReadinessCheck(button = $("#readiness-check")) {
  const dialogWasOpen = $("#support-dialog").open;
  if (!dialogWasOpen) openSupport();
  await runSupportJob(
    "run_verify_quick",
    button,
    "Running a fresh read-only check…",
    "Readiness refreshed. Select any area that still needs attention.",
  );
}

async function repairWideband(button = $("#support-repair")) {
  await runSupportJob(
    "run_install",
    button,
    "Reconciling the Wideband runtime without replacing client-owned work…",
    "Repair complete. Managed files and services were reconciled and checked.",
  );
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const area = element("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  const copied = document.execCommand("copy");
  area.remove();
  if (!copied) throw new Error("The browser could not copy the summary. Export the support bundle instead.");
}

async function copyDiagnostics() {
  const button = $("#support-copy");
  const message = $("#support-message");
  button.disabled = true;
  message.className = "support-message";
  message.textContent = "Preparing a redacted summary…";
  try {
    const result = await api("/api/support-summary");
    await copyText(result.text);
    message.textContent = "Redacted diagnostics copied. Credentials, profile answers, identity values, and raw logs were excluded.";
  } catch (error) {
    message.className = "support-message error";
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function exportDiagnostics() {
  const button = $("#support-export");
  const message = $("#support-message");
  button.disabled = true;
  message.className = "support-message";
  message.textContent = "Creating the redacted ZIP…";
  try {
    const result = await api("/api/support-bundle", { method: "POST", body: {} });
    await refreshState();
    message.textContent = `Support bundle created and revealed in Finder: ${result.path}`;
  } catch (error) {
    message.className = "support-message error";
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function openDeactivation() {
  $("#support-dialog").close();
  $("#deactivate-confirmation").value = "";
  $("#deactivate-apply").disabled = true;
  $("#deactivate-message").textContent = "";
  $("#deactivate-message").className = "support-message";
  $("#deactivate-dialog").showModal();
}

async function deactivateWideband() {
  const button = $("#deactivate-apply");
  const message = $("#deactivate-message");
  button.disabled = true;
  message.className = "support-message";
  message.textContent = "Stopping managed jobs and creating a recovery copy…";
  try {
    const result = await api("/api/deactivate", {
      method: "POST",
      body: { confirm: $("#deactivate-confirmation").value },
    });
    await refreshState();
    $("#deactivate-dialog").close();
    openSupport();
    $("#support-message").textContent = `Wideband services are deactivated. ${result.moved_count} managed item${result.moved_count === 1 ? " was" : "s were"} moved to a private recovery folder. Repair Wideband can restore the runtime.`;
  } catch (error) {
    message.className = "support-message error";
    message.textContent = error.message;
    button.disabled = $("#deactivate-confirmation").value !== "DEACTIVATE";
  }
}

/* -------------------------------------------------------------------------
   Operator view
   ------------------------------------------------------------------------- */

function renderProgress() {
  const required = requiredSteps();
  const complete = required.filter((step) => checkStatus(step).state === "done").length;
  const percent = required.length ? Math.round((complete / required.length) * 100) : 0;
  $("#progress-label").textContent = `${complete} of ${required.length} complete`;
  $("#progress-percent").textContent = `${percent}%`;
  $("#progress-bar").style.width = `${percent}%`;
}

function renderNav() {
  const nav = $("#stage-nav");
  nav.replaceChildren();
  manifest.stages.forEach((stage, index) => {
    const stats = stageStats(stage);
    const button = element("button", "nav-stage");
    button.type = "button";
    if (stage.id === activeStage) button.classList.add("active");
    if (stats.total && stats.complete === stats.total) button.classList.add("complete");
    button.append(
      element("span", "nav-num", stats.complete === stats.total ? "✓" : String(index + 1).padStart(2, "0")),
      element("span", "nav-label", stage.title),
      element("span", "nav-count", `${stats.complete}/${stats.total}`),
    );
    button.addEventListener("click", () => {
      activeStage = stage.id;
      sessionStorage.setItem("wb-setup-stage", activeStage);
      renderOperator();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    nav.append(button);
  });
}

function actionLabel(action) {
  const labels = {
    open_interview: "Open interview",
    open_claude_auth: "Open Claude sign-in",
    open_messages: "Open Messages",
    open_mail: "Open Mail",
    request_accessibility: "Request Accessibility",
    request_full_disk_access: "Show Wideband Agent",
    request_messages_automation: "Show permission prompt",
    request_screen_recording: "Request Screen Access",
    reveal_wideband_agent: "Reveal Wideband Agent",
    generate_build_record: "Generate record",
    run_install: "Install",
    run_doctor: "Create report",
  };
  if (labels[action]) return labels[action];
  if (action.startsWith("open_")) return "Open";
  if (action.includes("verify")) return "Run checks";
  return "Run";
}

function latestChecks(checkIds) {
  const report = snapshot.state.last_verification;
  if (!report) return [];
  const wanted = new Set(checkIds || []);
  return (report.checks || []).filter((check) => wanted.has(check.id));
}

function statusSymbol(status) {
  if (status.state === "done") return "✓";
  if (status.state === "failed") return "!";
  if (status.state === "skipped") return "~";
  return "";
}

function renderStep(step, index) {
  const status = checkStatus(step);
  const card = element("article", `step ${status.state}`);
  const canConfirm = ["guided", "interview"].includes(step.type)
    && (!(step.checks || []).length || step.requires_confirmation)
    && step.id !== "identify.operator-interview";
  const statusButton = element("button", `step-status${canConfirm ? " confirmable" : ""}`, statusSymbol(status));
  statusButton.type = "button";
  statusButton.title = canConfirm
    ? (status.state === "done" && status.source === "human" ? "Mark incomplete" : "Confirm this human step")
    : status.label;
  statusButton.setAttribute("aria-label", statusButton.title);
  if (!canConfirm) statusButton.disabled = true;
  if (canConfirm) {
    statusButton.addEventListener("click", async () => {
      const manuallyComplete = Boolean(snapshot.state.completed[step.id]);
      try {
        await api(`/api/steps/${encodeURIComponent(step.id)}`, { method: "POST", body: { complete: !manuallyComplete } });
        await refreshState();
      } catch (error) {
        toast(error.message);
      }
    });
  }

  const copy = element("div", "step-copy");
  const heading = element("h3", "", step.title);
  heading.append(element("span", `tag ${step.actor}`, step.actor));
  if (step.optional) heading.append(element("span", "tag optional", "optional"));
  copy.append(heading, element("p", "", step.description));
  if (step.note) copy.append(element("div", "note", step.note));
  if (step.command) {
    const command = element("div", "command");
    command.append(element("code", "", step.command));
    const copyButton = element("button", "copy", "copy");
    copyButton.type = "button";
    copyButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(step.command);
      copyButton.textContent = "copied";
      setTimeout(() => { copyButton.textContent = "copy"; }, 1000);
    });
    command.append(copyButton);
    copy.append(command);
  }
  if (step.checks && step.checks.length) {
    const detail = element("div", "check-detail");
    step.checks.forEach((id) => {
      const value = snapshot.verification_rollup[id] || "unknown";
      const pill = element("span", `check-pill ${value}`, `${id} · ${value}`);
      const messages = latestChecks([id]).map((check) => check.message);
      if (messages.length) pill.title = messages.join("\n");
      detail.append(pill);
    });
    copy.append(detail);
    for (const failure of latestChecks(step.checks).filter((check) => check.status === "fail")) {
      copy.append(element("div", "failure", `[${failure.id}] ${failure.message}`));
    }
  }

  const actions = element("div", "step-actions");
  if (step.action) {
    const action = element("button", "action-button", actionLabel(step.action));
    action.type = "button";
    action.addEventListener("click", () => handleAction(step.action, action));
    actions.append(action);
  }
  card.append(statusButton, copy, actions);
  card.dataset.index = String(index);
  return card;
}

function renderStage() {
  let stage = manifest.stages.find((item) => item.id === activeStage);
  if (!stage) {
    stage = manifest.stages.find((item) => {
      const stats = stageStats(item);
      return stats.complete < stats.total;
    }) || manifest.stages[0];
    activeStage = stage.id;
  }
  const stats = stageStats(stage);
  $("#stage-eyebrow").textContent = stage.eyebrow;
  $("#stage-title").textContent = stage.title;
  $("#stage-description").textContent = stage.description;
  $("#stage-count").textContent = `${stats.complete} / ${stats.total} required`;
  $("#steps").replaceChildren(...stage.steps.map(renderStep));
}

function renderDeviations() {
  const list = $("#deviation-list");
  list.replaceChildren(...snapshot.state.deviations.map((item) => element("li", "", `${item.text} · ${new Date(item.created_at).toLocaleString()}`)));
}

function renderMetadata() {
  const values = snapshot.state.metadata;
  if (document.activeElement !== $("#meta-machine")) $("#meta-machine").value = values.machine || "";
  if (document.activeElement !== $("#meta-operator")) $("#meta-operator").value = values.operator || "";
  if (document.activeElement !== $("#meta-date")) $("#meta-date").value = values.build_date || "";
}

function renderOperator() {
  renderNav();
  renderStage();
  renderProgress();
  renderDeviations();
  renderMetadata();
}

function render() {
  renderClient();
  renderOperator();
  setView(viewMode, false);
}

async function refreshState() {
  try {
    snapshot = await api("/api/state");
    lastStateRefresh = new Date();
    setConnectionState(true);
    render();
    runAutomaticMachineWork();
  } catch (error) {
    setConnectionState(false);
    throw error;
  }
}

async function pollState() {
  if (statePollActive) return;
  statePollActive = true;
  clearTimeout(stateRefreshTimer);
  try {
    await refreshState();
  } catch (_) {
    // The persistent reconnect banner gives recovery instructions. Polling
    // continues so the page heals automatically if the local server returns.
  } finally {
    statePollActive = false;
    stateRefreshTimer = setTimeout(pollState, 3000);
  }
}

async function handleAction(actionName, button) {
  if (actionName === "open_interview") {
    openInterview();
    return;
  }
  if (actionName === "generate_build_record") {
    button.disabled = true;
    try {
      const record = await api("/api/build-record", { method: "POST", body: {} });
      $("#record-path").textContent = `Saved privately at ${record.path}`;
      $("#record-preview").textContent = record.markdown;
      $("#record-dialog").showModal();
      await refreshState();
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
    return;
  }
  button.disabled = true;
  try {
    const result = await api(`/api/actions/${actionName}`, { method: "POST", body: {} });
    if (result.opened) {
      toast("Opened the requested page");
    } else {
      showJob(result);
      pollJob(result.id);
    }
  } catch (error) {
    toast(error.message);
  } finally {
    if (!button.closest(".runner")) button.disabled = false;
  }
}

function showJob(job) {
  $("#runner").hidden = false;
  $("#runner-title").textContent = job.action.replaceAll("_", " ");
  $("#runner-output").textContent = formatJobOutput(job);
  $("#runner-pulse").classList.toggle("still", job.status !== "running");
  $("#runner-output").scrollTop = $("#runner-output").scrollHeight;
}

function formatJobOutput(job) {
  if (!job.output) return "Starting…";
  if (job.action === "run_verify_quick" || job.action === "run_verify_full") {
    try {
      const report = JSON.parse(job.output);
      const summary = report.summary;
      const lines = [`${summary.passed} passed · ${summary.failed} failed · ${summary.skipped} skipped`, ""];
      for (const check of report.checks) {
        const mark = check.status === "pass" ? "✓" : check.status === "fail" ? "✗" : "~";
        lines.push(`${mark} [${check.id}] ${check.message}`);
      }
      return lines.join("\n");
    } catch (_) {
      // Partial streaming output is not JSON yet.
    }
  }
  return job.output;
}

async function waitForJob(jobId, visible = false) {
  while (true) {
    const job = await api(`/api/jobs/${jobId}`);
    if (visible) showJob(job);
    snapshot = await api("/api/state");
    renderClient();
    if (job.status !== "running") return job;
    await delay(800);
  }
}

function pollJob(jobId) {
  clearTimeout(jobTimer);
  api(`/api/jobs/${jobId}`).then(async (job) => {
    showJob(job);
    if (job.status === "running") {
      jobTimer = setTimeout(() => pollJob(jobId), 800);
    } else {
      $("#runner-title").textContent = job.status === "complete" ? "Complete" : "Complete — review needed";
      await refreshState();
      document.querySelectorAll(".action-button, #refresh").forEach((button) => { button.disabled = false; });
    }
  }).catch((error) => {
    $("#runner-output").textContent += `\n${error.message}\n`;
  });
}

/* Interview and build record */

function interviewValues() {
  return Object.fromEntries(new FormData($("#interview-form")).entries());
}

function openInterview() {
  const form = $("#interview-form");
  const values = snapshot.state.interview || {};
  for (const control of form.elements) {
    if (!control.name) continue;
    if (Object.hasOwn(values, control.name)) control.value = values[control.name];
    else if (control.name === "name" && snapshot.facts.client_name) control.value = snapshot.facts.client_name;
  }
  $("#interview-message").textContent = "";
  $("#interview-dialog").showModal();
}

async function previewInterview() {
  const button = $("#interview-preview-button");
  button.disabled = true;
  try {
    const result = await api("/api/interview/preview", { method: "POST", body: interviewValues() });
    $("#interview-preview").textContent = result.markdown;
    $("#interview-lines").textContent = `${result.line_count} / 200 lines`;
    $("#interview-preview-wrap").hidden = false;
  } catch (error) {
    $("#interview-message").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function applyInterview() {
  const button = $("#interview-apply");
  button.disabled = true;
  try {
    const result = await api("/api/interview/apply", { method: "POST", body: interviewValues() });
    $("#interview-message").textContent = `Installed privately · ${result.line_count} lines`;
    await refreshState();
    toast("Your agent profile is installed");
    await delay(650);
    $("#interview-dialog").close();
    const review = allSteps().find((step) => step.id === "identify.review-agent-profile");
    if (review && checkStatus(review).state !== "done") openGuide(review.id);
  } catch (error) {
    $("#interview-message").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function queueMetadataSave() {
  clearTimeout(metadataTimer);
  metadataTimer = setTimeout(async () => {
    try {
      await api("/api/metadata", {
        method: "POST",
        body: {
          machine: $("#meta-machine").value,
          operator: $("#meta-operator").value,
          build_date: $("#meta-date").value,
        },
      });
      snapshot = await api("/api/state");
    } catch (error) {
      toast(error.message);
    }
  }, 450);
}

async function start() {
  if (!token) throw new Error("This installer URL is missing its local access token. Reopen the Wideband Setup app.");
  [manifest, snapshot] = await Promise.all([api("/api/manifest"), api("/api/state")]);
  lastStateRefresh = new Date();
  setConnectionState(true);
  render();
  const running = snapshot.jobs.find((job) => job.status === "running");
  if (running && viewMode === "operator") {
    showJob(running);
    pollJob(running.id);
  }
  if (viewMode === "client") showWelcome();
  runAutomaticMachineWork();
  stateRefreshTimer = setTimeout(pollState, 3000);
}

$("#view-toggle").addEventListener("click", () => setView(viewMode === "client" ? "operator" : "client"));
$("#help").addEventListener("click", () => {
  if (viewMode === "client" && currentClientStep()) openGuide(currentClientStep().id);
  else showWelcome(true);
});
$("#support").addEventListener("click", openSupport);
$("#readiness-tools").addEventListener("click", openSupport);
$("#readiness-check").addEventListener("click", () => runReadinessCheck());
$("#status-help").addEventListener("click", openStatusHelp);
$("#status-legend-help").addEventListener("click", openStatusHelp);
$("#connection-recovery").addEventListener("click", openStatusHelp);
$("#status-close").addEventListener("click", () => $("#status-dialog").close());
$("#status-done").addEventListener("click", () => $("#status-dialog").close());
$("#welcome-begin").addEventListener("click", () => dismissWelcome(true));
$("#welcome-close").addEventListener("click", () => dismissWelcome(false));
$("#guide-close").addEventListener("click", () => { stopGuideMonitoring(); $("#guide-dialog").close(); });
$("#guide-later").addEventListener("click", () => { stopGuideMonitoring(); $("#guide-dialog").close(); });
$("#guide-dialog").addEventListener("close", stopGuideMonitoring);
$("#support-close").addEventListener("click", () => $("#support-dialog").close());
$("#support-check").addEventListener("click", () => runReadinessCheck($("#support-check")));
$("#support-repair").addEventListener("click", () => repairWideband());
$("#support-copy").addEventListener("click", copyDiagnostics);
$("#support-export").addEventListener("click", exportDiagnostics);
$("#support-deactivate").addEventListener("click", openDeactivation);
$("#deactivate-close").addEventListener("click", () => $("#deactivate-dialog").close());
$("#deactivate-cancel").addEventListener("click", () => $("#deactivate-dialog").close());
$("#deactivate-confirmation").addEventListener("input", (event) => {
  $("#deactivate-apply").disabled = event.target.value !== "DEACTIVATE";
});
$("#deactivate-apply").addEventListener("click", deactivateWideband);
$("#runner-close").addEventListener("click", () => { $("#runner").hidden = true; });
$("#interview-preview-button").addEventListener("click", previewInterview);
$("#interview-apply").addEventListener("click", applyInterview);
$("#record-close").addEventListener("click", () => $("#record-dialog").close());
$("#review-client-steps").addEventListener("click", () => $("#queue-section").scrollIntoView({ behavior: "smooth" }));
$("#completion-record").addEventListener("click", (event) => handleAction("generate_build_record", event.currentTarget));
$("#completion-tools").addEventListener("click", openSupport);
for (const input of [$("#meta-machine"), $("#meta-operator"), $("#meta-date")]) input.addEventListener("input", queueMetadataSave);
$("#deviation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("#deviation").value.trim();
  if (!text) return;
  try {
    await api("/api/deviations", { method: "POST", body: { text } });
    $("#deviation").value = "";
    await refreshState();
    toast("Deviation added to the build record");
  } catch (error) {
    toast(error.message);
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && manifest) pollState();
});

start().catch((error) => {
  setConnectionState(false, true);
  $("#focus-title").textContent = "Installer unavailable";
  $("#focus-description").textContent = error.message;
  $("#focus-action").hidden = true;
  $("#stage-title").textContent = "Installer unavailable";
  $("#stage-description").textContent = error.message;
  $("#steps").replaceChildren(element("div", "error-state", error.message));
});
