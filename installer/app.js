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
let onboardingEditing = false;
let onboardingFormInitialized = false;
let welcomeGuideTimer = null;
let phonePortalProof = null;
let phonePortalCheckedRun = "";
let phonePortalCheckActive = false;
let phonePortalCheckPromise = null;
let setupHandoffActive = false;
let setupHandoffError = "";

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

function textInstallRun() {
  const runs = snapshot.state.action_runs;
  return runs.run_imessage_install || (runs.run_install?.status === "complete" ? runs.run_install : null);
}

function checkStatus(step) {
  if (providerRuntimePending(step)) {
    return { state: "pending", label: selectedAgentProvider() ? "Provider runtime pending" : "Choose a provider first", source: "none" };
  }
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
  if (["Provider runtime pending", "Choose a provider first"].includes(status.label)) return status.label;
  if (status.state === "failed") return "Machine check needs attention";
  if (status.state === "skipped") return "Waiting for a usable check";
  if (status.state !== "done") {
    return status.source === "verification" ? "Waiting for machine check" : "Waiting for proof";
  }
  if (status.source === "verification" || status.source === "machine") {
    return status.label.includes("confirmed") ? "Machine verified + you confirmed" : "Machine verified";
  }
  if (["human", "interview"].includes(status.source)) return "You confirmed";
  if (status.source === "onboarding") return "Saved on this Mac";
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

function onboardingValues() {
  return snapshot.state.metadata || {};
}

const providerNames = {
  claude: "Claude Code",
  codex: "Codex",
  gemini: "Gemini CLI",
  grok: "Grok Build",
};

function selectedAgentProvider() {
  const values = onboardingValues();
  return values.agent_provider || (snapshot.state.completed["identify.name-your-system"] ? "claude" : "");
}

function providerRuntimePending(step) {
  return selectedAgentProvider() !== "claude"
    && ["identify.authenticate-agent", "connect.imessage-bind"].includes(step.id);
}

function providerStepTitle(step) {
  const name = providerNames[selectedAgentProvider()];
  if (step.id === "identify.authenticate-agent") return name ? `Connect ${name}` : step.title;
  if (step.id === "connect.imessage-bind" && providerRuntimePending(step)) return `${name || "Provider"} text connection pending`;
  return step.title;
}

function providerGuide(step) {
  if (step.id === "prove.phone-board" && !snapshot.state.completed["prove.phone-board"]) {
    return {
      ...step.client_guide,
      intro: "Open your private board on the phone. When you confirm it works, Wideband will verify its HTTPS link and queue two setup texts to your bound iMessage chat.",
      instructions: [
        ...step.client_guide.instructions,
        "Select Board works — send two setup texts to approve the Fleetdeck link and quick commands by iMessage.",
      ],
      confirm_label: "Board works — send two setup texts",
    };
  }
  if (["identify.authenticate-agent", "connect.imessage-bind"].includes(step.id) && !selectedAgentProvider()) {
    return {
      ...step.client_guide,
      intro: "Choose an AI provider in the form above before connecting the head agent.",
      purpose: "Wideband needs your provider choice before it can check sign-in or start a text session.",
      success: "Your selected provider is authenticated and a real text reply reaches your phone.",
      instructions: ["Choose your AI provider in Make it yours, then save your choices."],
      confirm_label: "Choose a provider first",
    };
  }
  if (step.id === "connect.imessage-bind" && providerRuntimePending(step)) {
    const name = providerNames[selectedAgentProvider()] || "This provider";
    return {
      ...step.client_guide,
      intro: `${name} is saved as your provider, but its Wideband iMessage head-agent route is not verified yet.`,
      purpose: "Wideband will pause before binding your private chat to an unverified head runtime.",
      success: `A ${name} head session answers a real text through the owner-bound route. This proof is still pending.`,
      instructions: [
        "Your provider choice remains saved on this Mac.",
        "Wideband will offer chat binding after this provider's signed-in head session and guarded reply path are verified.",
      ],
      confirm_label: "Runtime support pending",
    };
  }
  if (step.id !== "identify.authenticate-agent") return step.client_guide;
  if (selectedAgentProvider() === "claude") {
    return {
      ...step.client_guide,
      intro: "Connect Claude Code directly to your account. Wideband checks the local tool, but never sees your password.",
      success: "Claude Code reports a signed-in account; a real text reply is checked later.",
      instructions: [
        "Select Open Claude sign-in below. A second Terminal window will open.",
        "Follow the secure browser sign-in opened by Claude Code.",
        "Approve the account you intend this custom agent to use.",
        "Return here after the sign-in window says 'Login successful'.",
      ],
      privacy: "Authentication happens between you and Anthropic.",
      confirm_label: "Check Claude sign-in",
    };
  }
  const name = providerNames[selectedAgentProvider()] || "This provider";
  return {
    ...step.client_guide,
    intro: `${name} is saved as your choice. Its Wideband iMessage head-agent path has not passed the Mac text test yet.`,
    purpose: `Wideband must verify a signed-in ${name} session and guarded text routing before starting your head agent.`,
    success: `A ${name} head session answers a real text through the owner-bound route. This proof is still pending.`,
    instructions: [
      `${name} is saved on this Mac as your selected provider.`,
      "Wideband will pause head-agent activation until this provider's sign-in, persistent session, and iMessage reply path are verified.",
      "You can edit your provider choice above if you want to use the current Claude Code setup path.",
    ],
    confirm_label: "Runtime support pending",
  };
}

function fillOnboardingForm() {
  const values = onboardingValues();
  $("#onboarding-os-name").value = values.os_name || "";
  $("#onboarding-agent-name").value = values.agent_name || "";
  for (const input of document.querySelectorAll('input[name="agent_provider"]')) {
    input.checked = input.value === selectedAgentProvider();
  }
  for (const input of document.querySelectorAll('input[name="first_goal"]')) {
    input.checked = input.value === values.first_goal;
  }
}

function renderOnboarding() {
  const values = onboardingValues();
  const saved = Boolean(snapshot.state.completed["identify.name-your-system"])
    && values.os_name && values.agent_name && values.first_goal;
  $("#onboarding-form").hidden = saved && !onboardingEditing;
  $("#onboarding-saved").hidden = !saved || onboardingEditing;
  if (!onboardingEditing && (saved || !onboardingFormInitialized)) {
    fillOnboardingForm();
    onboardingFormInitialized = true;
  }
  $("#saved-os-name").textContent = values.os_name || "";
  $("#saved-agent-name").textContent = values.agent_name || "";
  $("#saved-agent-provider").textContent = providerNames[selectedAgentProvider()] || "";
  $("#saved-first-goal").textContent = {
    research: "Research", website: "Build a website", proposal: "Proposal · Advanced",
  }[values.first_goal] || "";

  const accountReady = Boolean(snapshot.state.completed["prepare.create-accounts"]);
  const textProved = Boolean(snapshot.state.completed["prove.messaging"]);
  const phoneProved = Boolean(snapshot.state.completed["prove.phone-board"]);
  const phase = !saved ? 0 : !accountReady ? 1 : !textProved ? 2 : !phoneProved ? 3 : 4;
  [...document.querySelectorAll(".journey-nav span")].forEach((node, index) => {
    node.classList.toggle("active", index === phase);
    node.classList.toggle("complete", index < phase);
  });
}

function handoffDeliveryStatus() {
  const handoff = snapshot.state.handoff || {};
  return handoff.delivery?.status || (handoff.status === "held" ? "held" : handoff.version === 1 ? "unverified" : "not_queued");
}

function handoffNeedsReview() {
  return ["held", "rejected", "missing"].includes(handoffDeliveryStatus());
}

function handoffDeliverySummary() {
  const handoff = snapshot.state.handoff || {};
  const delivery = handoff.delivery || {};
  const count = (key) => Number.isInteger(delivery[key]) && delivery[key] >= 0 ? delivery[key] : 0;
  const sent = count("sent");
  const pending = count("pending");
  const processing = count("processing");
  const total = count("total") || 2;
  const item = (amount, singular, plural = `${singular}s`) => `${amount} ${amount === 1 ? singular : plural}`;
  switch (handoffDeliveryStatus()) {
    case "sent":
      return `${sent} of ${total} setup texts sent by this Mac. Confirm both arrived on your phone.`;
    case "pending":
      return `${sent} of ${total} sent by this Mac; ${pending} waiting in the guarded outbox${processing ? ` (${processing} processing)` : ""}. Delivery status updates here.`;
    case "held": {
      const reasons = [
        count("review") ? `${count("review")} in review` : "",
        count("unsafe") ? item(count("unsafe"), "unsafe outbox entry", "unsafe outbox entries") : "",
        count("stale_processing") ? `${count("stale_processing")} stalled while processing` : "",
      ].filter(Boolean);
      return `${sent} of ${total} sent by this Mac; delivery needs review${reasons.length ? ` (${reasons.join(", ")})` : ""}. No automatic retry. Have Wideband inspect it before checking again.`;
    }
    case "rejected":
      return `${sent} of ${total} sent by this Mac; ${item(count("rejected"), "setup text")} rejected. Wideband must review delivery before another check.`;
    case "missing":
      return `${sent} of ${total} sent by this Mac; ${item(count("missing"), "setup text")} missing from the guarded outbox. Wideband must review it.`;
    case "unverified":
      return "A setup-text receipt exists. Guarded outbox delivery has not been checked yet.";
    default:
      return handoff.approved_at
        ? "Your approval is saved. Setup texts have not been queued yet."
        : "Confirm the checkbox to queue these two texts to your bound chat.";
  }
}

function renderFirstGoal() {
  const selected = onboardingValues().first_goal;
  const section = $("#first-goal-section");
  section.hidden = !selected;
  if (!selected) return;
  const title = { research: "Research", website: "Build a website", proposal: "Proposal · Advanced" }[selected] || "First job";
  $("#first-goal-title").textContent = `First job · ${title}`;
  const detail = $("#first-goal-detail");
  const action = $("#first-goal-action");
  const run = snapshot.state.action_runs.run_first_goal_apply;
  const status = snapshot.facts.first_goal || {};
  const replied = checkStatus(allSteps().find((step) => step.id === "prove.messaging")).state === "done";
  action.hidden = !replied;
  action.textContent = run?.status === "needs_attention" ? "Retry first job" : "Check first job";
  action.onclick = (event) => handleAction(run?.status === "needs_attention" ? "run_first_goal_apply" : "run_first_goal_check", event.currentTarget);
  if (!replied) detail.textContent = "Wideband prepares this after a real head-agent reply arrives on your phone.";
  else if (!run || run.status === "running") detail.textContent = "Preparing your first job on this Mac…";
  else if (run.status === "needs_attention") detail.textContent = "The first job needs attention. Review the build feed and retry after the issue is resolved.";
  else if (selected === "website" && status.status === "ready") detail.textContent = "Your starter site answers locally. Its phone preview follows Fleetdeck installation and a private HTTPS route; test the link on your phone.";
  else if (status.status === "prepared") detail.textContent = "Your first-job brief is ready. Text your agent the topic and the result you want.";
  else detail.textContent = "Wideband saved your choice. Check the first job to refresh its readiness.";
  const phoneRun = snapshot.state.action_runs.run_phone_install;
  const phoneInstalled = replied && !snapshot.facts.deactivated && phoneRun?.status === "complete";
  const recentProof = phoneInstalled && phonePortalProof?.run === phoneRun.finished_at
    && Date.now() - phonePortalProof.checkedAt < 60_000 ? phonePortalProof : null;
  const portalLink = $("#phone-portal-link");
  const portalCopy = $("#phone-portal-copy");
  const portalCheck = $("#phone-portal-check");
  const portalConnect = $("#phone-portal-connect");
  portalLink.hidden = true;
  portalCopy.hidden = true;
  portalCheck.hidden = !phoneInstalled;
  portalCheck.disabled = phonePortalCheckActive;
  portalConnect.hidden = !phoneInstalled || recentProof?.status === "ready";
  if (recentProof?.status === "ready") {
    try {
      const url = new URL(recentProof.url);
      if (url.protocol === "https:" && url.hostname.endsWith(".ts.net")
          && /^\/p\/[0-9a-f]{64}\/phone$/.test(url.pathname)
          && !url.username && !url.password && !url.search && !url.hash) {
        portalLink.href = url.href;
        portalLink.title = url.href;
        portalLink.hidden = false;
        portalCopy.hidden = false;
      }
    } catch (_) { /* A malformed link is never presented. */ }
  }
  const portalState = phonePortalCheckActive
    ? "Checking Fleetdeck's local portal and private HTTPS route…"
    : recentProof?.detail || (phoneRun?.status === "complete"
    ? "Fleetdeck local portal installed. Check its private HTTPS link, then test it on your phone and add it to the home screen."
    : phoneRun?.status === "needs_attention"
      ? "Fleetdeck local portal needs repair before the phone handoff."
      : replied ? "Fleetdeck local portal is queued behind the first job." : "Fleetdeck phone view follows the first job.");
  const boardConfirmed = Boolean(snapshot.state.completed["prove.phone-board"]);
  const handoff = snapshot.state.handoff || {};
  const deliveryStatus = handoffDeliveryStatus();
  const needsReview = handoffNeedsReview();
  const hasReceipt = handoff.version === 1;
  const handoffState = setupHandoffActive
    ? " Checking your approved setup texts…"
    : needsReview
      ? " Setup-text delivery needs review; nothing retries automatically."
      : deliveryStatus === "sent"
        ? " This Mac sent the setup texts; confirm they arrived on your phone."
        : deliveryStatus === "pending"
          ? " Setup texts are waiting in the guarded outbox."
          : hasReceipt
            ? " A setup-text receipt exists; delivery is being checked."
            : boardConfirmed && phoneInstalled
              ? " Approve the two setup texts below when you are ready."
              : phoneInstalled
                ? " Confirm the board on your phone before choosing whether to receive setup texts."
                : "";
  $("#phone-portal-state").textContent = portalState + handoffState;
  const handoffPanel = $("#phone-handoff-section");
  handoffPanel.hidden = !(boardConfirmed && phoneInstalled) && !hasReceipt && !needsReview;
  $("#phone-handoff-title").textContent = hasReceipt || needsReview
    ? "Setup texts for your phone." : "Send your setup details by iMessage.";
  $("#phone-handoff-detail").textContent = hasReceipt || needsReview
    ? "These texts contain your private Fleetdeck link and setup commands. The guarded outbox reports its delivery state below; confirm arrival on your phone."
    : "Wideband will queue two texts to your verified personal chat: your private Fleetdeck link and a short list of setup commands.";
  const consent = $("#phone-handoff-consent");
  const approved = Boolean(handoff.approved_at);
  const showAction = !hasReceipt || needsReview;
  $("#phone-handoff-consent-label").hidden = approved || !showAction;
  if (handoffPanel.hidden && !approved) consent.checked = false;
  const handoffReady = setupHandoffReady();
  const handoffButton = $("#phone-handoff-send");
  handoffButton.hidden = !showAction;
  handoffButton.textContent = needsReview ? "Check setup-text delivery" : approved ? "Queue setup texts" : "Approve and queue setup texts";
  handoffButton.append(element("span", "", "→"));
  handoffButton.disabled = !handoffReady || setupHandoffActive || (!approved && !consent.checked);
  const handoffMessage = $("#phone-handoff-status");
  const showError = Boolean(setupHandoffError);
  handoffMessage.classList.toggle("attention", needsReview || showError);
  handoffMessage.textContent = setupHandoffActive
    ? "Checking the owner-only chat and guarded outbox…"
    : showError
      ? `Setup-text check needs attention: ${setupHandoffError} ${handoffDeliverySummary()}`
      : hasReceipt || needsReview
        ? handoffDeliverySummary()
        : handoffReady
          ? approved ? "Your approval is saved. Choose Queue setup texts when ready." : "Confirm the checkbox to queue these two texts."
          : "Waiting for the private phone link and live text connection to verify. Use Check phone HTTPS above if needed.";

  const local = $("#first-goal-local");
  const phone = $("#first-goal-phone");
  local.hidden = true;
  phone.hidden = true;
  try {
    const url = new URL(status.local_url);
    if (replied && run?.status === "complete" && status.status === "ready" && selected === "website" && url.protocol === "http:" && url.hostname === "127.0.0.1") {
      local.href = url.href;
      local.hidden = false;
    }
  } catch (_) { /* No verified local preview yet. */ }
  try {
    const url = new URL(status.phone_url);
    if (replied && run?.status === "complete" && status.status === "ready" && selected === "website" && url.protocol === "https:" && url.hostname.endsWith(".ts.net")) {
      phone.href = url.href;
      phone.hidden = false;
    }
  } catch (_) { /* No private phone URL yet. */ }
}

async function checkPhonePortalLink() {
  if (phonePortalCheckPromise) return await phonePortalCheckPromise;
  const run = snapshot.state.action_runs.run_phone_install;
  if (run?.status !== "complete" || snapshot.facts.deactivated) return;
  phonePortalCheckPromise = performPhonePortalLinkCheck(run);
  try {
    await phonePortalCheckPromise;
  } finally {
    phonePortalCheckPromise = null;
  }
}

async function performPhonePortalLinkCheck(run) {
  phonePortalCheckActive = true;
  phonePortalCheckedRun = run.finished_at || "complete";
  renderFirstGoal();
  try {
    const result = await api("/api/phone-link");
    phonePortalProof = { ...result, run: phonePortalCheckedRun, checkedAt: Date.now() };
  } catch (error) {
    phonePortalProof = { status: "needs_attention", detail: `Phone link check paused: ${error.message}`, run: phonePortalCheckedRun, checkedAt: Date.now() };
  } finally {
    phonePortalCheckActive = false;
    renderFirstGoal();
  }
}

function setupHandoffReady() {
  const phoneRun = snapshot.state.action_runs.run_phone_install;
  const reply = allSteps().find((step) => step.id === "prove.messaging");
  return !snapshot.facts.deactivated && selectedAgentProvider() === "claude"
    && Boolean(snapshot.state.completed["prove.phone-board"])
    && snapshot.state.action_runs.run_imessage_bind?.status === "complete"
    && snapshot.state.action_runs.run_first_goal_apply?.status === "complete"
    && reply && checkStatus(reply).state === "done"
    && phoneRun?.status === "complete"
    && phonePortalProof?.status === "ready"
    && phonePortalProof.run === (phoneRun.finished_at || "complete")
    && Date.now() - phonePortalProof.checkedAt < 60_000;
}

async function sendSetupHandoff({ freshConfirmation = false } = {}) {
  if (setupHandoffActive || (snapshot.state.handoff?.version === 1 && !handoffNeedsReview()) || snapshot.facts.deactivated
      || !setupHandoffReady()) return { status: "skipped" };
  const consent = $("#phone-handoff-consent");
  if (!snapshot.state.handoff?.approved_at && !freshConfirmation && !consent.checked) return { status: "not_approved" };
  setupHandoffActive = true;
  setupHandoffError = "";
  renderFirstGoal();
  try {
    if (!snapshot.state.handoff?.approved_at) {
      const approval = await api("/api/handoff/confirm", { method: "POST", body: { confirm: true } });
      if (approval.status !== "approved" || !approval.approved_at) {
        throw new Error("the handoff approval was not saved");
      }
      snapshot.state.handoff = { ...snapshot.state.handoff, approved_at: approval.approved_at };
      consent.checked = false;
    }
    const result = await api("/api/handoff", { method: "POST", body: {} });
    if (result.status === "held") {
      snapshot.state.handoff = { ...snapshot.state.handoff, status: "held", delivery: undefined };
      try { await refreshState(); } catch (_) { /* Polling will retry the read-only delivery check. */ }
      return result;
    }
    if (result.status !== "queued" && result.status !== "already_queued") {
      throw new Error("the handoff did not return a queue receipt");
    }
    snapshot.state.handoff = { ...snapshot.state.handoff, version: 1, status: result.status, delivery: undefined };
    try { await refreshState(); } catch (_) { /* Keep the queue receipt until state reconnects. */ }
    if (result.status === "queued" && result.queued > 0) {
      toast("Setup links and quick commands queued for your agent chat");
    }
    return result;
  } catch (error) {
    setupHandoffError = error.message;
    return { status: "needs_attention" };
  } finally {
    setupHandoffActive = false;
    renderFirstGoal();
  }
}

function phoneBoardCompletionMessage(outcome) {
  if (outcome?.status === "queued" && outcome.queued > 0) {
    return "Phone board confirmed. Setup texts were queued for your bound chat; delivery is checked separately.";
  }
  if (snapshot.state.handoff?.status === "held" || outcome?.status === "held") {
    return "Phone board confirmed. Setup texts need delivery review; see the handoff card.";
  }
  if (outcome?.status === "already_queued" || snapshot.state.handoff?.version === 1) {
    return "Phone board confirmed. An earlier setup-text receipt exists; check its delivery status below.";
  }
  return "Phone board confirmed. Setup texts are waiting for the private link or text connection; see the handoff card.";
}

async function copyPhonePortalLink() {
  const link = $("#phone-portal-link");
  if (link.hidden) return;
  try {
    await navigator.clipboard.writeText(link.href);
    toast("Private Fleetdeck phone link copied");
  } catch (_) {
    toast("Copy did not complete; open the link and copy it from your browser", 5200);
  }
}

function openOnboarding() {
  onboardingEditing = true;
  fillOnboardingForm();
  $("#onboarding-message").textContent = "No Apple Account email, password, or verification code is collected here.";
  renderOnboarding();
  $("#onboarding-section").scrollIntoView({ behavior: "smooth", block: "start" });
  setTimeout(() => $("#onboarding-os-name").focus(), 180);
}

async function saveOnboarding(event) {
  event.preventDefault();
  const form = $("#onboarding-form");
  if (!form.reportValidity()) return;
  clearTimeout(welcomeGuideTimer);
  welcomeGuideTimer = null;
  const values = Object.fromEntries(new FormData(form).entries());
  const wasNew = !snapshot.state.completed["identify.name-your-system"];
  const button = $("#onboarding-save");
  button.disabled = true;
  try {
    await api("/api/onboarding", { method: "POST", body: values });
    onboardingEditing = false;
    await refreshState();
    toast("Your OS, agent, provider, and first job are saved privately");
    if (wasNew) {
      const next = currentClientStep();
      if (next) setTimeout(() => openGuide(next.id), 300);
    }
  } catch (error) {
    $("#onboarding-message").textContent = error.message;
  } finally {
    button.disabled = false;
  }
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
    $("#focus-count").textContent = "First text complete";
    $("#focus-stage").textContent = "Saved";
    $("#focus-icon").textContent = "✓";
    $("#focus-eyebrow").textContent = "The agent replied";
    $("#focus-title").textContent = "Your head agent is reachable by text.";
    $("#focus-description").textContent = "Your phone received a real answer. Keep this Mac plugged in and online while Wideband prepares your first job and Fleetdeck phone view.";
    action.hidden = true;
    note.hidden = false;
    note.textContent = "The phone board and later support setup remain visible below.";
    $("#client-complete").hidden = false;
    return;
  }

  const index = steps.findIndex((item) => item.id === step.id);
  const stage = stageForStep(step.id);
  $("#focus-count").textContent = `Client step ${index + 1} of ${steps.length}`;
  $("#focus-stage").textContent = stage?.title || "Setup";
  $("#focus-icon").textContent = String(index + 1).padStart(2, "0");
  $("#focus-eyebrow").textContent = step.client_guide.eyebrow || "Your action";
  $("#focus-title").textContent = providerStepTitle(step);
  $("#focus-description").textContent = providerGuide(step).intro || step.description;
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
      element("span", "", status.label === "Provider runtime pending" ? "RUNTIME PENDING"
        : status.label === "Choose a provider first" ? "CHOOSE PROVIDER"
        : (step.checks || []).length ? "WIDEBAND CHECKS" : "YOU CONFIRM"),
    );
    button.append(topline, element("h3", "", providerStepTitle(step)), element("p", "", evidenceLabel(status)));
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
      element("small", "", `${evidenceLabel(status)} · ${step.id === "prove.next-morning-brief" ? "Scheduled follow-up" : step.client_phase === "later" ? "Later setup" : "Complete with your Wideband operator"}`),
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
  const handoff = readinessForSteps(clientSteps().filter((step) => step.client_phase === "handoff"));
  const machineReady = verification && verification.failed === 0;

  $("#completion-title").textContent = "Your head agent answered by text.";
  $("#completion-summary").textContent = machineReady
    ? "The text path and machine foundation are verified. Your first job and Fleetdeck phone view are next."
    : "Your phone reply is confirmed. Wideband will resolve remaining machine checks and prepare your first job and phone view.";
  $("#completion-machine").textContent = verification
    ? `${verification.passed} passed · ${verification.failed} need attention · ${verification.skipped} deferred`
    : "Machine verification has not run yet";
  $("#completion-profile").textContent = profileReady
    ? "Approved and installed privately"
    : "Complete the custom operator profile with Wideband";
  $("#completion-handoff").textContent = `${handoff.done} of ${handoff.total} phone handoff proofs complete`;
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
  const install = textInstallRun();
  const deactivated = snapshot.facts.deactivated;
  const verification = snapshot.state.last_verification?.summary;
  const imessage = snapshot.verification_rollup;
  const textChecks = ["P6-IMSGOS", "P6-IMSG", "P6-IMSGCFG", "P6-IMSGCHAT", "P6-IMSGHEAD", "P6-IMSGSERVICES"];
  const textReady = textChecks.every((id) => imessage[id] === "pass");
  const textBroken = snapshot.facts.bootstrap_status === "unsupported_macos"
    || ["P6-IMSGOS", "P6-IMSG"].some((id) => imessage[id] === "fail")
    || snapshot.state.action_runs.run_imessage_bind?.status === "needs_attention";
  const foundationState = deactivated
    ? "attention"
    : install?.status === "needs_attention" || textBroken
      ? "attention"
      : install?.status === "complete" && snapshot.facts.wideband_agent_installed && textReady
        ? "ready"
        : "waiting";
  const foundationDetail = deactivated
    ? "Wideband services are deactivated. Repair restores the managed runtime."
    : snapshot.facts.bootstrap_status === "unsupported_macos"
      ? "This iMessage runtime needs macOS 14 or newer."
    : install?.status === "complete"
      ? textReady
        ? "imsg, exact owner chat, head session, and guarded services verified."
        : "Text foundation installed. Waiting for the separate account, fresh owner text, and live binding checks."
      : install?.status === "needs_attention"
        ? "The first-text installation needs review."
        : "The first-text foundation is being prepared.";

  const permissions = immediateClientSteps().filter((step) => permissionStepIds.includes(step.id));
  const permissionState = readinessForSteps(permissions);
  const approvals = immediateClientSteps().filter((step) => !permissionStepIds.includes(step.id));
  const approvalState = readinessForSteps(approvals);
  const proofs = clientSteps().filter((step) => step.client_phase === "handoff");
  const proofState = readinessForSteps(proofs);

  $("#readiness-grid").replaceChildren(
    readinessCard("Machine", "Wideband foundation", foundationState, foundationDetail, openSupport),
    readinessCard(
      "macOS",
      "First-text permissions",
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
      `${proofState.done} of ${proofState.total} phone handoff proofs observed.`,
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
  const install = textInstallRun();
  const running = snapshot.jobs.find((job) => job.status === "running");
  const verification = snapshot.state.last_verification?.summary;
  const bootstrapDone = snapshot.facts.bootstrap_ready;
  const bootstrapStatus = snapshot.facts.bootstrap_status || "starting";
  const deactivated = snapshot.facts.deactivated;
  const installDone = install?.status === "complete" && snapshot.facts.wideband_agent_installed && !deactivated;
  const attention = deactivated || install?.status === "needs_attention"
    || snapshot.facts.bootstrap_status === "unsupported_macos"
    || snapshot.state.action_runs.run_imessage_bind?.status === "needs_attention";
  const messagingChecks = ["P6-IMSGCFG", "P6-IMSGCHAT", "P6-IMSGHEAD", "P6-IMSGSERVICES"];
  const messagingReady = messagingChecks.every((id) => snapshot.verification_rollup[id] === "pass");

  list.replaceChildren(
    machineRow(
      bootstrapDone,
      "Core tools",
      bootstrapDone
        ? "Homebrew, Python, tmux, and imsg are ready."
        : bootstrapStatus === "unsupported_macos"
          ? "iMessage head-agent setup requires macOS 14 or newer on this Mac."
        : bootstrapStatus === "needs_admin_password"
          ? "Action needed: enter your Mac password in Terminal, then return here."
          : bootstrapStatus === "needs_developer_tools"
            ? "Action needed: approve Apple's Command Line Tools installer; Wideband checks it automatically."
            : bootstrapStatus === "needs_developer_tools_selection"
              ? "Apple's tools are installed but no longer selected. Terminal shows the exact reselect command."
            : bootstrapStatus === "needs_developer_tools_update"
              ? "Apple's developer-tool files remain, but Git cannot run after the macOS upgrade."
            : bootstrapStatus === "needs_homebrew_ownership"
              ? "Homebrew was left by another ownership context. Terminal shows the verified repair boundary."
          : bootstrapStatus === "collecting_identity"
            ? "Complete the Wideband setup popup currently on screen."
            : bootstrapStatus === "needs_attention"
              ? "The core tool install needs review in Terminal."
              : "Homebrew and the core tools are installing in Terminal.",
      !bootstrapDone && !["unsupported_macos", "needs_admin_password", "needs_developer_tools", "needs_developer_tools_selection", "needs_developer_tools_update", "needs_homebrew_ownership", "collecting_identity", "needs_attention"].includes(bootstrapStatus),
    ),
    machineRow(installDone, "Wideband text foundation", installDone ? "Wideband Agent and the messaging foundation are installed." : deactivated ? "Managed services are deactivated; Repair Wideband can restore them." : ["run_install", "run_imessage_install"].includes(running?.action) ? "Installing automatically now." : attention ? "An operator will review the installation output." : "Queued behind the core tools.", ["run_install", "run_imessage_install"].includes(running?.action)),
    machineRow(messagingReady, "iMessage head-agent runtime", messagingReady ? "Owner chat, persistent head session, and guarded reply services verified." : "Waiting for the separate Apple Account, fresh owner text, and live runtime checks.", ["run_imessage_init", "run_imessage_bind"].includes(running?.action)),
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
  if (!bootstrapDone && bootstrapStatus === "unsupported_macos") {
    state.textContent = "Unsupported macOS";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Update to macOS 14 or newer";
    badge.querySelector("small").textContent = "The iMessage runtime cannot start on this macOS version. Complete the OS update, then reopen Wideband Setup.";
  } else if (!bootstrapDone && bootstrapStatus === "needs_admin_password") {
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
  } else if (!bootstrapDone && bootstrapStatus === "needs_developer_tools_update") {
    state.textContent = "Your action";
    state.classList.add("attention");
    badge.classList.add("attention");
    badge.querySelector("strong").textContent = "Update Apple Command Line Tools";
    badge.querySelector("small").textContent = "Open System Settings → General → Software Update. Wideband will not delete or replace Apple's tools automatically.";
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
  $("#client-greeting").textContent = onboardingValues().agent_name || (name ? `${name}, your AI` : "Your AI");
  renderOnboarding();
  renderFirstGoal();
  renderClientProgress();
  renderFocusCard();
  renderClientQueue();
  renderHandoff();
  renderMachineState();
  renderReadiness();
  renderCompletion();
}

function guideActions(step) {
  if (step.id === "connect.imessage-bind" && providerRuntimePending(step)) return [];
  if (step.id === "identify.authenticate-agent") {
    return selectedAgentProvider() === "claude"
      ? [{ action: "open_claude_auth", label: "Open Claude sign-in" }] : [];
  }
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
  if (step.type === "onboarding") {
    openOnboarding();
    return;
  }
  currentGuideStepId = stepId;
  const steps = clientSteps();
  const index = steps.findIndex((item) => item.id === stepId);
  const guide = providerGuide(step);
  const status = checkStatus(step);
  $("#guide-progress-label").textContent = `Client step ${index + 1} of ${steps.length}`;
  $("#guide-progress-bar").style.width = `${Math.round(((index + 1) / steps.length) * 100)}%`;
  $("#guide-owner").textContent = responsibilityLabel(step);
  $("#guide-eyebrow").textContent = guide.eyebrow || "Your action";
  $("#guide-title").textContent = providerStepTitle(step);
  $("#guide-intro").textContent = guide.intro || step.description;
  $("#guide-purpose").textContent = guide.purpose || guide.intro || step.description;
  $("#guide-success").textContent = guide.success || ((step.checks || []).length
    ? "Wideband's local check reports this permission or service as ready."
    : "You confirm the account or action is complete, and the guide saves your place.");
  $("#guide-instructions").replaceChildren(...(guide.instructions || [step.description]).map((item) => element("li", "", item)));

  const privacy = $("#guide-privacy");
  privacy.hidden = !guide.privacy;
  privacy.querySelector("p").textContent = guide.privacy || "";
  const acknowledgment = $("#guide-acknowledgment");
  acknowledgment.hidden = !guide.acknowledgment_label || status.state === "done";
  $("#guide-acknowledgment-label").textContent = guide.acknowledgment_label || "";
  $("#guide-acknowledgment-check").checked = false;
  const providerPending = providerRuntimePending(step);
  $("#guide-message").textContent = providerPending
    ? selectedAgentProvider()
      ? "Provider choice saved. Head-agent activation is waiting for a verified runtime path."
      : "Choose and save an AI provider above before connecting the head agent."
    : status.state === "done" ? `✓ ${evidenceLabel(status)}. You can review or check it again.` : "";
  $("#guide-message").className = status.state === "done" ? "guide-message success" : "guide-message";

  const actions = $("#guide-open-actions");
  actions.replaceChildren(...guideActions(step).map((item) => {
    const button = element("button", "", item.label || actionLabel(item.action));
    button.type = "button";
    button.addEventListener("click", () => invokeGuideAction(item.action, button, item.message));
    return button;
  }));

  const confirm = $("#guide-confirm");
  confirm.disabled = providerPending;
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
      const job = await waitForJob(result.id, false);
      await refreshState();
      if (job.status !== "complete") {
        throw new Error(job.output.trim().split("\n").slice(-2).join(" ") || "The action needs attention; review Setup tools.");
      }
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
  if (providerRuntimePending(step)) return;
  const button = $("#guide-confirm");
  const message = $("#guide-message");
  if (checkStatus(step).state === "done") {
    stopGuideMonitoring();
    $("#guide-dialog").close();
    const next = currentClientStep();
    if (next && step.client_phase === "now") setTimeout(() => openGuide(next.id), 220);
    return;
  }
  if (step.client_guide.acknowledgment_label && !$("#guide-acknowledgment-check").checked) {
    message.className = "guide-message error";
    message.textContent = "Confirm that the agent Apple Account is separate from the one on your personal iPhone.";
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
      await api(`/api/steps/${encodeURIComponent(step.id)}`, {
        method: "POST",
        body: { complete: true, account_distinct: step.id === "prepare.create-accounts" && $("#guide-acknowledgment-check").checked },
      });
    }
    if (checks.length) {
      if (supportsLiveCheck(step)) {
        const result = await api("/api/live-checks", { method: "POST", body: {} });
        mergeLiveCheckResult(result);
      } else {
        const verificationAction = checks.every((id) => id.startsWith("P6-")) ? "run_verify_imessage" : "run_verify_quick";
        const job = await api(`/api/actions/${verificationAction}`, { method: "POST", body: {} });
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
    let handoffOutcome = null;
    if (step.id === "prove.phone-board") {
      await checkPhonePortalLink();
      if (setupHandoffReady()) handoffOutcome = await sendSetupHandoff({ freshConfirmation: true });
    }
    message.className = "guide-message success";
    message.textContent = step.id === "prove.phone-board"
      ? phoneBoardCompletionMessage(handoffOutcome)
      : `${evidenceLabel(status)}. Moving to your next step…`;
    await delay(450);
    $("#guide-dialog").close();
    if (step.id === "prove.phone-board" && !$("#phone-handoff-section").hidden) {
      $("#phone-handoff-section").scrollIntoView({ behavior: "smooth", block: "center" });
    }
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
    clearTimeout(welcomeGuideTimer);
    welcomeGuideTimer = setTimeout(() => {
      welcomeGuideTimer = null;
      const step = currentClientStep();
      if (step) openGuide(step.id);
    }, 180);
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
    const install = textInstallRun();
    if (!install || install.status === "interrupted") {
      const job = await api("/api/actions/run_imessage_install", { method: "POST", body: {} });
      await refreshState();
      const finished = await waitForJob(job.id, false);
      await refreshState();
      if (finished.status === "complete") toast("Wideband text foundation installed");
      else toast("Wideband text installation needs review", 5200);
    } else if (!snapshot.state.last_verification && install.status === "complete") {
      const job = await api("/api/actions/run_verify_imessage", { method: "POST", body: {} });
      await waitForJob(job.id, false);
      await refreshState();
    }
    const init = snapshot.state.action_runs.run_imessage_init;
    if ((snapshot.state.action_runs.run_imessage_install?.status === "complete" || snapshot.state.action_runs.run_install?.status === "complete")
        && selectedAgentProvider() === "claude"
        && snapshot.state.completed["identify.name-your-system"]
        && snapshot.state.completed["prepare.create-accounts"]
        && (!init || init.status === "interrupted")) {
      const job = await api("/api/actions/run_imessage_init", { method: "POST", body: {} });
      await refreshState();
      const finished = await waitForJob(job.id, false);
      await refreshState();
      if (finished.status === "complete") {
        toast("Private head-agent workspace staged");
        const check = await api("/api/actions/run_verify_imessage", { method: "POST", body: {} });
        await waitForJob(check.id, false);
        await refreshState();
      }
    }
    const firstJob = snapshot.state.action_runs.run_first_goal_apply;
    const reply = allSteps().find((step) => step.id === "prove.messaging");
    if (reply && checkStatus(reply).state === "done" && (!firstJob || firstJob.status === "interrupted")) {
      const job = await api("/api/actions/run_first_goal_apply", { method: "POST", body: {} });
      await waitForJob(job.id, false);
      await refreshState();
    }
    const phone = snapshot.state.action_runs.run_phone_install;
    if (snapshot.state.action_runs.run_first_goal_apply?.status === "complete"
        && (!phone || phone.status === "interrupted")) {
      const job = await api("/api/actions/run_phone_install", { method: "POST", body: {} });
      await waitForJob(job.id, false);
      await refreshState();
    }
    const installedPhone = snapshot.state.action_runs.run_phone_install;
    if (installedPhone?.status === "complete") {
      const currentProof = phonePortalProof?.run === (installedPhone.finished_at || "complete")
        && Date.now() - phonePortalProof.checkedAt < 60_000;
      if (!currentProof) await checkPhonePortalLink();
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
    viewMode === "client" ? "run_verify_imessage" : "run_verify_quick",
    button,
    "Running a fresh read-only check…",
    "Readiness refreshed. Select any area that still needs attention.",
  );
}

async function repairWideband(button = $("#support-repair")) {
  const action = viewMode === "client" ? "run_imessage_install" : "run_install";
  await runSupportJob(
    action,
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
    run_imessage_init: "Stage head agent",
    run_imessage_bind: "Bind my text",
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
    && step.id !== "identify.operator-interview"
    && step.id !== "prepare.create-accounts"
    && step.id !== "prove.phone-board"
    && (step.id !== "identify.authenticate-agent" || selectedAgentProvider() === "claude");
  const statusButton = element("button", `step-status${canConfirm ? " confirmable" : ""}`, statusSymbol(status));
  statusButton.type = "button";
  statusButton.title = step.id === "prove.phone-board"
    ? "Use the client guide to confirm the board and authorize two setup texts"
    : canConfirm
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
  const heading = element("h3", "", providerStepTitle(step));
  heading.append(element("span", `tag ${step.actor}`, step.actor));
  if (step.optional) heading.append(element("span", "tag optional", "optional"));
  copy.append(heading, element("p", "", ["identify.authenticate-agent", "connect.imessage-bind"].includes(step.id)
    ? providerGuide(step).intro : step.description));
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
  if (step.action && !providerRuntimePending(step)) {
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
  if (["run_verify_quick", "run_verify_full", "run_verify_imessage"].includes(job.action)) {
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
$("#onboarding-form").addEventListener("submit", saveOnboarding);
$("#onboarding-edit").addEventListener("click", openOnboarding);
$("#phone-portal-check").addEventListener("click", checkPhonePortalLink);
$("#phone-portal-copy").addEventListener("click", copyPhonePortalLink);
$("#phone-portal-connect").addEventListener("click", (event) => handleAction("run_phone_install", event.currentTarget));
$("#phone-handoff-consent").addEventListener("change", renderFirstGoal);
$("#phone-handoff-send").addEventListener("click", sendSetupHandoff);
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
