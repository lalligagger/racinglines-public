/* racinglines web app: the little client-side behaviour the server-rendered pages need.
   Partial updates (the Live tab, the Lab's sections and Edge Finder) are HTMX attributes in the templates;
   this file adds what attributes can't: the CSRF token on every HTMX POST, an error toast, browser-side view
   settings (which Lab sections are open, the jobs filter), the replay player, the sweep form's "what changed"
   highlighting, a generic pressed-button toggle (the Positions chart's Polymarket / Private book switch), and the
   three "less on the page at once" pieces: page tabs, remembered collapsed sections, and table row caps / filters. */
(function () {
  "use strict";
  const NS = document.body.dataset.ns || "";                // a demo session's own namespace (web/demo.py)
  const store = {
    get(k, d) { try { const v = localStorage.getItem(NS + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(NS + k, JSON.stringify(v)); } catch (e) {} },
  };
  const csrf = () => (document.querySelector("[name=csrf_token]") || {}).value || "";

  // --- HTMX: every non-GET request carries the form's CSRF token; a refused request shows its message ---
  document.addEventListener("htmx:configRequest", e => {
    if (e.detail.verb !== "get") e.detail.parameters.csrf_token = csrf();
  });
  document.addEventListener("htmx:responseError", e => {
    const x = e.detail.xhr, text = (x.responseText || "").trim();
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch (err) {}
    toast(msg || `Request failed (${x.status})`);
  });
  function toast(msg) {
    let t = document.getElementById("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "flash bad"; t.setAttribute("role", "alert");
      t.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:50;max-width:min(90vw,560px)"; document.body.appendChild(t); }
    t.textContent = msg; clearTimeout(toast.timer); toast.timer = setTimeout(() => t.remove(), 6000);
  }

  // --- generic pressed toggles: <button data-toggle="plot" data-value="x"> shows [data-plot="x"], hides the others;
  //     data-value="*" shows them all ---
  document.addEventListener("click", e => {
    const b = e.target.closest("button[data-toggle]");
    if (!b) return;
    const group = b.dataset.toggle, v = b.dataset.value;
    document.querySelectorAll(`button[data-toggle="${group}"]`).forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    document.querySelectorAll(`[data-${group}]:not(button)`).forEach(p => { p.hidden = v !== "*" && p.dataset[group] !== v; });
  });

  // --- page tabs: <nav class="ptabs" data-tabs="name"><button data-tab="k">…</button></nav> shows [data-panel="k"] and
  //     hides the other panels. One set per page; the choice is remembered per page, and #k in the URL opens a tab
  //     (so does a link to any element inside one). Content re-rendered by HTMX gets the same tab back. ---
  function tabsApply(nav, key, setHash) {
    const btns = [...nav.querySelectorAll("[data-tab]")];
    if (!btns.some(b => b.dataset.tab === key)) key = btns.length ? btns[0].dataset.tab : null;
    btns.forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === key)));
    document.querySelectorAll("[data-panel]").forEach(p => { p.hidden = p.dataset.panel !== key; });
    store.set("tabs." + nav.dataset.tabs, key);
    if (setHash && key) history.replaceState(null, "", "#" + key);
  }
  function tabsInit(root) {
    const nav = root.querySelector ? root.querySelector("[data-tabs]") : null;
    if (!nav) return;
    let key = store.get("tabs." + nav.dataset.tabs, null);
    const h = location.hash.slice(1), el = h && document.getElementById(h);
    if (h && nav.querySelector(`[data-tab="${h}"]`)) key = h;
    else if (el && el.closest("[data-panel]")) key = el.closest("[data-panel]").dataset.panel;
    tabsApply(nav, key, false);
    if (el && el.closest("[data-panel]") && !nav.dataset.shown) { nav.dataset.shown = 1; el.scrollIntoView({block: "start"}); }
  }
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-tabs] [data-tab]");
    if (b) tabsApply(b.closest("[data-tabs]"), b.dataset.tab, true);
  });

  // --- collapsed sections: <details data-remember="id"> keeps its open / closed state per browser ---
  document.addEventListener("toggle", e => {
    const d = e.target;
    if (d.matches && d.matches("details[data-remember]")) store.set("open." + d.dataset.remember, d.open);
  }, true);
  function detailsInit(root) {
    root.querySelectorAll("details[data-remember]").forEach(d => {
      const v = store.get("open." + d.dataset.remember, null);
      if (v !== null) d.open = v;
    });
  }

  // --- table tools: <div class="scroll" data-rows="12" data-filter="Driver or team"> caps a long table at N rows
  //     behind a "Show all" button and, with data-filter, adds a box that filters the rows by their text ---
  function tableInit(root) {
    root.querySelectorAll(".scroll[data-rows], .scroll[data-filter]").forEach(box => {
      if (box.dataset.tt) return;
      box.dataset.tt = 1;
      const rows = [...box.querySelectorAll("tbody tr")], cap = +box.dataset.rows || 0;
      if (rows.length <= (cap || 0) && !box.dataset.filter) return;
      const bar = document.createElement("div"); bar.className = "tt";
      let all = !(cap && rows.length > cap), q = "";
      function apply() {
        let shown = 0;
        rows.forEach(r => {
          const ok = !q || r.textContent.toLowerCase().includes(q);
          r.hidden = !ok || (!all && !q && shown >= cap); if (!r.hidden) shown++;
        });
        if (more) { more.hidden = all || !!q; }
        if (count) count.textContent = q ? `${shown} of ${rows.length}` : (all ? "" : `${cap} of ${rows.length}`);
      }
      let inp = null, more = null, count = null;
      if (box.dataset.filter !== undefined) {
        inp = document.createElement("input"); inp.type = "search"; inp.placeholder = box.dataset.filter || "Filter…";
        inp.setAttribute("aria-label", "Filter rows");
        inp.addEventListener("input", () => { q = inp.value.trim().toLowerCase(); apply(); });
        bar.appendChild(inp);
      }
      count = document.createElement("span"); count.className = "legend"; bar.appendChild(count);
      if (cap && rows.length > cap) {
        more = document.createElement("button"); more.type = "button"; more.className = "link";
        more.textContent = `Show all ${rows.length}`;
        more.addEventListener("click", () => { all = true; apply(); });
        bar.appendChild(more);
      }
      box.parentNode.insertBefore(bar, box);
      apply();
    });
  }
  function initAll(root) { tabsInit(root); detailsInit(root); tableInit(root); }
  document.addEventListener("htmx:afterSwap", e => initAll(e.detail.target));

  document.addEventListener("DOMContentLoaded", () => {
  initAll(document);
  // --- Lab: sections open on demand (HTMX loads them on their "open" event), remembered per browser ---
  const lab = document.getElementById("lab");
  if (lab) {
    const open = new Set(store.get("lab.open", []));
    (JSON.parse(lab.dataset.openNow || "[]")).forEach(k => open.add(k));
    function show(key, on, scroll) {
      const box = document.getElementById(key), btn = document.querySelector(`[data-section="${key}"]`);
      if (!box || !btn) return;
      box.hidden = !on; btn.setAttribute("aria-pressed", on);
      on ? open.add(key) : open.delete(key); store.set("lab.open", [...open]);
      if (on) { htmx.trigger(box, "open"); if (scroll) box.scrollIntoView({block: "start"}); }
    }
    document.querySelectorAll("[data-section]").forEach(b =>
      b.addEventListener("click", () => show(b.dataset.section, b.getAttribute("aria-pressed") !== "true")));
    document.addEventListener("click", e => {
      const a = e.target.closest("a[data-open]");
      if (a) { e.preventDefault(); show(a.dataset.open, true, true); }
    });
    // the jobs section: whose jobs (mine / everyone's) is a browser setting, sent as a query parameter
    const jobs = document.getElementById("jobs");
    if (jobs) {
      jobs.addEventListener("htmx:configRequest", e => { e.detail.parameters.scope = store.get("lab.jobsScope", "mine"); });
      document.addEventListener("change", e => {
        if (e.target.matches("[name=jobs-scope]")) { store.set("lab.jobsScope", e.target.value); htmx.trigger(jobs, "open"); }
      });
    }
    // Edge Finder buttons reflect the saved combos after every swap
    function mark() {
      const root = document.getElementById("edge-root");
      let cs = [];
      try { cs = JSON.parse(root.dataset.combos); } catch (e) {}
      const has = (v, s) => cs.some(c => c[0] === v && c[1] === s);
      document.querySelectorAll("[data-edge=toggle]").forEach(b => b.setAttribute("aria-pressed", has(b.dataset.variant, b.dataset.strategy)));
      document.querySelectorAll("[data-edge-model]").forEach(b => {
        const inEF = cs.some(c => c[0] === b.dataset.variant);
        b.setAttribute("aria-pressed", inEF);
        b.dataset.edge = inEF ? "remove_model" : "add_model";
        b.setAttribute("hx-vals", JSON.stringify({action: b.dataset.edge, variant: b.dataset.variant}));
        b.textContent = inEF ? "✓ in Edge Finder" : "+ Edge Finder";
      });
    }
    document.addEventListener("htmx:afterSwap", e => {
      mark();
      const sel = e.detail.target.querySelector && e.detail.target.querySelector("[data-start-from]");
      if (sel && sel.value) sel.dispatchEvent(new Event("change", {bubbles: true}));
      if (e.detail.target.id === "edge" && e.detail.requestConfig.path === "/lab/candidate") {
        const run = document.getElementById("run");
        if (run && !run.hidden) htmx.trigger(run, "open");             // the sweep form lists candidates
      }
    });
    // candidates: naming one takes two prompts, so it stays a click handler that fires the HTMX request
    document.addEventListener("click", e => {
      const b = e.target.closest("[data-cand=add]");
      if (!b) return;
      const name = prompt("Name this candidate (it can be loaded into the sweep form):", "");
      if (name === null) return;
      const why = prompt("Why is it worth exploring? (optional)", "") || "";
      htmx.ajax("POST", "/lab/candidate", {target: "#edge", swap: "innerHTML",
        values: {action: "add", name, why, variant: b.dataset.variant, strategy: b.dataset.strategy, csrf_token: csrf()}});
    });
    // the sweep form: start from a candidate or the defaults; highlight what differs from the starting point
    const fields = (form, name) => [...form.querySelectorAll(`[name="${name}"]`)];
    function readSettings(form) {
      const out = {};
      form.querySelectorAll("[data-setting]").forEach(l => {
        const name = l.dataset.setting, els = fields(form, name).filter(x => x.type !== "hidden");
        if (els.length && els[0].type === "checkbox" && els.length === 1) out[name] = els[0].checked;
        else if (els.length && els[0].type === "checkbox") out[name] = els.filter(x => x.checked).map(x => x.value);
        else if (els.length) out[name] = els[0].type !== "number" ? els[0].value : els[0].value === "" ? null : Number(els[0].value);
      });
      return out;
    }
    function fillSettings(form, st) {
      Object.entries(st).forEach(([name, v]) => {
        const els = fields(form, name).filter(x => x.type !== "hidden");
        if (!els.length) return;
        if (els[0].type === "checkbox" && els.length === 1) els[0].checked = !!v;
        else if (els[0].type === "checkbox") els.forEach(x => { x.checked = (v || []).includes(x.value); });
        else els[0].value = v === null ? "" : v;
      });
    }
    function markChanged(form) {
      const src = JSON.parse(form.dataset.source || "{}"), now = readSettings(form);
      let n = 0;
      form.querySelectorAll("[data-setting]").forEach(l => {
        const k = l.dataset.setting, a = JSON.stringify(now[k]), b = JSON.stringify(src[k]);
        const changed = src[k] !== undefined && a !== b && !(typeof now[k] === "number" && Number(src[k]) === now[k]);
        l.classList.toggle("changed", changed); if (changed) n++;
      });
      const c = form.querySelector("[data-changed-count]");
      if (c) c.textContent = n ? `${n} setting${n > 1 ? "s" : ""} changed from the starting point` : "";
    }
    document.addEventListener("change", e => {
      const sel = e.target.closest("[data-start-from]");
      if (sel) {
        const form = sel.form, st = JSON.parse(sel.selectedOptions[0].dataset.settings || "{}");
        form.dataset.source = JSON.stringify(Object.assign(JSON.parse(form.dataset.defaults), st));
        fillSettings(form, JSON.parse(form.dataset.source));
      }
      const form = e.target.closest("#sweep-form");
      if (form) markChanged(form);
    });
    document.addEventListener("input", e => { const form = e.target.closest("#sweep-form"); if (form) markChanged(form); });
    const hashKey = location.hash.slice(1);
    if (document.querySelector(`[data-section="${hashKey}"]`)) open.add(hashKey);
    [...open].forEach(k => show(k, true, hashKey === k));
    mark();
  }

  // --- Live replay: the slider picks a saved snapshot (HTMX fetches it); play steps through them ---
  const rp = document.getElementById("replay");
  if (rp) {
    const T = JSON.parse(rp.dataset.times), sl = document.getElementById("rp-slider"), lab = document.getElementById("rp-time"),
          play = document.getElementById("rp-play"), link = document.getElementById("rp-link"), paced = rp.dataset.pace === "real", base = rp.dataset.url;
    const at = s => Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8), +s.slice(9, 11), +s.slice(11, 13), +s.slice(13, 15));
    let speed = +rp.dataset.speed || 30, timer = null;
    function label() { const s = T[+sl.value]; lab.textContent = s.slice(9, 11) + ":" + s.slice(11, 13) + ":" + s.slice(13, 15) + " UTC · " + (+sl.value + 1) + " / " + T.length; }
    function show(i) {
      sl.value = Math.max(0, Math.min(T.length - 1, i)); label();
      const t = T[+sl.value];
      history.replaceState(null, "", base + "t=" + t); if (link) link.href = base + "t=" + t;
      return htmx.ajax("GET", base + "partial=1&t=" + t, {target: "#live", swap: "innerHTML"});
    }
    function stop() { clearTimeout(timer); timer = null; play.setAttribute("aria-pressed", "false"); play.textContent = "▶ Play"; }
    function tick() {
      const i = +sl.value;
      if (i >= T.length - 1) return stop();
      const wait = paced ? Math.max(150, (at(T[i + 1]) - at(T[i])) / speed) : 60000 / speed;   // updates hours apart: a fixed pace
      timer = setTimeout(() => show(i + 1).then(() => { if (timer) tick(); }), wait);
    }
    play.addEventListener("click", () => {
      if (timer) return stop();
      if (+sl.value >= T.length - 1) sl.value = 0;
      play.setAttribute("aria-pressed", "true"); play.textContent = "❚❚ Pause"; timer = 1; tick();
    });
    rp.querySelectorAll("[data-step]").forEach(b => b.addEventListener("click", () => { stop(); show(+sl.value + +b.dataset.step); }));
    rp.querySelectorAll("[data-speed]").forEach(b => b.addEventListener("click", () => {
      speed = +b.dataset.speed;
      rp.querySelectorAll("[data-speed]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    }));
    sl.addEventListener("input", label);
    sl.addEventListener("change", () => { stop(); show(+sl.value); });
    label();
  }
  });
})();
