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
  tokenStored: sessionStorage.getItem("wb-setup-token")?.length > 20,
  hashCleared: location.hash === "",
})`);
  console.log(`INITIAL=${JSON.stringify(initial)}`);
  if (!initial.welcome || !initial.hashCleared || !initial.tokenStored) {
    throw new Error("welcome or private-token lifecycle failed");
  }
  if (initial.responsibility.join("|") !== "Wideband installs|You approve|We customize together") {
    throw new Error("responsibility labels are missing");
  }

  await evaluate(`document.querySelector("#welcome-begin").click()`);
  await waitFor(`document.querySelector("#guide-dialog").open`);
  await new Promise((resolve) => setTimeout(resolve, 6_500));
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
  if (!/updates automatically|Machine verified|Return to Wideband Setup/.test(guide.message)) {
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

  console.log("WEB_E2E=PASS");
} finally {
  socket.close();
}
