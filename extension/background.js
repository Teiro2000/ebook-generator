// Ebook Generator - Read Aloud: background service worker.
// Talks to the local Ebook Generator app (starting it through the native helper if needed).

const API = "http://127.0.0.1:5173";
const HOST = "com.ebookgenerator.launcher";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "read-aloud", title: "Read aloud", contexts: ["selection"] });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "read-aloud") trigger(tab, info.frameId ?? 0);
});

chrome.commands.onCommand.addListener((command, tab) => {
  if (command === "read-selection") trigger(tab);
});

async function trigger(tab, frameId) {
  const opts = frameId === undefined ? {} : { frameId };
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "toggle" }, opts);
  } catch {
    // The page was open before the extension was installed: inject the script, then retry.
    try {
      const target = { tabId: tab.id, ...(frameId === undefined ? { allFrames: true } : { frameIds: [frameId] }) };
      await chrome.scripting.executeScript({ target, files: ["content.js"] });
      await chrome.tabs.sendMessage(tab.id, { type: "toggle" }, opts);
    } catch (e) {
      console.warn("Read aloud isn't available on this page:", e);
    }
  }
}

// ---------- the local app

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function ping() {
  try {
    const r = await fetch(`${API}/api/ping`, { signal: AbortSignal.timeout(800) });
    return r.ok;
  } catch {
    return false;
  }
}

let starting = null;
function ensureApp() {
  return starting ||= (async () => {
    if (await ping()) return;
    let reply;
    try {
      reply = await chrome.runtime.sendNativeMessage(HOST, { action: "start" });
    } catch {
      const err = new Error("The Ebook Generator helper isn't set up yet - run extension\\install.bat once.");
      err.code = "NOT_INSTALLED";
      throw err;
    }
    if (reply && reply.ok === false) throw Object.assign(new Error(reply.error), { code: "START_FAILED" });
    for (let i = 0; i < 50; i++) {        // first launch can take a few seconds
      await sleep(400);
      if (await ping()) return;
    }
    throw new Error("The Ebook Generator app didn't start. Try running start.bat once to check for errors.");
  })().finally(() => { starting = null; });
}

async function synthesize({ text, voice, speed }) {
  await ensureApp();
  const r = await fetch(`${API}/api/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice, speed }),
  });
  return r.json().catch(() => ({ error: `App error ${r.status}` }));
}

async function voices() {
  await ensureApp();
  return fetch(`${API}/api/voices`).then(r => r.json());
}

async function stopApp() {
  if (!(await ping())) return { ok: true };
  await fetch(`${API}/api/shutdown`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
  }).catch(() => {});
  return { ok: true };
}

// ---------- fallback: the browser's own voice, used when Microsoft's service is down

function fallbackSpeak({ text, speed, id }, sender) {
  const send = msg => chrome.tabs.sendMessage(sender.tab.id, { ...msg, id }, { frameId: sender.frameId }).catch(() => {});
  chrome.tts.stop();
  chrome.tts.speak(text, {
    rate: speed || 1,
    onEvent: e => {
      if (e.type === "word") send({ type: "fallbackWord", charIndex: e.charIndex, length: e.length });
      if (["end", "interrupted", "cancelled", "error"].includes(e.type)) send({ type: "fallbackEnd" });
    },
  });
  return { ok: true };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handlers = {
    synthesize,
    voices,
    stopApp,
    status: async () => ({ running: await ping() }),
    fallbackSpeak: m => fallbackSpeak(m, sender),
    fallbackStop: () => { chrome.tts.stop(); return { ok: true }; },
  };
  const handler = handlers[msg.type];
  if (!handler) return;
  Promise.resolve(handler(msg)).then(sendResponse, e => sendResponse({ error: e.message, code: e.code }));
  return true;   // async response
});
