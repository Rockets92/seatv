// Guida TV interattiva: legge /guide e /health e disegna la griglia canali × orari.
"use strict";

const TZ = "Europe/Rome";
const PX_PER_MIN = 4; // 240 px per ora
const MIN = 60 * 1000;
const SOURCE_LABELS = { tivu: "Tivù La Guida", sky: "Sky Guida TV", xmltv: "XMLTV" };
const PLATFORM_LABELS = { dtt: "DTT", tivusat: "Tivùsat", sky: "Sky" };

const state = {
  date: todayInRome(),
  platform: "",
  source: "",
  query: "",
  guide: null,
  health: null,
  dayStart: 0,
  dayEnd: 0,
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

async function loadGuide() {
  $("status") && ($("status").textContent = "Caricamento della guida…");
  const params = new URLSearchParams({ date: state.date });
  if (state.platform) params.set("platform", state.platform);
  try {
    const [guide, health] = await Promise.all([
      fetch(`/guide?${params}`).then(checked),
      fetch("/health").then(checked),
    ]);
    state.guide = guide;
    state.health = health;
  } catch (err) {
    state.guide = null;
    renderStatus(`Impossibile leggere la guida: ${err.message}`);
    return;
  }
  state.dayStart = romeMidnight(state.date);
  state.dayEnd = romeMidnight(addDays(state.date, 1));
  renderSources();
  renderGuide();
}

function checked(response) {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
  // Da ieri l'altro a fra quattro giorni; le frecce vanno oltre.
  for (let offset = -2; offset <= 4; offset++) {
    const day = addDays(today, offset);
    const label = day === today ? "Oggi" : day === addDays(today, 1) ? "Domani" : day === addDays(today, -1) ? "Ieri" : fmtDayShort.format(utcDate(day));
    const button = el(
      "button",
      { type: "button", "aria-current": day === state.date ? "date" : null, onclick: () => setDate(day) },
      label,
      el("small", {}, fmtDayNum.format(utcDate(day)))
    );
    list.append(button);
  }
}

function renderSources() {
  const panel = $("sources-panel");
  panel.replaceChildren();
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
  const box = el("div", { class: "status", id: "status" }, el("img", { src: "/static/icon-192.png", alt: "" }), message);
  if (hint) box.append(el("br"), hint);
  $("guide").replaceChildren(box);
}

function visibleRows() {
  const query = state.query.trim().toLowerCase();
  return (state.guide?.channels || []).filter(({ channel }) => {
    if (state.source && !channel.sources.includes(state.source)) return false;
    if (query && !channel.name.toLowerCase().includes(query)) return false;
    return true;
  });
}

function channelNumber(channel) {
  const n = channel.numbers;
  if (state.platform) return n[state.platform];
  return n.dtt ?? n.tivusat ?? n.sky;
}

function renderGuide() {
  if (!state.guide) return;
  renderOnAir();
  if (!state.guide.channels.length) {
    const hint = el("span", {}, "Avvia lo scaricamento con ", el("code", {}, "python -m seatv.ingest"), " e ricarica la pagina.");
    renderStatus("Nessun canale nel database.", hint);
    return;
  }
  const rows = visibleRows();
  if (!rows.length) {
    renderStatus("Nessun canale corrisponde ai filtri.");
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
  for (const { channel, programmes } of rows) {
    const number = channelNumber(channel);
    const chan = el("div", { class: "chan", title: channel.name },
      el("span", { class: "chan-num" }, number ?? ""),
      logoTile(channel),
      el("div", { class: "chan-text" },
        el("div", { class: "chan-name" }, channel.name),
        el("div", { class: "chan-src" }, ...channel.sources.map((s) => el("i", { title: SOURCE_LABELS[s] || s, style: sourceVar(s) })))
      )
    );

    const track = el("div", { class: "track", style: { width: `${width}px` } });
    for (const programme of programmes) {
      track.append(programmeBlock(channel, programme, now));
    }
    grid.append(el("div", { class: "row" }, chan, track));
  }

  if (now >= state.dayStart && now < state.dayEnd) {
    grid.append(
      el("div", { class: "now-line", id: "now-line", style: { left: `calc(var(--chan-w) + ${x(now)}px)` } },
        el("span", {}, fmtTime.format(now)))
    );
  }

  const container = $("guide");
  const keepScroll = container.dataset.date === state.date ? container.scrollLeft : null;
  container.replaceChildren(grid);
  container.dataset.date = state.date;
  if (keepScroll !== null) container.scrollLeft = keepScroll;
  else scrollToNow(false);
  pinTitles();
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
  return name.split(/\s+/).map((w) => w[0]).join("").slice(0, 3).toUpperCase();
}

// Riquadro col logo del canale, servito dalla cache di SEA-TV; se manca, le iniziali.
function logoTile(channel) {
  const tile = el("div", { class: "logo-tile", title: channel.name });
  const fallback = () => {
    tile.classList.add("initials");
    tile.replaceChildren(initials(channel.name));
  };
  if (channel.logo) {
    const img = el("img", { src: `/channels/${encodeURIComponent(channel.id)}/logo`, alt: channel.name, loading: "lazy", decoding: "async" });
    img.addEventListener("error", fallback);
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
  for (const { channel, programmes } of visibleRows()) {
    const index = programmes.findIndex((p) => Date.parse(p.start) <= now && now < Date.parse(p.stop));
    if (index < 0) continue;
    const current = programmes[index];
    const next = programmes[index + 1];
    const start = Date.parse(current.start);
    const stop = Date.parse(current.stop);
    const number = channelNumber(channel);
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

function programmeBlock(channel, programme, now) {
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
      onclick: () => openDetail(channel, programme),
    },
    // Il testo resta visibile anche quando l'inizio del programma è fuori schermo.
    el("span", { class: "inner" },
      el("span", { class: "t" }, programme.title),
      el("span", { class: "h" },
        `${fmtTime.format(start)} – ${fmtTime.format(stop)}`,
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

  const number = channelNumber(channel);
  $("detail-channel").replaceChildren(
    logoTile(channel),
    number != null ? el("span", { class: "chan-num" }, String(number)) : "",
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
  renderDays();
  loadGuide();
}

function setPlatform(platform) {
  state.platform = platform;
  for (const tab of $("platform-tabs").querySelectorAll("button")) {
    tab.setAttribute("aria-selected", String(tab.dataset.platform === platform));
  }
  loadGuide();
}

$("prev-day").addEventListener("click", () => setDate(addDays(state.date, -1)));
$("next-day").addEventListener("click", () => setDate(addDays(state.date, 1)));
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
$("jump-now").addEventListener("click", () => {
  if (state.date !== todayInRome()) setDate(todayInRome());
  else scrollToNow();
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

renderDays();
loadGuide();
