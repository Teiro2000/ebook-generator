// Ebook Generator - Read Aloud: content script.
// Captures the selection, plays the narration and highlights each word as it's spoken.
(() => {
  if (window.__ebookReadAloud) return;
  window.__ebookReadAloud = true;

  const WORD = "ebook-read-aloud-word";
  const PASSAGE = "ebook-read-aloud-passage";
  const FIRST_CHUNK = 300;      // small first request so speech starts quickly
  const CHUNK = 1200;

  const settings = { key: "F2", voice: "", speed: 1 };
  chrome.storage.sync.get(settings, s => Object.assign(settings, s));
  chrome.storage.onChanged.addListener(changes => {
    for (const k in changes) settings[k] = changes[k].newValue;
  });

  let session = null;
  let nextId = 1;

  // ---------- triggers

  window.addEventListener("keydown", e => {
    if (e.key === settings.key && !e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey) {
      e.preventDefault();
      e.stopPropagation();
      if (!toggle()) toast(`Highlight some text first, then press ${settings.key}.`, 3000);
    } else if (e.key === "Escape" && session) {
      stop();
    }
  }, true);

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === "toggle") sendResponse({ handled: toggle() });
    else if (session && msg.id === session.id) {
      if (msg.type === "fallbackWord") session.onFallbackWord(msg);
      if (msg.type === "fallbackEnd") stop();
    }
  });

  // New selection -> read it. No selection while reading -> stop.
  function toggle() {
    const sel = captureSelection();
    if (sel) { start(sel); return true; }
    if (session) { stop(); return true; }
    return false;
  }

  // ---------- selection -> text + map back to DOM positions

  function captureSelection() {
    const el = document.activeElement;
    if (el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT") && el.selectionEnd > el.selectionStart) {
      const text = el.value.slice(el.selectionStart, el.selectionEnd);
      return text.trim() ? { text, segs: null, range: null } : null;
    }
    const sel = getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0).cloneRange();
    let root = range.commonAncestorContainer;
    if (root.nodeType !== Node.ELEMENT_NODE) root = root.parentNode;

    const blocks = new Map();
    const blockOf = node => {
      for (let el = node.parentElement; el && el !== document.body; el = el.parentElement) {
        if (!blocks.has(el)) blocks.set(el, getComputedStyle(el).display);
        if (!blocks.get(el).startsWith("inline")) return el;
      }
      return document.body;
    };

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode(n) {
        if (n.nodeType === Node.ELEMENT_NODE) {
          if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|SVG)$/i.test(n.tagName)) return NodeFilter.FILTER_REJECT;
          return n.tagName === "BR" && range.intersectsNode(n) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        }
        if (!range.intersectsNode(n)) return NodeFilter.FILTER_REJECT;
        const p = n.parentElement;
        if (p && p.checkVisibility && !p.checkVisibility()) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    let text = "", lastBlock = null;
    const segs = [];
    for (let n; (n = walker.nextNode());) {
      if (n.nodeType === Node.ELEMENT_NODE) { text += "\n"; continue; }   // <br>
      const s = n === range.startContainer ? range.startOffset : 0;
      const e = n === range.endContainer ? range.endOffset : n.data.length;
      if (e <= s) continue;
      const block = blockOf(n);
      if (text && block !== lastBlock) text += "\n";
      lastBlock = block;
      segs.push({ node: n, nodeStart: s, textStart: text.length, len: e - s });
      text += n.data.slice(s, e);
    }
    return text.trim() ? { text, segs, range } : null;
  }

  function locate(segs, idx) {
    for (let i = segs.length - 1; i >= 0; i--) {
      const g = segs[i];
      if (idx >= g.textStart) return idx < g.textStart + g.len ? [g.node, g.nodeStart + idx - g.textStart] : null;
    }
    return null;
  }

  function rangeFor(segs, index, length) {
    const a = locate(segs, index), b = locate(segs, index + Math.max(length, 1) - 1);
    if (!a || !b) return null;
    const r = document.createRange();
    r.setStart(a[0], a[1]);
    r.setEnd(b[0], b[1] + 1);
    return r;
  }

  function splitChunks(text) {
    const chunks = [];
    let start = 0;
    while (start < text.length) {
      const limit = chunks.length ? CHUNK : FIRST_CHUNK;
      let end = Math.min(text.length, start + limit);
      if (end < text.length) {
        const slice = text.slice(start, end);
        const cut = Math.max(slice.lastIndexOf(". "), slice.lastIndexOf("! "), slice.lastIndexOf("? "), slice.lastIndexOf("\n"));
        if (cut > limit / 3) end = start + cut + 1;
        else if (slice.lastIndexOf(" ") > 0) end = start + slice.lastIndexOf(" ") + 1;
      }
      const t = text.slice(start, end);
      if (t.trim()) chunks.push({ start, text: t });
      start = end;
    }
    return chunks;
  }

  // ---------- playback

  async function start(sel) {
    stop();
    const s = session = { id: `${Date.now()}-${nextId++}`, sel, prefetch: [], stopped: false };
    ensureStyles();
    if (sel.range) {
      if (window.CSS?.highlights) CSS.highlights.set(PASSAGE, new Highlight(sel.range));
      getSelection().removeAllRanges();
    }
    const chunks = splitChunks(sel.text);
    const synth = text => chrome.runtime.sendMessage({ type: "synthesize", text, voice: settings.voice, speed: settings.speed })
      .catch(e => ({ error: String(e.message || e) }));

    toast("Getting the voice ready…");
    s.ctx = new AudioContext();
    for (let i = 0; i < chunks.length; i++) {
      const data = await (s.prefetch[i] ||= synth(chunks[i].text));
      if (s.stopped) return;
      if (data.error) return fallback(s, chunks[i].start, data);
      if (i + 1 < chunks.length) s.prefetch[i + 1] ||= synth(chunks[i + 1].text);
      let buffer;
      try {
        buffer = await s.ctx.decodeAudioData(base64ToBuffer(data.audio));
      } catch {
        return fallback(s, chunks[i].start, { error: "Couldn't decode the audio" });
      }
      if (s.stopped) return;
      if (i === 0) hideToast();
      await play(s, buffer, data.words, chunks[i].start);
      if (s.stopped) return;
    }
    stop();
  }

  function play(s, buffer, words, base) {
    return new Promise(resolve => {
      const src = s.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(s.ctx.destination);
      s.source = src;
      s.resolve = resolve;
      let w = -1;
      const t0 = s.ctx.currentTime;
      src.onended = () => { clearInterval(s.timer); resolve(); };
      src.start();
      // A plain timer (not requestAnimationFrame) so highlighting keeps time even when the page isn't repainting.
      s.timer = setInterval(() => {
        const ms = (s.ctx.currentTime - t0) * 1000;
        let next = w;
        while (next + 1 < words.length && words[next + 1].start <= ms) next++;
        if (next !== w) {
          w = next;
          highlightWord(s, base + words[w].index, words[w].length);
        }
      }, 25);
    });
  }

  function fallback(s, from, data) {
    const why = data.code ? data.error : "Microsoft's voice service isn't responding.";
    toast(`${why} Using your browser's built-in voice for now.`, 7000);
    const text = s.sel.text.slice(from);
    s.usingFallback = true;
    s.onFallbackWord = m => {
      const len = m.length || (text.slice(m.charIndex).match(/^\S+/) || [""])[0].length;
      highlightWord(s, from + m.charIndex, len);
    };
    chrome.runtime.sendMessage({ type: "fallbackSpeak", text, speed: settings.speed, id: s.id }).catch(() => {});
  }

  function stop() {
    const s = session;
    if (!s) return;
    s.stopped = true;
    session = null;
    clearInterval(s.timer);
    try { s.source?.stop(); } catch {}
    s.resolve?.();
    s.ctx?.close().catch(() => {});
    if (s.usingFallback) chrome.runtime.sendMessage({ type: "fallbackStop" }).catch(() => {});
    if (window.CSS?.highlights) { CSS.highlights.delete(WORD); CSS.highlights.delete(PASSAGE); }
    hideToast();
  }

  // ---------- highlighting

  function highlightWord(s, index, length) {
    if (!s.sel.segs || !window.CSS?.highlights) return;
    const r = rangeFor(s.sel.segs, index, length);
    if (!r) return;
    CSS.highlights.set(WORD, new Highlight(r));
    const rect = r.getBoundingClientRect();
    if (rect.height && (rect.top < 60 || rect.bottom > innerHeight - 60)) {
      r.startContainer.parentElement?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  function ensureStyles() {
    if (document.getElementById("ebook-read-aloud-style")) return;
    const style = document.createElement("style");
    style.id = "ebook-read-aloud-style";
    style.textContent = `
      ::highlight(${PASSAGE}) { background-color: rgba(255, 200, 60, 0.22); }
      ::highlight(${WORD}) { background-color: #ffcf3f; color: #111; }`;
    (document.head || document.documentElement).appendChild(style);
  }

  // ---------- toast

  let toastHost = null, toastBox = null, toastTimer = 0;
  function toast(message, ms = 0) {
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.style.cssText = "all:initial;position:fixed;z-index:2147483647;right:16px;bottom:16px;";
      const root = toastHost.attachShadow({ mode: "closed" });
      root.innerHTML = `<style>
        div { font: 13px/1.45 system-ui, "Segoe UI", sans-serif; background: #23201b; color: #fff;
              padding: 10px 14px; border-radius: 10px; box-shadow: 0 4px 18px rgba(0,0,0,.3); max-width: 340px; }
      </style><div></div>`;
      toastBox = root.querySelector("div");
    }
    toastBox.textContent = `🔊 ${message}`;
    document.documentElement.appendChild(toastHost);
    clearTimeout(toastTimer);
    if (ms) toastTimer = setTimeout(hideToast, ms);
  }
  function hideToast() {
    clearTimeout(toastTimer);
    toastHost?.remove();
  }

  function base64ToBuffer(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }
})();
