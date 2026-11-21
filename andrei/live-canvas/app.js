"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const stages = {
  intake: {label: "Intake", fn: "load_institution()", icon: "⇥", x: 45, y: 191, about: "Load alerts, policy, and the evidence available for this case."},
  red_flags: {label: "Red flags", fn: "red_flags()", icon: "⚑", x: 266, y: 97, about: "Check for evidence of suspicion and raise questions about unclear prose."},
  explainers: {label: "Explainers", fn: "explainers()", icon: "≋", x: 266, y: 299, about: "Match documents to activity, or identify which information is missing."},
  reader: {label: "Reader", fn: "reader.ask()", icon: "▤", x: 466, y: 97, about: "Answer evidence questions and return soft signals to the rulebook."},
  rulebook: {label: "Rulebook", fn: "decide()", icon: "◇", x: 466, y: 299, about: "Assess each alert and apply the highest-severity outcome to the case."},
  validate: {label: "Validation", fn: "check() · annotate()", icon: "✓", x: 700, y: 299, about: "Check verdict, evidence, and alert references. Record the audit fingerprints."},
  verdict: {label: "Verdict", fn: "Decision.output_row()", icon: "↗", x: 700, y: 99, about: "The case result written by the system."},
};
const institution = {bank: "Bank", emoney: "E-money", investment: "Investment", payments_fx: "Payments & FX"};
const stateLabel = {start: "Running", done: "Complete", skip: "Skipped", error: "Check issue"};
const timeFormat = new Intl.DateTimeFormat("en-GB", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
const gbp = new Intl.NumberFormat("en-GB", {style: "currency", currency: "GBP"});
const word = (value) => String(value).replaceAll("_", " ");
const when = (value) => timeFormat.format(new Date(value * 1000));
const verdictClass = (value) => ["CLOSE", "RFI", "ESCALATE"].includes(value) ? value.toLowerCase() : "pending";

const board = $("board"), viewport = $("viewport"), nodes = {};
let cases = new Map(), run = {}, runList = [], runId = "sample", cursor = 0, generation = 0;
let selected = "", stage = "rulebook", filter = "", followStage = true, manualRun = false;
let replay = null, replayTimer = 0, replayEvents = [], sample = [], zoom = 1, lastList = 0;
let serverAvailable = true, casesDirty = true;

for (const [id, spec] of Object.entries(stages)) {
  const button = el("button", "node");
  button.type = "button";
  button.dataset.stage = id;
  button.style.left = spec.x + "px";
  button.style.top = spec.y + "px";
  button.setAttribute("aria-pressed", "false");
  const icon = el("span", "node-icon", spec.icon);
  icon.setAttribute("aria-hidden", "true");
  const status = el("span", "node-status");
  const text = el("span", "", "Waiting");
  status.append(el("i"), text);
  button.append(icon, el("span", "node-label", spec.label), el("span", "node-subtitle", spec.fn), status);
  button.addEventListener("click", () => { stage = id; followStage = false; renderFocused(); });
  nodes[id] = {button, text};
  board.append(button);
}

function emptyCase(id) {
  return {id, nodes: {}, activity: [], active: "intake", verdict: null, evidence: ""};
}

function accept(c, e) {
  const n = c.nodes[e.stage] ??= {state: "waiting", data: {}, checks: [], answers: []};
  if (e.state === "check") n.checks.push(e.data);
  else if (e.state === "answer") n.answers.push(e.data);
  else if (e.state === "question") n.question = e.data;
  else {
    n.state = e.state;
    n.data = {...n.data, ...e.data};
  }
  c.active = e.stage;
  if (e.stage === "intake") c.input = e.data;
  if (e.stage === "verdict") c.verdict = e.data.verdict;
  if (e.state !== "check" || e.data.signals.length || e.data.questions.length) {
    c.activity.unshift(e);
    if (c.activity.length > 60) c.activity.pop();
  }
}

function take(events) {
  for (const e of events) {
    if (e.stage === "run") {
      Object.assign(run, e.data, {state: e.state});
      casesDirty = true;
      continue;
    }
    if (!stages[e.stage] || !e.case_id) continue;
    if (!cases.has(e.case_id)) {
      cases.set(e.case_id, emptyCase(e.case_id));
      casesDirty = true;
    }
    if (!selected) { selected = e.case_id; stage = e.stage; }
    const c = cases.get(e.case_id);
    accept(c, e);
    if (e.stage === "intake" || e.stage === "verdict") casesDirty = true;
    if (selected === e.case_id && followStage) stage = e.stage;
  }
}

function status(id, n) {
  if (!n) return "Waiting";
  if (id === "verdict" && n.data.verdict) return n.data.verdict;
  if (n.state === "done" && ["red_flags", "explainers"].includes(id)) {
    return n.data.signal_count ? n.data.signal_count + " signal" + (n.data.signal_count === 1 ? "" : "s") : "No signals";
  }
  if (n.state === "done" && id === "reader") return n.data.answer_count + " answer" + (n.data.answer_count === 1 ? "" : "s");
  if (n.state === "done" && id === "intake") {
    const count = n.data.counts?.alerts ?? 0;
    return count + (count === 1 ? " alert loaded" : " alerts loaded");
  }
  if (n.state === "done" && id === "rulebook") return n.data.verdict;
  if (n.state === "done" && id === "validate") return "Checks passed";
  return stateLabel[n.state] ?? "Waiting";
}

function renderList() {
  if (!casesDirty) return;
  casesDirty = false;
  const found = [...cases.values()];
  $("case-count").textContent = found.length;
  const counts = {CLOSE: 0, RFI: 0, ESCALATE: 0};
  found.forEach((c) => { if (c.verdict) counts[c.verdict]++; });
  const assessed = Object.values(counts).reduce((prev, n) => prev + n, 0);
  const metrics = [["Processed", assessed + " / " + (run.cases ?? found.length), ""], ["Closed", counts.CLOSE, "close"],
    ["Information requested", counts.RFI, "rfi"], ["Escalated", counts.ESCALATE, "escalate"]];
  $("metrics").replaceChildren(...metrics.map(([label, value, cls]) => {
    const card = el("div", "metric " + cls);
    card.append(el("span", "", label), el("strong", "", value));
    return card;
  }));
  const search = $("case-search").value.trim().toLowerCase();
  const list = $("case-list");
  const scroll = list.scrollTop;
  const focus = list.contains(document.activeElement) ? document.activeElement.dataset.case : null;
  const matches = found.filter((c) => (!filter || c.verdict === filter) &&
    [c.id, c.input?.customer?.name, c.input?.institution].some((x) => String(x ?? "").toLowerCase().includes(search)));
  list.replaceChildren(...matches.map((c) => {
    const button = el("button", "case-button");
    button.type = "button";
    button.dataset.case = c.id;
    button.setAttribute("aria-pressed", String(selected === c.id));
    const row = el("span", "case-row");
    row.append(el("span", "case-id", c.id), el("span", "pill " + verdictClass(c.verdict), c.verdict ?? "Active"));
    button.append(row, el("span", "case-name", c.input?.customer?.name ?? institution[c.input?.institution] ?? "Pending intake"));
    button.addEventListener("click", () => selectCase(c.id));
    return button;
  }));
  if (!matches.length) list.append(el("p", "empty", found.length ? "No matching cases." : "Waiting for cases."));
  list.scrollTop = scroll;
  if (focus) [...list.children].find((n) => n.dataset.case === focus)?.focus({preventScroll: true});
}

function selectCase(id) {
  stopReplay();
  selected = id;
  followStage = true;
  stage = cases.get(id)?.verdict ? "rulebook" : cases.get(id)?.active ?? "intake";
  casesDirty = true;
  render();
}

function section(title) {
  const box = el("section");
  box.append(el("h4", "", title));
  return box;
}
function values(entries) {
  const list = el("dl");
  for (const [key, v] of Object.entries(entries ?? {})) {
    if (v == null || v === "") continue;
    list.append(el("dt", "", word(key)), el("dd", "", typeof v === "object" ? JSON.stringify(v) : String(v)));
  }
  return list;
}
function chips(ids, c) {
  const line = el("div", "evidence");
  for (const id of new Set(ids ?? [])) {
    const available = c?.input?.documents?.some((d) => d.id === id) ||
      c?.input?.transactions?.some((t) => t.transaction_id === id);
    const chip = el(available ? "button" : "span", "chip", id);
    if (available) {
      chip.type = "button";
      chip.title = "Inspect evidence " + id;
      chip.addEventListener("click", () => { c.evidence = c.evidence === id ? "" : id; renderInspector(c); });
    }
    line.append(chip);
  }
  return line;
}
function card(title, code, body) {
  const box = el("div", "mini");
  box.append(el("strong", "", title));
  if (code) box.append(el("p", "code", code));
  if (body) box.append(el("p", "", body));
  return box;
}
function questionCard(q) {
  return card(word(q.id ?? q.question), q.alert_id ?? "", q.text);
}

function renderInspector(c) {
  const panel = $("inspector");
  const scroll = panel.scrollTop;
  const n = c?.nodes[stage];
  const node = stages[stage];
  const label = status(stage, n);
  panel.replaceChildren(el("span", "pill " + verdictClass(label), label),
    el("h3", "", node.label), el("p", "inspect-summary", node.about));
  if (!n) { panel.append(el("p", "empty", "Waiting for this stage.")); return; }
  const d = n.data;
  if (c.evidence) {
    const evidence = c.input?.documents?.find((x) => x.id === c.evidence) ??
      c.input?.transactions?.find((x) => x.transaction_id === c.evidence);
    if (evidence) {
      const info = section("Evidence · " + c.evidence);
      info.append(values(evidence));
      const clear = el("button", "secondary", "Dismiss");
      clear.type = "button";
      clear.addEventListener("click", () => { c.evidence = ""; renderInspector(c); });
      info.append(clear);
      panel.append(info);
    }
  }
  if (stage === "intake") {
    const context = section("Case context");
    context.append(values({...d.customer, ...d.counts, ...d.window, held_payment: d.held_payment_id}));
    panel.append(context);
    for (const alert of d.alerts ?? []) {
      const info = section(alert.rule_id + " · " + (alert.rule_name ?? alert.policy?.name ?? alert.alert_id));
      if (alert.message) info.append(el("p", "", alert.message));
      info.append(values(alert.measured));
      if (alert.policy?.fires_when) info.append(card("Policy trigger", "", alert.policy.fires_when));
      panel.append(info);
    }
    if (Object.keys(d.policy_limits ?? {}).length) {
      const limits = section("Additional policy limits");
      limits.append(values(d.policy_limits));
      panel.append(limits);
    }
    const docs = section("Evidence on file");
    docs.append(chips((d.documents ?? []).map((x) => x.id), c));
    for (const t of d.transactions ?? []) {
      const row = card(t.transaction_id, t.direction, t.amount_gbp != null ? gbp.format(t.amount_gbp) : "");
      row.append(values({counterparty: t.counterparty_name, channel: t.channel, booked_at: t.booked_at}));
      docs.append(row);
    }
    panel.append(docs);
  }
  if (["red_flags", "explainers"].includes(stage)) {
    const found = section("Signals and questions");
    let count = 0;
    for (const check of n.checks) {
      for (const signal of check.signals) {
        const item = card(word(signal.kind) + " · " + signal.strength, signal.code, signal.facts);
        item.append(values({function: check.function, alert: signal.alert_id}), chips(signal.evidence, c));
        found.append(item);
        count++;
      }
      for (const q of check.questions) { found.append(questionCard(q)); count++; }
    }
    if (!count) found.append(el("p", "empty", "No signals or questions from the checks so far."));
    panel.append(found);
    const functions = section("Functions checked · " + n.checks.length);
    n.checks.forEach((check) => functions.append(values({[check.function + "()"]: check.signals.length + " signals · " + check.questions.length + " questions"})));
    panel.append(functions);
  }
  if (stage === "reader") {
    const content = section("Reader activity");
    if (d.reason) content.append(el("p", "", d.reason));
    if (n.question && n.state === "start") content.append(questionCard(n.question));
    for (const a of n.answers) {
      const info = card("Tier " + a.tier + " · " + a.value, a.model, a.text);
      info.append(values({probability_yes: a.probability, cached: a.cached, assigned_code: a.signal?.code}));
      if (a.quote) info.append(el("blockquote", "", a.quote));
      info.append(chips(a.evidence, c));
      content.append(info);
    }
    if (!n.answers.length && d.questions) for (const q of d.questions) content.append(questionCard(q));
    if (d.unresolved !== undefined) content.append(values({unresolved_questions: d.unresolved}));
    panel.append(content);
  }
  if (stage === "rulebook") {
    const alerts = c.nodes.validate?.data.alerts ?? d.alerts ?? [];
    if (d.reason) panel.append(el("p", "", d.reason));
    const paths = section("Per-alert decision");
    if (!alerts.length) paths.append(values({signals: d.signal_count, reader_answers: d.answer_count}));
    for (const a of alerts) {
      const item = card(a.rule_id + " · " + a.verdict, (a.codes ?? []).join(" · "), (a.facts ?? []).join(" "));
      item.append(values({alert: a.alert_id, path: a.path}), chips(a.evidence, c));
      if (a.sop?.length) {
        const sop = el("details");
        sop.append(el("summary", "", "Policy clauses"), ...a.sop.map((line) => el("blockquote", "", line.replaceAll("**", ""))));
        item.append(sop);
      }
      paths.append(item);
    }
    panel.append(paths);
  }
  if (stage === "validate") {
    const checks = section("Output validation");
    if (d.problems) checks.append(el("p", "", d.problems.length ? d.problems.join(" · ") : "Evidence references, verdict code, and alert IDs validated."));
    const audit = section("Audit fingerprints");
    audit.append(values(d.audit));
    panel.append(checks, audit);
  }
  if (stage === "verdict") {
    const outcome = section("Case outcome");
    outcome.append(card(d.verdict ?? "Pending", d.reason_code, d.reason), chips(d.evidence, c));
    panel.append(outcome);
  }
  panel.scrollTop = scroll;
}

function eventText(e) {
  const d = e.data;
  if (e.state === "check") return word(d.function) + " · " + (d.signals.map((s) => s.code).join(", ") || "question raised");
  if (e.state === "answer") return "Tier " + d.tier + " · " + d.value + (d.probability != null ? " · p(yes) " + d.probability : "");
  if (e.state === "question") return "Tier " + d.tier + " · " + word(d.id);
  if (e.state === "skip") return d.reason;
  if (e.stage === "verdict") return d.verdict + " · " + d.reason_code;
  return status(e.stage, {state: e.state, data: d});
}

function renderFocused() {
  const c = replay ?? cases.get(selected);
  $("flow-case").textContent = c ? [c.id, c.input?.customer?.name, institution[c.input?.institution]].filter(Boolean).join(" · ") : "Select a case";
  $("replay").hidden = runId !== "sample" || !selected;
  $("replay").classList.toggle("is-playing", Boolean(replay));
  $("replay").textContent = replay ? "Stop replay" : "Replay case";
  $("live-tip").hidden = runId !== "sample";
  const activity = $("events");
  const wasFocused = activity.scrollTop;
  activity.replaceChildren(...(c?.activity ?? []).map((e) => {
    const li = el("li");
    const desc = el("span");
    desc.append(el("strong", "", stages[e.stage].label), el("small", "", eventText(e)));
    li.append(desc, el("time", "", when(e.at)));
    return li;
  }));
  activity.scrollTop = wasFocused;
  if (!activity.children.length) activity.append(el("li", "empty", "Waiting for case activity."));
  $("activity-note").textContent = c?.activity.length ? c.activity.length + " latest events" : "Event stream";
  for (const [id, dom] of Object.entries(nodes)) {
    const n = c?.nodes[id];
    dom.button.className = "node " + ({start: "running", done: "done", skip: "skipped", error: "error"}[n?.state] ?? "");
    dom.button.setAttribute("aria-pressed", String(stage === id));
    const label = status(id, n);
    dom.text.textContent = label;
    dom.text.className = verdictClass(label);
  }
  for (const wire of board.querySelectorAll(".wires path")) {
    const a = c?.nodes[wire.dataset.from], b = c?.nodes[wire.dataset.to];
    const skipped = b?.state === "skip" || a?.state === "skip";
    wire.classList.toggle("skipped", skipped || (!b && Boolean(wire.dataset.reader)));
    const suppliedQuestions = wire.dataset.to !== "reader" || a?.checks.some((check) => check.questions.length);
    wire.classList.toggle("used", Boolean(!skipped && suppliedQuestions && a?.state === "done" && b && b.state !== "waiting"));
  }
  renderInspector(c);
}

function render() {
  renderList();
  renderFocused();
  const connected = $("connection");
  const title = !serverAvailable ? "Connection lost" : runId === "sample" ? "Sample replay" :
    run.state === "done" ? "Run complete" : run.state === "error" ? "Run failed" : "Live run";
  connected.className = "connection " + (!serverAvailable || run.state === "error" ? "offline" :
    runId !== "sample" && run.state !== "done" ? "running" : "");
  connected.replaceChildren(el("i"), document.createTextNode(title));
  $("run-foot").textContent = run.output_fp ? "Output fingerprint " + run.output_fp : runId === "sample" ?
    "Invented cases · simulated reader answers" : run.reason ?? "Payper Trail · Track 1";
}

function stopReplay() { clearTimeout(replayTimer); replay = null; replayEvents = []; }
function play() {
  if (replay) { stopReplay(); stage = "rulebook"; renderFocused(); return; }
  replayEvents = sample.filter((e) => e.case_id === selected);
  if (!replayEvents.length) return;
  replay = emptyCase(selected);
  followStage = true;
  const next = () => {
    const e = replayEvents.shift();
    if (!e) { stopReplay(); if (followStage) stage = "verdict"; renderFocused(); return; }
    accept(replay, e);
    if (followStage) stage = e.stage;
    renderFocused();
    replayTimer = setTimeout(next, e.state === "check" ? 60 : 470);
  };
  next();
}
async function json(url) {
  const response = await fetch(url, {cache: "no-store"});
  if (!response.ok) throw new Error("Request failed (" + response.status + ")");
  return response.json();
}
function openRun(id) {
  stopReplay();
  generation++;
  runId = id;
  cursor = 0;
  selected = "";
  stage = "intake";
  followStage = true;
  cases = new Map();
  casesDirty = true;
  run = {...runList.find((r) => r.id === id)};
  $("run-picker").value = id;
  $("start-tip").hidden = true;
  $("live-tip").setAttribute("aria-expanded", "false");
  if (id === "sample") {
    take(sample);
    stage = "rulebook";
  }
  render();
}
async function poll() {
  try {
    if (Date.now() - lastList > 1700) {
      lastList = Date.now();
      const list = await json("/api/runs");
      if (JSON.stringify(list) !== JSON.stringify(runList)) {
        runList = list;
        const picker = $("run-picker");
        picker.replaceChildren(new Option("Sample replay", "sample"), ...list.map((r) =>
          new Option((institution[r.institution] ?? r.institution) + " · " + when(r.at), r.id)));
        if (runId !== "sample" && !list.some((r) => r.id === runId)) openRun("sample");
        else picker.value = runId;
      }
      if (!manualRun && runId === "sample" && list[0] && !replay) openRun(list[0].id);
    }
    serverAvailable = true;
    if (runId !== "sample") {
      const current = generation;
      const data = await json("/api/runs/" + runId + "?after=" + cursor);
      if (current === generation && data.events.length) {
        cursor = data.cursor;
        take(data.events);
        render();
      } else if ($("connection").classList.contains("offline")) render();
    } else if ($("connection").classList.contains("offline")) render();
  } catch {
    serverAvailable = false;
    render();
  } finally {
    setTimeout(poll, run.state === "done" ? 800 : 420);
  }
}

function setZoom(value) {
  zoom = Math.min(1.5, Math.max(.42, value));
  board.style.transform = "scale(" + zoom + ")";
  $("board-wrap").style.width = 908 * zoom + "px";
  $("board-wrap").style.height = 482 * zoom + "px";
  $("zoom-fit").textContent = Math.round(zoom * 100) + "%";
}
function fit() { setZoom(Math.max(.65, (viewport.clientWidth - 15) / 908)); }
let drag;
viewport.addEventListener("pointerdown", (e) => {
  if (e.target.closest("button") || e.button !== 0) return;
  drag = {x: e.clientX, y: e.clientY, left: viewport.scrollLeft, top: viewport.scrollTop};
  viewport.classList.add("panning");
  viewport.setPointerCapture(e.pointerId);
});
viewport.addEventListener("pointermove", (e) => {
  if (!drag) return;
  viewport.scrollLeft = drag.left + drag.x - e.clientX;
  viewport.scrollTop = drag.top + drag.y - e.clientY;
});
viewport.addEventListener("lostpointercapture", () => { drag = null; viewport.classList.remove("panning"); });
$("zoom-fit").addEventListener("click", fit);
$("zoom-out").addEventListener("click", () => setZoom(zoom / 1.16));
$("zoom-in").addEventListener("click", () => setZoom(zoom * 1.16));
$("case-search").addEventListener("input", () => { casesDirty = true; renderList(); });
$("run-picker").addEventListener("change", (e) => { manualRun = true; openRun(e.target.value); });
for (const b of document.querySelectorAll("[data-filter]")) {
  b.addEventListener("click", () => {
    filter = b.dataset.filter;
    for (const other of document.querySelectorAll("[data-filter]")) other.setAttribute("aria-pressed", String(other === b));
    casesDirty = true;
    renderList();
  });
}
$("replay").addEventListener("click", () => { manualRun = true; play(); });
$("live-tip").addEventListener("click", () => {
  const tip = $("start-tip");
  tip.hidden = !tip.hidden;
  $("live-tip").setAttribute("aria-expanded", String(!tip.hidden));
});
new ResizeObserver(fit).observe(viewport);
json("/examples.json").then((data) => { sample = data; openRun("sample"); })
  .catch(() => { serverAvailable = false; render(); })
  .finally(poll);
