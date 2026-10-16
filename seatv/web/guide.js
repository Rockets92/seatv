// Guida TV interattiva: legge i file statici in api/ (generati da `python -m seatv.build`)
// e disegna la griglia canali × orari. Tutti gli indirizzi sono relativi alla pagina.
"use strict";

const TZ = "Europe/Rome";
const PX_PER_MIN = 4; // 240 px per ora
const MIN = 60 * 1000;
const SOURCE_LABELS = { tivu: "Tivù La Guida", sky: "Sky Guida TV", xmltv: "XMLTV" };
const PLATFORM_LABELS = { dtt: "DTT", tivusat: "Tivùsat", sky: "Sky" };

// Scelte che restano tra un'apertura e l'altra (vista e piattaforma).
const saved = (() => {
  try { return JSON.parse(localStorage.getItem("seatv") || "{}"); } catch { return {}; }
})();
function remember() {
  try { localStorage.setItem("seatv", JSON.stringify({ view: state.view, platform: state.platform })); } catch { /* niente */ }
}

const VIEWS = ["grid", "now", "evening"];
const PLATFORMS = ["", "dtt", "tivusat", "sky"];

const state = {
  date: todayInRome(),
  // "grid": griglia oraria; "now": in onda adesso; "evening": prima e seconda serata.
  view: VIEWS.includes(saved.view) ? saved.view : "grid",
  platform: PLATFORMS.includes(saved.platform) ? saved.platform : "",
  source: "",
  query: "",
  guide: null,
  health: null,
  dayStart: 0,
  dayEnd: 0,
  // Giorni pubblicati (da api/health.json), da oggi in avanti.
  days: [],
  // Canali base mostrati in versione +1/+24: { skyuno: "skyunoplus1" }.
  shift: {},
};

const $ = (id) => document.getElementById(id);
const fmtTime = new Intl.DateTimeFormat("it-IT", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const fmtDayShort = new Intl.DateTimeFormat("it-IT", { timeZone: "UTC", weekday: "short" });
const fmtDayNum = new Intl.DateTimeFormat("it-IT", { timeZone: "UTC", day: "numeric", month: "short" });
const fmtDayLong = new Intl.DateTimeFormat("it-IT", { timeZone: "UTC", weekday: "long", day: "numeric", month: "long" });
const fmtStamp = new Intl.DateTimeFormat("it-IT", { timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

// --- date in ora italiana ---------------------------------------------

function todayInRome() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date());
}

function addDays(dateStr, days) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

function utcDate(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

// Millisecondi della mezzanotte italiana di quel giorno (gestisce l'ora legale).
function romeMidnight(dateStr) {
  const guess = utcDate(dateStr).getTime();
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    }).formatToParts(new Date(guess)).map((p) => [p.type, p.value])
  );
  const asRome = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute);
  return guess - (asRome - guess);
}

// --- dati ----------------------------------------------------------------

// Un file per giorno con tutti i canali; piattaforma, fonte e ricerca si
// filtrano qui, senza altre richieste.
const guideCache = new Map();

async function loadGuide() {
  $("status") && ($("status").textContent = "Caricamento della guida…");
  try {
    if (!state.health) {
      state.health = await apiGet("api/health.json");
      const today = todayInRome();
      state.days = (state.health.days || []).filter((d) => d >= today);
      if (!state.days.includes(state.date) && state.days.length) state.date = state.days[0];
      renderDays();
    }
    if (!guideCache.has(state.date)) guideCache.set(state.date, await apiGet(`api/guide/${state.date}.json`));
    state.guide = guideCache.get(state.date);
  } catch (err) {
    state.guide = null;
    renderStatus(err.status === 404 ? "Guida di questo giorno non ancora pubblicata." : `Impossibile leggere la guida: ${err.message}`);
    return;
  }
  state.dayStart = romeMidnight(state.date);
  state.dayEnd = romeMidnight(addDays(state.date, 1));
  renderSources();
  renderGuide();
}

async function apiGet(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) throw Object.assign(new Error(`HTTP ${response.status}`), { status: response.status });
  return response.json();
}

// --- disegno -----------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null) continue;
    if (key === "class") node.className = value;
    else if (key === "style") {
      // Le variabili CSS (--src) vanno impostate con setProperty.
      for (const [prop, v] of Object.entries(value)) {
        if (prop.startsWith("--")) node.style.setProperty(prop, v);
        else node.style[prop] = v;
      }
    }
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function sourceVar(source) {
  return { "--src": `var(--src-${source}, var(--idle))` };
}

function renderDays() {
  const list = $("day-list");
  list.replaceChildren();
  const today = todayInRome();
  // Solo i giorni pubblicati, da oggi in avanti.
  const days = state.days.length ? state.days : [today];
  $("prev-day").disabled = state.date <= days[0];
  $("next-day").disabled = state.date >= days[days.length - 1];
  for (const day of days) {
    const label = day === today ? "Oggi" : day === addDays(today, 1) ? "Domani" : day === addDays(today, -1) ? "Ieri" : capitalize(fmtDayShort.format(utcDate(day)));
    const button = el(
      "button",
      { type: "button", "aria-current": day === state.date ? "date" : null, onclick: () => setDate(day) },
      label,
      el("small", {}, fmtDayNum.format(utcDate(day)))
    );
    list.append(button);
  }
}

// Indirizzo assoluto di un file del sito, da incollare nel programma IPTV.
function siteUrl(path) {
  return new URL(path, location.href.replace(/[?#].*$/, "")).href;
}

const FEED_LABELS = {
  seatv: ["Id SEA-TV", "tvg-id come rai1, canale5"],
  iptvorg: ["Liste iptv-org", "tvg-id come Rai1.it o Rai1.it@HD"],
  epgshare: ["Liste epgshare01", "tvg-id come Rai.1.HD.it o La.5.it"],
};

function copyButton(url) {
  const button = el("button", {
    type: "button",
    class: "copy",
    onclick: async () => {
      try {
        await navigator.clipboard.writeText(url);
        button.textContent = "Copiato";
      } catch {
        button.textContent = "Copia a mano";
      }
      setTimeout(() => (button.textContent = "Copia"), 2000);
    },
  }, "Copia");
  return button;
}

// Un feed per schema di tvg-id: si sceglie quello che usa la propria playlist M3U.
function feedCard() {
  const rows = [];
  for (const feed of state.health?.feeds || []) {
    const [label, hint] = FEED_LABELS[feed.scheme] || [feed.scheme, ""];
    const url = siteUrl(feed.gz);
    const total = state.health?.channels ?? 0;
    const matched = feed.scheme === "seatv" ? "" : ` · ${feed.channels} canali su ${total} con i loro id`;
    rows.push(
      el("p", {}, el("strong", {}, label), ` (${hint}${matched})`),
      el("div", { class: "feed-url" }, el("code", {}, url), copyButton(url))
    );
  }
  const when = state.health?.generated_at ? fmtStamp.format(new Date(state.health.generated_at)) : "?";
  return el("article", { class: "source-card feed-card", style: { "--src": "var(--cyan)" } },
    el("h3", {}, "Feed EPG per l'IPTV"),
    el("p", {}, "Usa il feed che corrisponde ai tvg-id della tua playlist M3U.",
      (state.health?.feeds || []).every((f) => f.xml) ? " Togliendo .gz dall'indirizzo hai la versione non compressa." : ""),
    ...rows,
    el("p", {}, "Aggiornato: ", el("strong", {}, when), " · ", el("strong", {}, String(state.health?.programmes ?? 0)), " programmi")
  );
}

function renderSources() {
  const panel = $("sources-panel");
  panel.replaceChildren(feedCard());
  const runs = state.health?.sources || [];
  const dot = $("sources-dot");
  dot.className = "dot " + (state.health?.status === "ok" ? "ok" : runs.some((r) => r.error) ? "err" : "");

  if (!runs.length) {
    panel.append(el("p", { class: "status" }, "Nessuna fonte ancora scaricata."));
  }
  for (const run of runs) {
    const when = run.finished_at ? fmtStamp.format(new Date(run.finished_at)) : "in corso";
    panel.append(
      el("article", { class: "source-card", style: sourceVar(run.source) },
        el("h3", {}, el("span", { class: "dot " + (run.error ? "err" : "ok") }), SOURCE_LABELS[run.source] || run.source),
        el("p", {}, "Ultimo aggiornamento: ", el("strong", {}, when)),
        el("p", {}, el("strong", {}, String(run.channels)), " canali · ", el("strong", {}, String(run.programmes)), " programmi"),
        run.reused ? el("p", {}, el("strong", {}, String(run.reused)), " canali dall'aggiornamento precedente") : null,
        run.error ? el("p", { class: "error" }, run.error) : null
      )
    );
  }

  // Elenco fonti per il filtro: quelle con un'ingestione e quelle citate dai canali.
  const names = new Set(runs.map((r) => r.source));
  for (const row of state.guide?.channels || []) row.channel.sources.forEach((s) => names.add(s));
  const select = $("source-filter");
  const current = state.source;
  select.replaceChildren(el("option", { value: "" }, "Tutte le fonti"));
  for (const name of [...names].sort()) {
    select.append(el("option", { value: name }, SOURCE_LABELS[name] || name));
  }
  select.value = names.has(current) ? current : "";
  state.source = select.value;
}

function renderStatus(message, hint) {
  const box = el("div", { class: "status", id: "status" }, el("img", { src: "static/icon-192.png", alt: "" }), message);
  if (hint) box.append(el("br"), hint);
  $("guide").replaceChildren(box);
}

// Il canale si cerca per nome ("rai 3", "rai3") o per numero ("5", "105").
function matchesQuery(channel, query) {
  if (!query) return true;
  if (/^\d+$/.test(query)) {
    const numbers = state.platform ? [channel.numbers[state.platform]] : Object.values(channel.numbers);
    return numbers.some((n) => String(n) === query);
  }
  const compact = (text) => text.toLowerCase().replace(/[^a-z0-9àèéìòù+]/g, "");
  return channel.name.toLowerCase().includes(query) || compact(channel.name).includes(compact(query));
}

// Canali +1/+24 per canale base, dal ritardo più piccolo.
function variantsOf(guide) {
  if (!guide.variants) {
    const ids = new Set(guide.channels.map((row) => row.channel.id));
    guide.variants = new Map();
    for (const row of guide.channels) {
      const shift = row.channel.timeshift;
      if (!shift || !ids.has(shift.of)) continue;
      if (!guide.variants.has(shift.of)) guide.variants.set(shift.of, []);
      guide.variants.get(shift.of).push(row);
    }
    for (const rows of guide.variants.values()) rows.sort((a, b) => a.channel.timeshift.hours - b.channel.timeshift.hours);
  }
  return guide.variants;
}

// Righe da mostrare: { channel, programmes } del canale (o della sua versione
// +1/+24 scelta), con `base` il canale dell'elenco e `shifts` le sue versioni.
// I +1/+24 non compaiono da soli: si vedono toccando il canale base.
function visibleRows() {
  const query = state.query.trim().toLowerCase();
  const variants = variantsOf(state.guide);
  const hidden = new Set([...variants.values()].flat().map((row) => row.channel.id));
  const rows = (state.guide?.channels || []).filter(({ channel }) => {
    if (hidden.has(channel.id)) return false;
    if (state.platform && channel.numbers[state.platform] === undefined) return false;
    if (state.source && !channel.sources.includes(state.source)) return false;
    return matchesQuery(channel, query);
  });
  // Con una piattaforma scelta, in ordine di numero su quella piattaforma.
  if (state.platform) rows.sort((a, b) => a.channel.numbers[state.platform] - b.channel.numbers[state.platform]);
  return rows.map((row) => {
    const shifts = variants.get(row.channel.id) || [];
    const chosen = shifts.find((v) => v.channel.id === state.shift[row.channel.id]);
    return { ...(chosen || row), base: row.channel, shifts };
  });
}

// Tocco sul canale: base, poi +1 (e +24), poi di nuovo base.
function cycleShift(base, shifts) {
  const order = [base.id, ...shifts.map((row) => row.channel.id)];
  const next = order[(order.indexOf(state.shift[base.id] || base.id) + 1) % order.length];
  if (next === base.id) delete state.shift[base.id];
  else state.shift[base.id] = next;
  renderGuide();
}

// Logo del canale; per la versione +1/+24 con il ritardo in un angolo.
function rowLogo(channel, base) {
  const tile = logoTile(channel);
  if (channel.id !== base.id) tile.append(el("span", { class: "shift-tag" }, `+${channel.timeshift.hours}`));
  return tile;
}

// Proprietà del riquadro del canale: se ha versioni +1/+24, il tocco le alterna.
function shiftProps(base, shifts, cls) {
  if (!shifts.length) return { class: cls };
  const labels = shifts.map((row) => `+${row.channel.timeshift.hours}`).join(" o ");
  return {
    class: `${cls} shiftable${state.shift[base.id] ? " shifted" : ""}`,
    role: "button",
    tabindex: "0",
    "aria-label": `${base.name}: tocca per la programmazione ${labels}`,
    onclick: () => cycleShift(base, shifts),
    onkeydown: (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        cycleShift(base, shifts);
      }
    },
  };
}

function channelNumber(channel) {
  const n = channel.numbers;
  if (state.platform) return n[state.platform];
  return n.dtt ?? n.tivusat ?? n.sky;
}

function renderGuide() {
  if (!state.guide) return;
  document.body.dataset.view = state.view;
  renderOnAir();
  if (!state.guide.channels.length) {
    renderStatus("Nessun canale in questa guida.");
    return;
  }
  const rows = visibleRows();
  if (!rows.length) {
    renderStatus("Nessun canale corrisponde ai filtri.");
    return;
  }
  if (state.view !== "grid") {
    renderList(rows);
    return;
  }

  const width = ((state.dayEnd - state.dayStart) / MIN) * PX_PER_MIN;
  const grid = el("div", { class: "grid" });

  // Riga degli orari.
  const ticks = el("div", { class: "ticks", style: { width: `${width}px` } });
  for (let t = state.dayStart; t < state.dayEnd; t += 30 * MIN) {
    const label = fmtTime.format(new Date(t));
    ticks.append(
      el("div", { class: "tick" + (label.endsWith(":00") ? " hour" : ""), style: { left: `${x(t)}px` } }, label)
    );
  }
  grid.append(el("div", { class: "timeline" }, el("div", { class: "corner" }, capitalize(fmtDayLong.format(utcDate(state.date)))), ticks));

  const now = Date.now();
  for (const { channel, programmes, base, shifts } of rows) {
    const number = channelNumber(base);
    const chan = el("div", { ...shiftProps(base, shifts, "chan"), title: channel.name },
      el("span", { class: "chan-num" }, number ?? ""),
      rowLogo(channel, base),
      el("div", { class: "chan-text" },
        el("div", { class: "chan-name" }, channel.name),
        el("div", { class: "chan-src" }, ...channel.sources.map((s) => el("i", { title: SOURCE_LABELS[s] || s, style: sourceVar(s) })))
      )
    );

    const track = el("div", { class: "track", style: { width: `${width}px` } });
    programmes.forEach((programme, i) => {
      // Se la fonte sovrappone due programmi, il primo finisce dove inizia il successivo.
      const next = programmes[i + 1];
      const shown = next && Date.parse(next.start) < Date.parse(programme.stop) && Date.parse(next.start) > Date.parse(programme.start)
        ? { ...programme, stop: next.start }
        : programme;
      track.append(programmeBlock(channel, shown, now, programme));
    });
    grid.append(el("div", { class: "row" }, chan, track));
  }

  if (now >= state.dayStart && now < state.dayEnd) {
    grid.append(
      el("div", { class: "now-line", id: "now-line", style: { left: `calc(var(--chan-w) + ${x(now)}px)` } },
        el("span", {}, fmtTime.format(now)))
    );
  }

  const container = $("guide");
  const sameView = container.dataset.date === state.date && container.dataset.view === "grid";
  const keepScroll = sameView ? container.scrollLeft : null;
  const keepTop = sameView ? container.scrollTop : 0;
  container.replaceChildren(grid);
  container.dataset.date = state.date;
  container.dataset.view = "grid";
  container.scrollTop = keepTop;
  if (keepScroll !== null) container.scrollLeft = keepScroll;
  else scrollToNow(false);
  pinTitles();
}

// --- elenchi Adesso e Serata ----------------------------------------------

const EVENING_FROM = 20 * 60 + 25; // la prima serata inizia tra le 20:25...
const EVENING_TO = 22 * 60; // ...e le 22:00
const EVENING_AT = 21 * 60 + 30; // in mancanza, ciò che va in onda alle 21:30

// Programma in onda e successivo.
function nowPair(programmes, now) {
  const index = programmes.findIndex((p) => Date.parse(p.start) <= now && now < Date.parse(p.stop));
  return index < 0 ? [] : [programmes[index], programmes[index + 1]];
}

// Prima serata: il programma più lungo che inizia tra le 20:25 e le 22:00
// (o quello in onda alle 21:30); seconda serata: il primo dopo, di almeno 20 minuti.
function eveningPair(programmes) {
  const at = (minutes) => state.dayStart + minutes * MIN;
  const length = (p) => Date.parse(p.stop) - Date.parse(p.start);
  let main = null;
  for (const p of programmes) {
    const start = Date.parse(p.start);
    if (start >= at(EVENING_FROM) && start <= at(EVENING_TO) && length(p) >= 25 * MIN && (!main || length(p) > length(main))) main = p;
  }
  main ??= programmes.find((p) => Date.parse(p.start) <= at(EVENING_AT) && at(EVENING_AT) < Date.parse(p.stop));
  if (!main) return [];
  const after = programmes.slice(programmes.indexOf(main) + 1).find((p) => length(p) >= 20 * MIN);
  return [main, after];
}

function listCard(channel, programme, label, now, main) {
  const start = Date.parse(programme.start);
  const stop = Date.parse(programme.stop);
  const live = start <= now && now < stop;
  return el("button", {
    type: "button",
    class: "lprog" + (main ? " main" : "") + (live ? " live" : ""),
    style: sourceVar(programme.source),
    onclick: () => openDetail(channel, programme),
  },
    el("span", { class: "lp-when" }, `${label} `, el("b", {}, fmtTime.format(start), el("i", {}, ` – ${fmtTime.format(stop)}`))),
    el("span", { class: "lp-title" }, programme.title),
    programme.category ? el("span", { class: "lp-cat" }, programme.category) : null,
    live ? el("span", { class: "lp-bar" }, el("span", { style: { width: `${((now - start) / (stop - start)) * 100}%` } })) : null
  );
}

function renderList(rows) {
  const now = Date.now();
  const evening = state.view === "evening";
  const labels = evening ? ["Prima serata", "Seconda serata"] : ["Ora", "Dopo"];
  const items = [];
  for (const { channel, programmes, base, shifts } of rows) {
    const [first, second] = evening ? eveningPair(programmes) : nowPair(programmes, now);
    // Una versione +1/+24 scelta resta visibile anche senza programmi, per tornare indietro.
    if (!first && channel.id === base.id) continue;
    const number = channelNumber(base);
    items.push(el("div", { class: "lrow" },
      el("div", { ...shiftProps(base, shifts, "lchan"), title: channel.name },
        rowLogo(channel, base),
        el("span", { class: "lchan-name" }, number != null ? el("b", {}, `${number} `) : null, channel.name)
      ),
      el("div", { class: "lprogs" },
        first ? listCard(channel, first, labels[0], now, true) : el("p", { class: "status" }, "Nessun programma."),
        second ? listCard(channel, second, labels[1], now, false) : null
      )
    ));
  }
  const title = evening
    ? `Stasera in TV · ${capitalize(fmtDayLong.format(utcDate(state.date)))}`
    : `In onda adesso · ${fmtTime.format(now)}`;
  const list = el("div", { class: "list" },
    el("h2", { class: "list-head" }, title),
    ...(items.length ? items : [el("p", { class: "status" }, evening ? "Nessun programma in serata per questi canali." : "Nessun programma in onda per questi canali.")])
  );
  const container = $("guide");
  const keepTop = container.dataset.view === state.view && container.dataset.date === state.date ? container.scrollTop : 0;
  container.replaceChildren(list);
  container.dataset.date = state.date;
  container.dataset.view = state.view;
  container.scrollTop = keepTop;
  container.scrollLeft = 0;
}

// Se un programma inizia prima del bordo sinistro visibile, sposta il suo
// testo a destra così il titolo resta leggibile.
let pinned = [];
function pinTitles() {
  for (const inner of pinned) inner.style.transform = inner.style.width = "";
  pinned = [];
  const edge = $("guide").scrollLeft;
  for (const track of document.querySelectorAll(".track")) {
    for (const block of track.children) {
      const left = block.offsetLeft;
      const right = left + block.offsetWidth;
      if (left >= edge) break;
      if (right <= edge + 40) continue;
      const inner = block.firstElementChild;
      const shift = edge - left;
      inner.style.transform = `translateX(${shift}px)`;
      inner.style.width = `calc(100% - ${shift}px)`;
      pinned.push(inner);
      break;
    }
  }
}

let pinFrame = 0;
$("guide").addEventListener("scroll", () => {
  cancelAnimationFrame(pinFrame);
  pinFrame = requestAnimationFrame(pinTitles);
}, { passive: true });

function x(time) {
  return ((Math.max(time, state.dayStart) - state.dayStart) / MIN) * PX_PER_MIN;
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function initials(name) {
  // "Canale 5 +1" -> "C5": il ritardo si vede già nell'angolo del logo.
  return name.split(/\s+/).filter((w) => w && !w.startsWith("+")).map((w) => w[0]).join("").slice(0, 3).toUpperCase();
}

// Un logo quasi tutto bianco sparisce sul riquadro chiaro: si riconosce dalla
// luminosità media dei pixel visibili e gli si dà un riquadro scuro.
const lightLogos = new Map();
function isLightLogo(img) {
  if (lightLogos.has(img.src)) return lightLogos.get(img.src);
  let light = false;
  try {
    const size = 32;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, size, size);
    const data = ctx.getImageData(0, 0, size, size).data;
    let sum = 0;
    let weight = 0;
    for (let i = 0; i < data.length; i += 4) {
      const alpha = data[i + 3] / 255;
      if (alpha < 0.1) continue;
      sum += alpha * (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]);
      weight += alpha;
    }
    // Solo i loghi con sfondo trasparente: un logo su fondo bianco pieno resta com'è.
    const coverage = weight / (size * size);
    light = weight > 0 && coverage < 0.85 && sum / weight > 200;
  } catch {
    // Immagine di un altro sito (rimando alla fonte): non si può leggere, resta chiara.
  }
  lightLogos.set(img.src, light);
  return light;
}

// Riquadro col logo del canale, pubblicato insieme al sito; se manca, le iniziali.
function logoTile(channel) {
  const tile = el("div", { class: "logo-tile", title: channel.name });
  const fallback = () => {
    tile.classList.add("initials");
    tile.replaceChildren(initials(channel.name));
  };
  if (channel.logo) {
    const img = el("img", { src: channel.logo, alt: channel.name, loading: "lazy", decoding: "async" });
    img.addEventListener("error", fallback);
    img.addEventListener("load", () => {
      if (isLightLogo(img)) tile.classList.add("on-dark");
    });
    tile.append(img);
  } else {
    fallback();
  }
  return tile;
}

// Riga "In onda ora": una scheda per canale con il programma attuale e il successivo.
function renderOnAir() {
  const section = $("onair");
  const now = Date.now();
  if (state.date !== todayInRome()) {
    section.hidden = true;
    return;
  }
  const cards = [];
  for (const { channel, programmes, base } of visibleRows()) {
    const index = programmes.findIndex((p) => Date.parse(p.start) <= now && now < Date.parse(p.stop));
    if (index < 0) continue;
    const current = programmes[index];
    const next = programmes[index + 1];
    const start = Date.parse(current.start);
    const stop = Date.parse(current.stop);
    const number = channelNumber(base);
    cards.push(
      el("button", { type: "button", class: "onair-card", onclick: () => openDetail(channel, current) },
        logoTile(channel),
        el("span", { class: "oc-title" }, current.title),
        el("span", { class: "oc-sub" }, `${number != null ? number + " · " : ""}${channel.name} · fino alle ${fmtTime.format(stop)}`),
        el("span", { class: "oc-bar" }, el("span", { style: { width: `${((now - start) / (stop - start)) * 100}%` } })),
        el("span", { class: "oc-next" }, next ? `Dopo: ${fmtTime.format(Date.parse(next.start))} ${next.title}` : "")
      )
    );
  }
  section.hidden = !cards.length;
  $("onair-list").replaceChildren(...cards);
  $("clock").textContent = fmtTime.format(now);
}

function programmeBlock(channel, programme, now, original = programme) {
  const start = Date.parse(programme.start);
  const stop = Date.parse(programme.stop);
  const left = x(start);
  const right = x(Math.min(stop, state.dayEnd));
  const live = start <= now && now < stop;
  const block = el(
    "button",
    {
      type: "button",
      class: "prog" + (live ? " live" : stop <= now ? " past" : ""),
      style: { left: `${left}px`, width: `${Math.max(right - left - 2, 3)}px`, ...sourceVar(programme.source) },
      title: `${fmtTime.format(start)} ${programme.title}`,
      onclick: () => openDetail(channel, original),
    },
    // Il testo resta visibile anche quando l'inizio del programma è fuori schermo.
    el("span", { class: "inner" },
      el("span", { class: "t" }, programme.title),
      el("span", { class: "h" },
        `${fmtTime.format(start)} – ${fmtTime.format(Date.parse(original.stop))}`,
        programme.category ? el("span", { class: "cat" }, ` · ${programme.category}`) : null)
    )
  );
  if (live) {
    block.append(el("span", { class: "bar", style: { width: `${((now - start) / (stop - start)) * 100}%` } }));
  }
  return block;
}

function scrollToNow(smooth = true) {
  const container = $("guide");
  const now = Date.now();
  const target = now >= state.dayStart && now < state.dayEnd ? x(now - 30 * MIN) : x(state.dayStart + 18 * 60 * MIN);
  container.scrollTo({ left: target, behavior: smooth ? "smooth" : "auto" });
}

// --- dettaglio -----------------------------------------------------------

function openDetail(channel, programme) {
  const start = Date.parse(programme.start);
  const stop = Date.parse(programme.stop);
  const now = Date.now();
  const minutes = Math.round((stop - start) / MIN);

  const hero = $("detail-hero");
  hero.classList.toggle("noimg", !programme.image);
  hero.style.backgroundImage = programme.image ? `url("${encodeURI(programme.image)}")` : "";

  $("detail-channel").replaceChildren(
    logoTile(channel),
    el("span", {}, channel.name)
  );
  $("detail-title").textContent = programme.title;
  const day = new Intl.DateTimeFormat("it-IT", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" }).format(start);
  $("detail-time").textContent = `${capitalize(day)}, ${fmtTime.format(start)} – ${fmtTime.format(stop)} · ${minutes} min`;

  const progress = $("detail-progress");
  const live = start <= now && now < stop;
  progress.hidden = !live;
  if (live) progress.firstElementChild.style.width = `${((now - start) / (stop - start)) * 100}%`;

  const chips = [];
  if (live) chips.push(el("span", { class: "chip live" }, "IN ONDA"));
  if (programme.category) chips.push(el("span", { class: "chip" }, programme.category));
  chips.push(el("span", { class: "chip", style: sourceVar(programme.source) }, el("i"), `Fonte: ${SOURCE_LABELS[programme.source] || programme.source}`));
  for (const [platform, lcn] of Object.entries(channel.numbers)) {
    chips.push(el("span", { class: "chip" }, `${PLATFORM_LABELS[platform] || platform} ${lcn}`));
  }
  const tvgIds = [channel.id, ...Object.values(channel.ids || {}).flat()];
  for (const id of tvgIds) {
    chips.push(el("span", { class: "chip", title: "tvg-id da usare nella playlist M3U" }, `tvg-id: ${id}`));
  }
  $("detail-meta").replaceChildren(...chips);
  $("detail-desc").textContent = programme.description || "Nessuna descrizione disponibile.";

  $("detail").hidden = false;
  $("backdrop").hidden = false;
  $("detail-close").focus();
}

function closeDetail() {
  $("detail").hidden = true;
  $("backdrop").hidden = true;
}

// --- interazioni ---------------------------------------------------------

function setDate(day) {
  state.date = day;
  // Un altro giorno non ha un "adesso": si passa alla sua serata.
  if (state.view === "now" && day !== todayInRome()) {
    state.view = "evening";
    for (const tab of $("view-tabs").querySelectorAll("button")) tab.setAttribute("aria-selected", String(tab.dataset.view === "evening"));
  }
  renderDays();
  loadGuide();
}

function setPlatform(platform) {
  state.platform = platform;
  for (const tab of $("platform-tabs").querySelectorAll("button")) {
    tab.setAttribute("aria-selected", String(tab.dataset.platform === platform));
  }
  remember();
  renderGuide();
}

// Griglia, Adesso o Serata. "Adesso" vale solo per oggi; toccare di nuovo
// "Griglia" riporta all'ora attuale.
function setView(view) {
  const again = view === state.view;
  state.view = view;
  for (const tab of $("view-tabs").querySelectorAll("button")) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === view));
  }
  remember();
  const today = todayInRome();
  if (view === "now" && state.date !== today && state.days.includes(today)) {
    setDate(today);
    return;
  }
  renderGuide();
  if (view === "grid" && again) scrollToNow();
}

function stepDay(delta) {
  const index = state.days.indexOf(state.date) + delta;
  if (index >= 0 && index < state.days.length) setDate(state.days[index]);
}

$("prev-day").addEventListener("click", () => stepDay(-1));
$("next-day").addEventListener("click", () => stepDay(1));
$("platform-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("button[data-platform]");
  if (tab) setPlatform(tab.dataset.platform);
});
$("source-filter").addEventListener("change", (event) => {
  state.source = event.target.value;
  renderGuide();
});
$("search").addEventListener("input", (event) => {
  state.query = event.target.value;
  renderGuide();
});
$("view-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("button[data-view]");
  if (tab) setView(tab.dataset.view);
});
$("sources-toggle").addEventListener("click", () => {
  const panel = $("sources-panel");
  panel.hidden = !panel.hidden;
  $("sources-toggle").setAttribute("aria-expanded", String(!panel.hidden));
});
$("detail-close").addEventListener("click", closeDetail);
$("backdrop").addEventListener("click", closeDetail);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDetail();
});

// Aggiorna linea dell'ora e programmi in onda ogni minuto.
setInterval(() => {
  if (state.guide && state.date === todayInRome()) renderGuide();
}, 60 * 1000);

// La griglia occupa lo schermo sotto la barra dei filtri, che su telefono va a capo.
function syncToolbarHeight() {
  document.documentElement.style.setProperty("--toolbar-h", `${document.querySelector(".toolbar").offsetHeight}px`);
}
window.addEventListener("resize", syncToolbarHeight);
syncToolbarHeight();

// --- app installabile (PWA) ---------------------------------------------

const standalone = matchMedia("(display-mode: fullscreen), (display-mode: standalone)").matches || navigator.standalone === true;
const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
let installPrompt = null;

// Android e Chrome: il browser propone l'installazione, il pulsante la apre.
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  $("install").hidden = false;
});
window.addEventListener("appinstalled", () => {
  installPrompt = null;
  $("install").hidden = true;
});
// iPhone e iPad: Safari non ha un comando, si spiegano i due tocchi.
if (isIos && !standalone) $("install").hidden = false;

$("install").addEventListener("click", async () => {
  if (installPrompt) {
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    $("install").hidden = true;
  } else {
    $("ios-install").hidden = false;
  }
});
$("ios-install-close").addEventListener("click", () => { $("ios-install").hidden = true; });

if ("serviceWorker" in navigator && location.protocol !== "file:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

for (const tab of $("view-tabs").querySelectorAll("button")) tab.setAttribute("aria-selected", String(tab.dataset.view === state.view));
for (const tab of $("platform-tabs").querySelectorAll("button")) tab.setAttribute("aria-selected", String(tab.dataset.platform === state.platform));
document.body.dataset.view = state.view;
renderDays();
loadGuide();
