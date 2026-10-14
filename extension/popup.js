const $ = id => document.getElementById(id);
const send = msg => chrome.runtime.sendMessage(msg);
const KEYS = ["F2", "F3", "F4", "F6", "F7", "F8", "F9", "F10", "F12"];   // F1/F5/F11 are used by the browser

const defaults = { key: "F2", voice: "", speed: 1 };

async function init() {
  const s = await chrome.storage.sync.get(defaults);
  $("key").innerHTML = KEYS.map(k => `<option>${k}</option>`).join("");
  $("key").value = s.key;
  $("keyHint").textContent = s.key;
  $("speed").value = String(s.speed);

  $("key").onchange = () => { chrome.storage.sync.set({ key: $("key").value }); $("keyHint").textContent = $("key").value; };
  $("speed").onchange = () => chrome.storage.sync.set({ speed: +$("speed").value });
  $("voice").onchange = () => chrome.storage.sync.set({ voice: $("voice").value });

  const running = await refreshStatus();
  if (running) loadVoices(s.voice);
  else $("voice").innerHTML = `<option value="${s.voice}">${s.voice ? s.voice.split("-").pop().replace(/Neural|Multilingual/g, "") : "Default voice"} (start the app to change)</option>`;
}

async function loadVoices(saved) {
  const r = await send({ type: "voices" });
  if (r.error) {
    $("voice").innerHTML = `<option value="">Default voice</option>`;
    showError(r.error);
    return;
  }
  const opt = v => `<option value="${v.id}">${v.name} · ${v.locale} · ${v.gender}</option>`;
  $("voice").innerHTML =
    `<optgroup label="Recommended">${r.voices.filter(v => v.recommended).map(opt).join("")}</optgroup>` +
    `<optgroup label="All English voices">${r.voices.filter(v => !v.recommended).map(opt).join("")}</optgroup>`;
  $("voice").value = saved || r.default;
}

async function refreshStatus() {
  const { running } = await send({ type: "status" });
  $("dot").classList.toggle("on", running);
  $("statusText").textContent = running ? "Ebook Generator app is running" : "App not running (starts when you read)";
  $("appBtn").hidden = false;
  $("appBtn").textContent = running ? "Stop" : "Start";
  $("appBtn").onclick = async () => {
    $("appBtn").disabled = true;
    const r = running ? await send({ type: "stopApp" }) : await send({ type: "voices" });
    if (r?.error) showError(r.error);
    if (!running && !r?.error) loadVoices((await chrome.storage.sync.get(defaults)).voice);
    setTimeout(async () => { await refreshStatus(); $("appBtn").disabled = false; }, 600);
  };
  return running;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = false;
}

init();
