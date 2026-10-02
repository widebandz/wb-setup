#!/usr/bin/env node

const token = process.env.WB_E2E_TOKEN;
const base = process.env.WB_E2E_BASE || "http://127.0.0.1:8803";
const debugging = process.env.WB_E2E_DEBUG || "http://127.0.0.1:9223";
if (!token) throw new Error("WB_E2E_TOKEN is required");

const targets = await (
  await fetch(`${debugging}/json/list`, { signal: AbortSignal.timeout(5_000) })
).json();
const target = targets.find((item) => item.type === "page");
if (!target) throw new Error("no Chrome page target");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});

let nextId = 1;
const pending = new Map();
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
};
socket.onclose = () => {
  for (const { reject } of pending.values()) reject(new Error("Chrome DevTools connection closed"));
  pending.clear();
};

function send(method, params = {}, timeout = 10_000) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`timeout waiting for Chrome DevTools ${method}`));
    }, timeout);
    const settle = (callback) => (value) => {
      clearTimeout(timer);
      callback(value);
    };
    pending.set(id, { resolve: settle(resolve), reject: settle(reject) });
    try {
      socket.send(JSON.stringify({ id, method, params }));
    } catch (error) {
      pending.delete(id);
      clearTimeout(timer);
      reject(error);
    }
  });
}

async function evaluate(expression, awaitPromise = true) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  }
  return result.result.value;
}

async function waitFor(expression, timeout = 15_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await evaluate(`Boolean(${expression})`)) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`timeout waiting for ${expression}`);
}

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.navigate", { url: `${base}/#${token}` });
  await waitFor(
    `document.readyState === "complete" && document.querySelector("#focus-title")?.textContent !== "Loading your next step…"`,
    20_000,
  );

  const initial = await evaluate(`({
  title: document.title,
  welcome: document.querySelector("#welcome-dialog").open,
  focus: document.querySelector("#focus-title").textContent,
  responsibility: [...document.querySelectorAll(".responsibility-strip strong")].map((node) => node.textContent),
  connection: document.querySelector("#live-state").textContent,
  runtime: document.querySelector("#runtime-reminder-detail").textContent,
  phonePortalHidden: document.querySelector("#phone-portal-link").hidden,
  tokenStored: sessionStorage.getItem("wb-setup-token")?.length > 20,
  hashCleared: location.hash === "",
})`);
  console.log(`INITIAL=${JSON.stringify(initial)}`);
  if (!initial.welcome || !initial.hashCleared || !initial.tokenStored || !initial.phonePortalHidden) {
    throw new Error("welcome or private-token lifecycle failed");
  }
  if (initial.responsibility.join("|") !== "Wideband installs|You approve|We customize together") {
    throw new Error("responsibility labels are missing");
  }

  await evaluate(`document.querySelector("#welcome-begin").click()`);
  await waitFor(`!document.querySelector("#onboarding-form").hidden`);
  const providerChoices = await evaluate(`({
    selected: document.querySelector('input[name="agent_provider"]:checked')?.value || "",
    options: [...document.querySelectorAll('input[name="agent_provider"]')].map((input) => input.value),
  })`);
  if (providerChoices.selected || providerChoices.options.join("|") !== "claude|codex|gemini|grok") {
    throw new Error("new onboarding must offer four explicit provider choices");
  }
  await evaluate(`(() => {
    document.querySelector("#onboarding-os-name").value = "Aurora";
    document.querySelector("#onboarding-agent-name").value = "Trace";
    document.querySelector('input[name="agent_provider"][value="claude"]').checked = true;
    document.querySelector('input[name="first_goal"][value="research"]').checked = true;
    document.querySelector("#onboarding-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  })()`);
  await waitFor(`!document.querySelector("#onboarding-saved").hidden`).catch(async (error) => {
    const state = await evaluate(`({
      valid: document.querySelector("#onboarding-form").checkValidity(),
      values: [...new FormData(document.querySelector("#onboarding-form")).entries()],
      message: document.querySelector("#onboarding-message").textContent,
      saving: document.querySelector("#onboarding-save").disabled,
    })`);
    throw new Error(`${error.message}; form: ${JSON.stringify(state)}`);
  });
  await waitFor(`document.querySelector("#guide-dialog").open`).catch(async (error) => {
    const state = await evaluate(`({
      next: currentClientStep()?.id,
      guideTitle: document.querySelector("#guide-title").textContent,
      onboardingMessage: document.querySelector("#onboarding-message").textContent,
    })`);
    throw new Error(`${error.message}; after onboarding: ${JSON.stringify(state)}`);
  });
  const onboarding = await evaluate(`({
    os: document.querySelector("#saved-os-name").textContent,
    agent: document.querySelector("#saved-agent-name").textContent,
    provider: document.querySelector("#saved-agent-provider").textContent,
    goal: document.querySelector("#saved-first-goal").textContent,
    firstGuide: document.querySelector("#guide-title").textContent,
    accountCheck: !document.querySelector("#guide-acknowledgment").hidden,
  })`);
  console.log(`ONBOARDING=${JSON.stringify(onboarding)}`);
  if (onboarding.os !== "Aurora" || onboarding.agent !== "Trace" || onboarding.provider !== "Claude Code" || onboarding.goal !== "Research"
      || onboarding.firstGuide !== "Complete macOS Setup Assistant" || onboarding.accountCheck) {
    throw new Error("local-first onboarding order failed");
  }
  await evaluate(`document.querySelector("#guide-later").click(); openGuide("prepare.create-accounts")`);
  await waitFor(`document.querySelector("#guide-dialog").open && document.querySelector("#guide-title").textContent === "Create a separate agent Apple Account"`);
  const accountGate = await evaluate(`!document.querySelector("#guide-acknowledgment").hidden`);
  if (!accountGate) throw new Error("separate agent Apple Account acknowledgment is missing");
  await evaluate(`document.querySelector("#guide-confirm").click()`);
  await waitFor(`document.querySelector("#guide-message").textContent.includes("separate from")`);
  await evaluate(`document.querySelector("#guide-later").click()`);
  await waitFor(`!document.querySelector("#guide-dialog").open`);
  await new Promise((resolve) => setTimeout(resolve, 100));
  await evaluate(`openGuide("connect.screen-sharing")`);
  await waitFor(`document.querySelector("#guide-dialog").open && document.querySelector("#guide-title").textContent === "Enable secure Screen Sharing"`);
  await waitFor(`/updates automatically|Machine verified|Return to Wideband Setup|Waiting for macOS approval/.test(document.querySelector("#guide-message").textContent)`, 20_000).catch(async (error) => {
    const state = await evaluate(`({
      message: document.querySelector("#guide-message").textContent,
      currentGuideStepId, guideCheckActive, guideCheckTimer: Boolean(guideCheckTimer),
      status: checkStatus(allSteps().find((step) => step.id === "connect.screen-sharing")),
      supports: supportsLiveCheck(allSteps().find((step) => step.id === "connect.screen-sharing")),
    })`);
    throw new Error(`${error.message}; guide: ${JSON.stringify(state)}`);
  });
  const guide = await evaluate(`({
  open: document.querySelector("#guide-dialog").open,
  title: document.querySelector("#guide-title").textContent,
  owner: document.querySelector("#guide-owner").textContent,
  message: document.querySelector("#guide-message").textContent,
  actionCount: document.querySelectorAll("#guide-open-actions button").length,
  confirm: document.querySelector("#guide-confirm").textContent.trim(),
})`);
  console.log(`GUIDE=${JSON.stringify(guide)}`);
  if (!guide.open || guide.owner !== "You approve · Wideband verifies" || guide.actionCount < 1) {
    throw new Error("guided client-step contract failed");
  }
  if (!/updates automatically|Machine verified|Return to Wideband Setup|Waiting for macOS approval/.test(guide.message)) {
    throw new Error("live-check coaching did not appear");
  }

  await evaluate(`document.querySelector("#guide-later").click(); document.querySelector("#view-toggle").click()`);
  await waitFor(`!document.querySelector("#operator-view").hidden`);
  const operator = await evaluate(`({
  title: document.querySelector("#stage-title").textContent,
  steps: document.querySelectorAll("#steps .step").length,
  toggle: document.querySelector("#view-toggle").textContent,
})`);
  console.log(`OPERATOR=${JSON.stringify(operator)}`);
  if (!operator.steps || operator.toggle !== "Back to client") throw new Error("operator view failed");

  await evaluate(`document.querySelector("#view-toggle").click(); document.querySelector("#support").click()`);
  await waitFor(`document.querySelector("#support-dialog").open`);
  const support = await evaluate(`({
  options: [...document.querySelectorAll(".support-option strong")].map((node) => node.textContent),
  privacy: document.querySelector(".support-privacy").textContent.includes("Private by design"),
})`);
  console.log(`SUPPORT=${JSON.stringify(support)}`);
  if (support.options.length !== 4 || !support.privacy) throw new Error("support tools failed");

  await evaluate(`document.querySelector("#support-dialog").close(); document.querySelector("#onboarding-edit").click()`);
  await waitFor(`!document.querySelector("#onboarding-form").hidden`);
  await evaluate(`(() => {
    document.querySelector('input[name="agent_provider"][value="codex"]').checked = true;
    document.querySelector("#onboarding-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  })()`);
  await waitFor(`!document.querySelector("#onboarding-saved").hidden && document.querySelector("#saved-agent-provider").textContent === "Codex"`);
  await evaluate(`openGuide("identify.authenticate-agent")`);
  const preview = await evaluate(`({
    title: document.querySelector("#guide-title").textContent,
    intro: document.querySelector("#guide-intro").textContent,
    actionCount: document.querySelectorAll("#guide-open-actions button").length,
    confirmationDisabled: document.querySelector("#guide-confirm").disabled,
    saved: snapshot.state.metadata.agent_provider,
  })`);
  console.log(`PROVIDER_PREVIEW=${JSON.stringify(preview)}`);
  if (preview.title !== "Connect Codex" || preview.saved !== "codex" || preview.actionCount !== 0
      || !preview.confirmationDisabled || !preview.intro.includes("has not passed the Mac text test")) {
    throw new Error("unverified provider was presented as connected");
  }
  await evaluate(`document.querySelector("#guide-dialog").close(); openGuide("connect.imessage-bind")`);
  const binding = await evaluate(`({
    title: document.querySelector("#guide-title").textContent,
    actionCount: document.querySelectorAll("#guide-open-actions button").length,
    confirmationDisabled: document.querySelector("#guide-confirm").disabled,
  })`);
  if (binding.title !== "Codex text connection pending" || binding.actionCount !== 0 || !binding.confirmationDisabled) {
    throw new Error("unverified provider exposed iMessage binding");
  }

  const fleetdeckRetry = await evaluate(`(() => {
    snapshot.state.action_runs.run_first_goal_apply = { status: "complete" };
    snapshot.state.action_runs.run_phone_install = { status: "needs_attention" };
    renderFirstGoal();
    const button = document.querySelector("#phone-portal-connect");
    return !button.hidden && button.textContent === "Retry Fleetdeck installation";
  })()`);
  if (!fleetdeckRetry) throw new Error("failed local Fleetdeck install has no visible retry");

  // Exercise explicit phone-handoff consent in-browser with mocked API responses.
  // The real setup server receives no handoff POST and no text is sent.
  const handoff = await evaluate(`(async () => {
    clearTimeout(stateRefreshTimer);
    const originalFetch = window.fetch;
    const calls = [];
    let delivery = { status: "not_queued", sent: 0, pending: 0, processing: 0,
      review: 0, rejected: 0, missing: 0, unsafe: 0, stale_processing: 0, total: 2 };
    window.fetch = async (input, options) => {
      const path = String(input);
      if (path === "/api/steps/prove.phone-board") {
        snapshot.state.completed["prove.phone-board"] = { source: "human" };
        return new Response(JSON.stringify({ completed: snapshot.state.completed }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      if (path === "/api/state") {
        snapshot.state.handoff.delivery = { ...delivery };
        return new Response(JSON.stringify(snapshot), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      if (path === "/api/phone-link") {
        calls.push({ path, method: options?.method || "GET" });
        return new Response(JSON.stringify({
          status: "ready", url: "https://aurora.example-tailnet.ts.net:8790/p/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/phone",
          detail: "Private phone link verified.",
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (path === "/api/handoff/confirm") {
        calls.push({ path, method: options?.method || "GET", confirm: JSON.parse(options?.body || "{}").confirm });
        snapshot.state.handoff.approved_at = "2026-09-27T20:00:00Z";
        return new Response(JSON.stringify({ status: "approved", approved_at: snapshot.state.handoff.approved_at }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      if (path === "/api/handoff") {
        calls.push({ path, method: options?.method || "GET" });
        const count = calls.filter((call) => call.path === "/api/handoff").length;
        if (count === 1) delivery = { ...delivery, status: "pending", pending: 2 };
        return new Response(JSON.stringify(count === 1
          ? { status: "queued", queued: 2 }
          : { status: "held", queued: 0 }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      return originalFetch(input, options);
    };
    try {
      snapshot.facts.client_mode = false;
      snapshot.facts.deactivated = false;
      snapshot.jobs = [];
      snapshot.state.metadata.agent_provider = "claude";
      snapshot.state.completed["prove.messaging"] = { source: "human" };
      snapshot.state.completed["prove.phone-board"] = { source: "human" };
      snapshot.state.action_runs.run_imessage_bind = { status: "complete" };
      snapshot.state.action_runs.run_first_goal_apply = { status: "complete" };
      snapshot.state.action_runs.run_phone_install = { status: "complete", finished_at: "handoff-browser-proof" };
      snapshot.state.handoff = {};
      for (const id of ["P6-IMSGCHAT", "P6-IMSGHEAD", "P6-IMSGSERVICES"]) {
        snapshot.verification_rollup[id] = "pass";
      }
      phonePortalProof = {
        status: "ready", url: "https://aurora.example-tailnet.ts.net:8790/p/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/phone",
        run: "handoff-browser-proof", checkedAt: Date.now(),
      };
      renderFirstGoal();
      const phoneLink = document.querySelector("#phone-portal-link");
      const phoneLinkShown = !phoneLink.hidden && !document.querySelector("#phone-portal-copy").hidden
        && phoneLink.href === phonePortalProof.url;
      const verifiedProof = phonePortalProof;
      phonePortalProof = { ...verifiedProof, url: verifiedProof.url.slice(0, -6) + "/board" };
      renderFirstGoal();
      const boardRouteHidden = phoneLink.hidden;
      phonePortalProof = { ...verifiedProof, url: verifiedProof.url.replace(":8790/", ":9999/") };
      renderFirstGoal();
      const wrongPortHidden = phoneLink.hidden;
      phonePortalProof = { ...verifiedProof, status: "waiting" };
      renderFirstGoal();
      const unverifiedHidden = phoneLink.hidden;
      phonePortalProof = { ...verifiedProof, run: "stale-run" };
      renderFirstGoal();
      const staleHidden = phoneLink.hidden;
      phonePortalProof = verifiedProof;
      snapshot.facts.deactivated = true;
      renderFirstGoal();
      const deactivatedHidden = phoneLink.hidden;
      snapshot.facts.deactivated = false;
      renderFirstGoal();
      await checkPhonePortalLink();
      const resumePosts = calls.filter((call) => call.path.startsWith("/api/handoff")).length;
      const consentVisibleOnResume = !document.querySelector("#phone-handoff-section").hidden
        && document.querySelector("#phone-handoff-send").disabled;
      const consent = document.querySelector("#phone-handoff-consent");
      consent.checked = true;
      consent.dispatchEvent(new Event("change"));
      const manualSendEnabled = !document.querySelector("#phone-handoff-send").disabled;
      consent.checked = false;
      consent.dispatchEvent(new Event("change"));
      delete snapshot.state.completed["prove.phone-board"];
      renderFirstGoal();
      const phoneBoardStep = allSteps().find((step) => step.id === "prove.phone-board");
      const quickControl = renderStep(phoneBoardStep, 0).querySelector(".step-status");
      const quickCompleteDisabled = quickControl.disabled && quickControl.title.includes("Use the client guide");
      document.querySelector("#guide-dialog").close();
      openGuide("prove.phone-board");
      const freshConfirmation = document.querySelector("#guide-confirm").textContent.includes("send two setup texts")
        && document.querySelector("#guide-intro").textContent.includes("queue two setup texts");
      await completeGuideStep(phoneBoardStep);
      const afterProof = calls.filter((call) => call.path.startsWith("/api/handoff")).length;
      const approved = snapshot.state.handoff?.approved_at === "2026-09-27T20:00:00Z";
      const pending = snapshot.state.handoff?.version === 1
        && document.querySelector("#phone-handoff-status").textContent.includes("2 waiting in the guarded outbox")
        && document.querySelector("#phone-handoff-send").hidden;
      const priorReceiptMessage = phoneBoardCompletionMessage({ status: "already_queued" }).includes("An earlier setup-text receipt exists");
      await checkPhonePortalLink();
      const afterRepeat = calls.filter((call) => call.path.startsWith("/api/handoff")).length;
      delivery = { ...delivery, status: "sent", sent: 2, pending: 0 };
      await refreshState();
      const sent = document.querySelector("#phone-handoff-status").textContent.includes("2 of 2 setup texts sent by this Mac")
        && document.querySelector("#phone-handoff-send").hidden;
      delivery = { ...delivery, status: "held", sent: 1, review: 1 };
      await refreshState();
      const heldBeforeClick = !document.querySelector("#phone-handoff-section").hidden
        && document.querySelector("#phone-handoff-status").textContent.includes("1 in review")
        && !document.querySelector("#phone-handoff-send").hidden
        && document.querySelector("#phone-portal-state").textContent.includes("nothing retries automatically");
      await checkPhonePortalLink();
      const afterHeldPoll = calls.filter((call) => call.path === "/api/handoff").length;
      delivery = { ...delivery, status: "rejected", review: 0, rejected: 1 };
      await refreshState();
      const rejected = document.querySelector("#phone-handoff-status").textContent.includes("1 setup text rejected")
        && !document.querySelector("#phone-handoff-send").hidden;
      delivery = { ...delivery, status: "missing", rejected: 0, missing: 1 };
      await refreshState();
      const missing = document.querySelector("#phone-handoff-status").textContent.includes("1 setup text missing")
        && !document.querySelector("#phone-handoff-send").hidden;
      delivery = { ...delivery, status: "held", missing: 0, pending: 1, processing: 1, stale_processing: 1 };
      await refreshState();
      const stalled = document.querySelector("#phone-handoff-status").textContent.includes("1 stalled while processing")
        && !document.querySelector("#phone-handoff-send").hidden;
      await sendSetupHandoff();
      const heldAfterClick = snapshot.state.handoff?.status === "held"
        && document.querySelector("#phone-handoff-status").textContent.includes("No automatic retry");
      return { phoneLinkShown, boardRouteHidden, wrongPortHidden, unverifiedHidden, staleHidden, deactivatedHidden,
        resumePosts, consentVisibleOnResume, manualSendEnabled, quickCompleteDisabled, freshConfirmation, afterProof, approved, pending,
        priorReceiptMessage, afterRepeat, sent, heldBeforeClick, afterHeldPoll, rejected, missing, stalled, heldAfterClick,
        handoffMethods: calls.filter((call) => call.path.startsWith("/api/handoff")).map((call) => call.method),
        confirmTrue: calls.find((call) => call.path === "/api/handoff/confirm")?.confirm };
    } finally {
      window.fetch = originalFetch;
    }
  })()`);
  console.log(`HANDOFF=${JSON.stringify(handoff)}`);
  if (!handoff.phoneLinkShown || !handoff.boardRouteHidden || !handoff.wrongPortHidden || !handoff.unverifiedHidden
      || !handoff.staleHidden || !handoff.deactivatedHidden
      || handoff.resumePosts !== 0 || !handoff.consentVisibleOnResume || !handoff.manualSendEnabled || !handoff.quickCompleteDisabled
      || !handoff.freshConfirmation || handoff.afterProof !== 2 || !handoff.approved || !handoff.pending || !handoff.priorReceiptMessage
      || handoff.afterRepeat !== 2 || !handoff.sent || !handoff.heldBeforeClick || handoff.afterHeldPoll !== 1
      || !handoff.rejected || !handoff.missing || !handoff.stalled || !handoff.heldAfterClick
      || !handoff.confirmTrue || handoff.handoffMethods.join("|") !== "POST|POST|POST") {
    throw new Error("phone handoff consent, held state, or no-auto-retry contract failed");
  }

  console.log("WEB_E2E=PASS");
} finally {
  socket.close();
}
