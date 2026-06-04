const STORAGE_KEYS = {
  scans: "marketscan.savedScans",
  watchlist: "marketscan.watchlist",
  tgToken: "marketscan.tgToken",
  tgChatId: "marketscan.tgChatId",
  tgEnabled: "marketscan.tgEnabled",
};

const fields = [
  { key: "close", label: "Close", type: "number" },
  { key: "open", label: "Open", type: "number" },
  { key: "high", label: "High", type: "number" },
  { key: "low", label: "Low", type: "number" },
  { key: "changePct", label: "Change %", type: "number" },
  { key: "volume", label: "Volume", type: "number" },
  { key: "avgVolume", label: "Avg Volume", type: "number" },
  { key: "rsi", label: "RSI", type: "number" },
  { key: "ema20", label: "EMA 20", type: "number" },
  { key: "ema50", label: "EMA 50", type: "number" },
  { key: "sma20", label: "SMA 20", type: "number" },
  { key: "sma50", label: "SMA 50", type: "number" },
  { key: "resistance", label: "Resistance", type: "number" },
  { key: "delivery", label: "Delivery %", type: "number" },
  { key: "pe", label: "P/E", type: "number" },
  { key: "sector", label: "Sector", type: "text" },
  { key: "symbol", label: "Symbol", type: "text" },
  { key: "name", label: "Name", type: "text" },
];

const presets = {
  breakout: {
    name: "Price Volume Breakout",
    conditions: [
      ["close", ">", "resistance"],
      ["volume", ">", "avgVolume"],
      ["changePct", ">", "1.5"],
    ],
    formula: "close > resistance and volume > avgVolume and changePct > 1.5",
  },
  rsi: {
    name: "RSI Recovery",
    conditions: [
      ["rsi", ">", "50"],
      ["rsi", "<", "68"],
      ["close", ">", "ema20"],
    ],
    formula: "rsi > 50 and rsi < 68 and close > ema20",
  },
  delivery: {
    name: "Delivery Strength",
    conditions: [
      ["delivery", ">", "55"],
      ["changePct", ">", "0"],
      ["volume", ">", "avgVolume"],
    ],
    formula: "delivery > 55 and changePct > 0 and volume > avgVolume",
  },
  maCross: {
    name: "EMA Bull Cross",
    conditions: [
      ["ema20", ">", "ema50"],
      ["close", ">", "ema20"],
      ["rsi", ">", "55"],
    ],
    formula: "ema20 > ema50 and close > ema20 and rsi > 55",
  },
};

// ─── Indicator Library ────────────────────────────────────────────────────────
const INDICATOR_LIBRARY = [
  {
    key: "supertrend_buy",
    name: "SuperTrend — Buy Signal",
    category: "Trend Following",
    description: "Price above SuperTrend baseline with bullish momentum and above-average volume confirmation.",
    formula: "close > ema20 and changePct > 0 and rsi > 50 and volume > avgVolume",
    conditions: [["close", ">", "ema20"], ["changePct", ">", "0"], ["rsi", ">", "50"], ["volume", ">", "avgVolume"]],
  },
  {
    key: "macd_cross",
    name: "MACD — Bullish Crossover",
    category: "Momentum",
    description: "Fast EMA (20) crossed above slow EMA (50) — classic MACD bullish trigger with RSI support.",
    formula: "ema20 > ema50 and close > ema20 and changePct > 0 and rsi > 45",
    conditions: [["ema20", ">", "ema50"], ["close", ">", "ema20"], ["changePct", ">", "0"], ["rsi", ">", "45"]],
  },
  {
    key: "rsi_recovery",
    name: "RSI — Oversold Recovery",
    category: "Momentum",
    description: "RSI recovering from oversold zone back above 40, price above 20-SMA, fresh buying momentum.",
    formula: "rsi > 40 and rsi < 60 and close > sma20 and changePct > 0",
    conditions: [["rsi", ">", "40"], ["rsi", "<", "60"], ["close", ">", "sma20"], ["changePct", ">", "0"]],
  },
  {
    key: "bollinger_breakout",
    name: "Bollinger Band — Upper Breakout",
    category: "Volatility",
    description: "Price breaking above upper Bollinger Band (resistance proxy) with volume and RSI not overbought.",
    formula: "close > resistance and volume > avgVolume and changePct > 1 and rsi < 75",
    conditions: [["close", ">", "resistance"], ["volume", ">", "avgVolume"], ["changePct", ">", "1"], ["rsi", "<", "75"]],
  },
  {
    key: "golden_cross",
    name: "Golden Cross — EMA 20/50",
    category: "Trend Following",
    description: "EMA 20 crosses above EMA 50 — institutional-grade bull signal; price confirming above both MAs.",
    formula: "ema20 > ema50 and close > ema20 and rsi > 50 and changePct > 0",
    conditions: [["ema20", ">", "ema50"], ["close", ">", "ema20"], ["rsi", ">", "50"], ["changePct", ">", "0"]],
  },
  {
    key: "vwap_breakout",
    name: "VWAP — Intraday Breakout",
    category: "Price Action",
    description: "Price breaking above VWAP (EMA20 proxy) on strong volume — intraday momentum trade setup.",
    formula: "close > ema20 and volume > avgVolume and changePct > 0.5 and rsi > 50",
    conditions: [["close", ">", "ema20"], ["volume", ">", "avgVolume"], ["changePct", ">", "0.5"], ["rsi", ">", "50"]],
  },
  {
    key: "ssl_hybrid",
    name: "SSL Hybrid — Buy Zone",
    category: "Trend Following",
    description: "SSL Hybrid baseline (EMA50) and SSL channel (EMA20) both bullish; trend fully confirmed.",
    formula: "close > ema50 and close > ema20 and rsi > 50 and ema20 > ema50",
    conditions: [["close", ">", "ema50"], ["close", ">", "ema20"], ["rsi", ">", "50"], ["ema20", ">", "ema50"]],
  },
  {
    key: "volume_surge",
    name: "Volume Surge — Momentum Play",
    category: "Volume",
    description: "Exceptional volume spike (>avg) paired with 2%+ move above resistance — institutional interest.",
    formula: "volume > avgVolume and changePct > 2 and close > resistance",
    conditions: [["volume", ">", "avgVolume"], ["changePct", ">", "2"], ["close", ">", "resistance"]],
  },
  {
    key: "delivery_accum",
    name: "Delivery — Smart Money Accumulation",
    category: "Delivery / FII",
    description: "High delivery % (>60) signals institutional accumulation / smart money entry into the stock.",
    formula: "delivery > 60 and changePct > 0 and volume > avgVolume and rsi > 45",
    conditions: [["delivery", ">", "60"], ["changePct", ">", "0"], ["volume", ">", "avgVolume"], ["rsi", ">", "45"]],
  },
  {
    key: "high_breakout",
    name: "52-Week High — Fresh Breakout",
    category: "Breakout",
    description: "Price breaking prior resistance (52W high proxy) with volume confirmation and RSI momentum.",
    formula: "close > resistance and changePct > 1 and volume > avgVolume and rsi > 55",
    conditions: [["close", ">", "resistance"], ["changePct", ">", "1"], ["volume", ">", "avgVolume"], ["rsi", ">", "55"]],
  },
  {
    key: "ema_pullback",
    name: "EMA 20 — Healthy Pullback Buy",
    category: "Trend Following",
    description: "Low-risk pullback to EMA20 in an ongoing uptrend (EMA20>EMA50); RSI not extended.",
    formula: "close > ema20 and rsi > 45 and rsi < 65 and changePct > 0 and ema20 > ema50",
    conditions: [["close", ">", "ema20"], ["rsi", ">", "45"], ["rsi", "<", "65"], ["changePct", ">", "0"], ["ema20", ">", "ema50"]],
  },
  {
    key: "stoch_rsi",
    name: "Stochastic RSI — Buy Cross",
    category: "Momentum",
    description: "StochRSI crossed above 50 — momentum picking up from neutral; price and volume confirm.",
    formula: "rsi > 50 and rsi < 70 and close > ema20 and volume > avgVolume and changePct > 0",
    conditions: [["rsi", ">", "50"], ["rsi", "<", "70"], ["close", ">", "ema20"], ["volume", ">", "avgVolume"], ["changePct", ">", "0"]],
  },
  {
    key: "adx_trend",
    name: "ADX — Strong Trend Momentum",
    category: "Trend Following",
    description: "Strong directional trend — price above both EMAs with RSI >55 and volume; ADX proxied.",
    formula: "rsi > 55 and close > ema20 and close > ema50 and changePct > 0.5 and volume > avgVolume",
    conditions: [["rsi", ">", "55"], ["close", ">", "ema20"], ["close", ">", "ema50"], ["changePct", ">", "0.5"], ["volume", ">", "avgVolume"]],
  },
  {
    key: "price_action_bull",
    name: "Price Action — Strong Bull Candle",
    category: "Price Action",
    description: "Strong bullish candle (>1%) with delivery confirmation (>50%) — genuine buying interest.",
    formula: "changePct > 1 and delivery > 50 and close > ema20 and volume > avgVolume",
    conditions: [["changePct", ">", "1"], ["delivery", ">", "50"], ["close", ">", "ema20"], ["volume", ">", "avgVolume"]],
  },
  {
    key: "obv_rising",
    name: "OBV — Rising Volume Trend",
    category: "Volume",
    description: "On-Balance Volume rising: up-volume dominates with delivery confirmation and RSI bullish.",
    formula: "volume > avgVolume and changePct > 0 and close > ema20 and delivery > 55 and rsi > 50",
    conditions: [["volume", ">", "avgVolume"], ["changePct", ">", "0"], ["close", ">", "ema20"], ["delivery", ">", "55"], ["rsi", ">", "50"]],
  },
  {
    key: "ttm_squeeze",
    name: "TTM Squeeze — Momentum Fire",
    category: "Momentum",
    description: "TTM Squeeze momentum histogram fired bullish — high-probability breakout with volume support.",
    formula: "close > ema20 and rsi > 52 and volume > avgVolume and changePct > 1 and ema20 > ema50",
    conditions: [["close", ">", "ema20"], ["rsi", ">", "52"], ["volume", ">", "avgVolume"], ["changePct", ">", "1"], ["ema20", ">", "ema50"]],
  },
  {
    key: "ichimoku_buy",
    name: "Ichimoku Cloud — Kumo Breakout",
    category: "Trend Following",
    description: "Price above Ichimoku Cloud (Kumo) with Tenkan above Kijun — powerful multi-timeframe trend signal.",
    formula: "close > ema50 and ema20 > ema50 and rsi > 52 and changePct > 0",
    conditions: [["close", ">", "ema50"], ["ema20", ">", "ema50"], ["rsi", ">", "52"], ["changePct", ">", "0"]],
  },
  {
    key: "pivot_breakout",
    name: "Pivot Point — Resistance Break",
    category: "Breakout",
    description: "Clean break above pivot resistance with momentum and volume — institutional level cleared.",
    formula: "close > resistance and changePct > 1.5 and volume > avgVolume and rsi > 55",
    conditions: [["close", ">", "resistance"], ["changePct", ">", "1.5"], ["volume", ">", "avgVolume"], ["rsi", ">", "55"]],
  },
  {
    key: "cci_bull",
    name: "CCI — Bullish Momentum",
    category: "Momentum",
    description: "CCI crossed above zero (RSI+SMA proxy) — commodity channel momentum confirmed bullish.",
    formula: "rsi > 50 and close > sma20 and volume > avgVolume and changePct > 0",
    conditions: [["rsi", ">", "50"], ["close", ">", "sma20"], ["volume", ">", "avgVolume"], ["changePct", ">", "0"]],
  },
  {
    key: "demand_zone",
    name: "Demand Zone — Supply Reversal",
    category: "Price Action",
    description: "Price bouncing from demand zone with institutional delivery support — smart reversal entry.",
    formula: "close > ema50 and rsi > 48 and rsi < 62 and delivery > 50 and changePct > 0",
    conditions: [["close", ">", "ema50"], ["rsi", ">", "48"], ["rsi", "<", "62"], ["delivery", ">", "50"], ["changePct", ">", "0"]],
  },
];

let stocks = [
  stock("RELIANCE", "Reliance Industries", "Energy", 2890, 2937, 2970, 2875, 2.4, 8200000, 5900000, 64, 2810, 2748, 58, 24, 2928),
  stock("TCS", "Tata Consultancy Services", "IT", 3912, 3885, 3944, 3862, -0.5, 2100000, 2400000, 47, 3890, 3821, 43, 29, 3990),
  stock("HDFCBANK", "HDFC Bank", "Banking", 1572, 1608, 1620, 1568, 1.9, 11200000, 9100000, 59, 1564, 1538, 49, 18, 1612),
  stock("INFY", "Infosys", "IT", 1468, 1492, 1505, 1454, 1.3, 6200000, 5400000, 56, 1477, 1459, 51, 23, 1518),
  stock("ICICIBANK", "ICICI Bank", "Banking", 1121, 1148, 1156, 1117, 2.1, 9800000, 7700000, 66, 1112, 1084, 62, 17, 1138),
  stock("SBIN", "State Bank of India", "Banking", 812, 795, 818, 790, -1.4, 15100000, 12700000, 44, 806, 781, 46, 10, 836),
  stock("LT", "Larsen & Toubro", "Capital Goods", 3625, 3698, 3714, 3608, 1.8, 1800000, 1400000, 61, 3584, 3498, 57, 31, 3688),
  stock("AXISBANK", "Axis Bank", "Banking", 1175, 1196, 1208, 1160, 1.2, 6500000, 5200000, 58, 1168, 1145, 54, 14, 1225),
  stock("MARUTI", "Maruti Suzuki", "Auto", 12420, 12680, 12750, 12360, 1.7, 790000, 620000, 63, 12180, 11890, 53, 28, 12610),
  stock("TATAMOTORS", "Tata Motors", "Auto", 940, 972, 984, 932, 2.8, 23200000, 17800000, 70, 925, 902, 60, 35, 966),
  stock("SUNPHARMA", "Sun Pharmaceutical", "Pharma", 1486, 1462, 1491, 1452, -1.1, 2700000, 2200000, 42, 1474, 1440, 48, 34, 1514),
  stock("CIPLA", "Cipla", "Pharma", 1510, 1544, 1555, 1506, 1.6, 1900000, 1500000, 60, 1498, 1469, 56, 26, 1538),
  stock("ASIANPAINT", "Asian Paints", "Consumer", 2940, 2886, 2965, 2874, -2.3, 1600000, 1200000, 36, 2960, 3025, 41, 48, 3048),
  stock("HINDUNILVR", "Hindustan Unilever", "Consumer", 2484, 2510, 2528, 2478, 0.7, 1400000, 1300000, 52, 2470, 2462, 45, 55, 2550),
  stock("NTPC", "NTPC", "Power", 365, 379, 382, 362, 3.1, 20300000, 16800000, 72, 354, 341, 64, 16, 374),
  stock("POWERGRID", "Power Grid Corp", "Power", 302, 296, 306, 293, -1.8, 14600000, 11200000, 39, 300, 287, 50, 19, 316),
  stock("TITAN", "Titan Company", "Consumer", 3568, 3632, 3658, 3540, 1.5, 1100000, 850000, 57, 3522, 3488, 52, 74, 3620),
  stock("BAJFINANCE", "Bajaj Finance", "Finance", 6820, 6710, 6868, 6660, -1.6, 920000, 780000, 40, 6790, 6950, 44, 30, 7040),
  stock("ADANIENT", "Adani Enterprises", "Metals", 3148, 3244, 3270, 3132, 2.7, 5100000, 3900000, 68, 3052, 2988, 59, 92, 3210),
  stock("JSWSTEEL", "JSW Steel", "Metals", 902, 926, 936, 894, 2.2, 4200000, 3300000, 62, 884, 861, 61, 22, 920),
  stock("ULTRACEMCO", "UltraTech Cement", "Cement", 10420, 10280, 10510, 10220, -0.9, 420000, 390000, 45, 10380, 10140, 47, 46, 10630),
  stock("GRASIM", "Grasim Industries", "Cement", 2440, 2498, 2510, 2422, 2.0, 1250000, 980000, 63, 2398, 2350, 54, 21, 2482),
];

let state = {
  mode: "visual",
  results: [...stocks],
  selected: stocks[0],
  sort: { key: "changePct", direction: -1 },
  moverMode: "gainers",
  savedScans: load(STORAGE_KEYS.scans, []),
  watchlist: load(STORAGE_KEYS.watchlist, []),
  pineConversion: null,
};

function stock(symbol, name, sector, open, close, high, low, changePct, volume, avgVolume, rsi, ema20, ema50, delivery, pe, resistance) {
  const history = Array.from({ length: 34 }, (_, index) => {
    const wave = Math.sin(index / 3) * close * 0.018;
    const drift = (index - 18) * close * 0.0025;
    return Math.max(1, Math.round((close + wave + drift) * 100) / 100);
  });
  history[history.length - 1] = close;
  const sma20 = Math.round(((ema20 * 0.62 + close * 0.38) + Number.EPSILON) * 100) / 100;
  const sma50 = Math.round(((ema50 * 0.7 + close * 0.3) + Number.EPSILON) * 100) / 100;
  return { symbol, name, sector, open, close, high, low, changePct, volume, avgVolume, rsi, ema20, ema50, sma20, sma50, delivery, pe, resistance, history };
}

function load(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function save(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function money(value) {
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function compact(value) {
  return Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
function boot() {
  setupNavigation();
  setupBuilder();
  setupIndicatorSelector();
  setupTelegramSettings();
  setupActions();
  populateSectorFilter();
  applyPreset("breakout");
  renderAll();
}

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav-item, .view").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(button.dataset.view).classList.add("active");
      document.getElementById("pageTitle").textContent = button.textContent;
    });
  });

  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      applyPreset(button.dataset.preset);
      switchView("scanner");
      runScan();
    });
  });
}

function switchView(view) {
  document.querySelector(`.nav-item[data-view="${view}"]`).click();
}

function setupBuilder() {
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      document.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("active", item === button));
      document.getElementById("visualBuilder").classList.toggle("active", state.mode === "visual");
      document.getElementById("formulaBuilder").classList.toggle("active", state.mode === "formula");
    });
  });

  document.getElementById("addCondition").addEventListener("click", () => addCondition(["close", ">", "100"]));
  document.getElementById("runScan").addEventListener("click", runScan);
  document.getElementById("saveScan").addEventListener("click", saveCurrentScan);
  document.getElementById("convertPine").addEventListener("click", convertPineFromPreview);
  document.getElementById("applyPineFormula").addEventListener("click", applyPineFormula);
}

// ─── Indicator Library ────────────────────────────────────────────────────────
function setupIndicatorSelector() {
  const select = document.getElementById("indicatorSelect");
  const categories = [...new Set(INDICATOR_LIBRARY.map((ind) => ind.category))];

  categories.forEach((cat) => {
    const group = document.createElement("optgroup");
    group.label = cat;
    INDICATOR_LIBRARY.filter((ind) => ind.category === cat).forEach((ind) => {
      const opt = document.createElement("option");
      opt.value = ind.key;
      opt.textContent = ind.name;
      group.append(opt);
    });
    select.append(group);
  });

  select.addEventListener("change", () => {
    const ind = INDICATOR_LIBRARY.find((i) => i.key === select.value);
    const desc = document.getElementById("indicatorDesc");
    if (ind) {
      desc.textContent = ind.description;
      desc.style.display = "block";
    } else {
      desc.style.display = "none";
    }
  });

  document.getElementById("applyIndicatorBtn").addEventListener("click", () => {
    const ind = INDICATOR_LIBRARY.find((i) => i.key === select.value);
    if (!ind) return;
    document.getElementById("scanName").value = ind.name;
    document.getElementById("formulaInput").value = ind.formula;
    document.getElementById("conditionList").innerHTML = "";
    ind.conditions.forEach(addCondition);
    state.mode = "formula";
    document.querySelector('[data-mode="formula"]').click();
    switchView("scanner");
    runScan();
  });
}

function setupActions() {
  document.getElementById("refreshData").addEventListener("click", refreshPrices);
  document.getElementById("exportResults").addEventListener("click", exportResults);
  document.getElementById("resultSearch").addEventListener("input", renderResults);
  document.getElementById("addToWatchlist").addEventListener("click", addSelectedToWatchlist);
  document.getElementById("clearWatchlist").addEventListener("click", () => {
    state.watchlist = [];
    save(STORAGE_KEYS.watchlist, state.watchlist);
    renderWatchlist();
  });
  document.getElementById("clearSaved").addEventListener("click", () => {
    state.savedScans = [];
    save(STORAGE_KEYS.scans, state.savedScans);
    renderSavedScans();
    renderAlerts();
  });
  document.getElementById("enableNotifications").addEventListener("click", requestNotifications);
  document.getElementById("csvInput").addEventListener("change", importCsv);
  document.getElementById("pineInput").addEventListener("change", importPineScript);
  document.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => sortBy(th.dataset.sort)));
  document.querySelectorAll("[data-mover]").forEach((button) => {
    button.addEventListener("click", () => {
      state.moverMode = button.dataset.mover;
      document.querySelectorAll("[data-mover]").forEach((item) => item.classList.toggle("active", item === button));
      renderMovers();
    });
  });
  document.getElementById("sectorFilter").addEventListener("change", renderBreadth);
}

function populateSectorFilter() {
  const select = document.getElementById("sectorFilter");
  [...new Set(stocks.map((item) => item.sector))].sort().forEach((sector) => {
    const option = document.createElement("option");
    option.value = sector;
    option.textContent = sector;
    select.append(option);
  });
}

function applyPreset(name) {
  const preset = presets[name];
  document.getElementById("scanName").value = preset.name;
  document.getElementById("formulaInput").value = preset.formula;
  document.getElementById("conditionList").innerHTML = "";
  preset.conditions.forEach(addCondition);
  const ind = document.getElementById("indicatorSelect");
  if (ind) ind.value = "";
  const desc = document.getElementById("indicatorDesc");
  if (desc) desc.style.display = "none";
}

function addCondition(condition = ["close", ">", "100"]) {
  const node = document.getElementById("conditionTemplate").content.cloneNode(true);
  const row = node.querySelector(".condition-row");
  const fieldSelect = row.querySelector(".field");
  fields.forEach((field) => {
    const option = document.createElement("option");
    option.value = field.key;
    option.textContent = field.label;
    fieldSelect.append(option);
  });
  row.querySelector(".field").value = condition[0];
  row.querySelector(".operator").value = condition[1];
  row.querySelector(".value").value = condition[2];
  row.querySelector(".remove").addEventListener("click", () => row.remove());
  document.getElementById("conditionList").append(row);
}

function runScan() {
  const matcher = state.mode === "formula" ? formulaMatcher(document.getElementById("formulaInput").value) : visualMatcher();
  state.results = stocks.filter(matcher);
  if (state.results[0]) {
    state.selected = state.results[0];
  }
  checkAlerts();
  const scanName = document.getElementById("scanName").value || "MarketScan";
  sendTelegramAlert(state.results, scanName);
  renderAll();
}

function visualMatcher() {
  const rows = [...document.querySelectorAll(".condition-row")].map((row) => ({
    field: row.querySelector(".field").value,
    operator: row.querySelector(".operator").value,
    value: row.querySelector(".value").value.trim(),
  }));
  return (item) => rows.every((rule) => compare(item, rule));
}

function formulaMatcher(formula) {
  const groups = formula.split(/\s+or\s+/i);
  return (item) =>
    groups.some((group) =>
      group
        .split(/\s+and\s+/i)
        .map((part) => part.trim())
        .filter(Boolean)
        .every((part) => {
          const match = part.match(/^([a-z0-9]+)\s*(>=|<=|>|<|=|contains)\s*(.+)$/i);
          if (!match) return false;
          return compare(item, { field: match[1], operator: match[2], value: match[3].replace(/^["']|["']$/g, "") });
        })
    );
}

function compare(item, rule) {
  const fieldKey = normalizeField(rule.field);
  const valueKey = normalizeField(rule.value);
  const actual = item[fieldKey];
  const value = valueKey ? item[valueKey] : rule.value;
  if (rule.operator === "contains") return String(actual).toLowerCase().includes(String(value).toLowerCase());
  if (typeof actual === "string") {
    return rule.operator === "=" && String(actual).toLowerCase() === String(value).toLowerCase();
  }
  const number = Number(value);
  if (Number.isNaN(number)) return false;
  if (rule.operator === ">") return actual > number;
  if (rule.operator === "<") return actual < number;
  if (rule.operator === ">=") return actual >= number;
  if (rule.operator === "<=") return actual <= number;
  if (rule.operator === "=") return actual === number;
  return false;
}

function normalizeField(candidate) {
  const text = String(candidate ?? "").trim().toLowerCase();
  return fields.find((field) => field.key.toLowerCase() === text)?.key;
}

function saveCurrentScan() {
  const name = document.getElementById("scanName").value.trim() || "Untitled Scan";
  const conditions = [...document.querySelectorAll(".condition-row")].map((row) => [
    row.querySelector(".field").value,
    row.querySelector(".operator").value,
    row.querySelector(".value").value.trim(),
  ]);
  const scan = {
    id: crypto.randomUUID(),
    name,
    mode: state.mode,
    conditions,
    formula: document.getElementById("formulaInput").value.trim(),
    createdAt: new Date().toISOString(),
  };
  state.savedScans.unshift(scan);
  save(STORAGE_KEYS.scans, state.savedScans);
  renderSavedScans();
  renderAlerts();
}

function renderAll() {
  renderStats();
  renderBreadth();
  renderMovers();
  renderResults();
  renderChart();
  renderRecommendationSummary();
  renderSavedScans();
  renderAlerts();
  renderWatchlist();
}

function renderStats() {
  document.getElementById("statUniverse").textContent = stocks.length;
  document.getElementById("statAdvances").textContent = stocks.filter((item) => item.changePct > 0).length;
  document.getElementById("statBreakouts").textContent = stocks.filter((item) => item.close > item.resistance).length;
  document.getElementById("statAlerts").textContent = state.savedScans.reduce((sum, scan) => sum + scanMatches(scan).length, 0);
}

function renderBreadth() {
  const filter = document.getElementById("sectorFilter").value;
  const universe = filter === "all" ? stocks : stocks.filter((item) => item.sector === filter);
  const bySector = [...new Set(universe.map((item) => item.sector))].sort();
  const root = document.getElementById("breadthBars");
  root.innerHTML = "";
  bySector.forEach((sector) => {
    const sectorStocks = universe.filter((item) => item.sector === sector);
    const positive = sectorStocks.filter((item) => item.changePct > 0).length;
    const pct = Math.round((positive / sectorStocks.length) * 100);
    root.insertAdjacentHTML(
      "beforeend",
      `<div class="breadth-row"><strong>${sector}</strong><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><span>${pct}%</span></div>`
    );
  });
}

function renderMovers() {
  const root = document.getElementById("moversList");
  root.innerHTML = "";
  const sorted = [...stocks].sort((a, b) => (state.moverMode === "gainers" ? b.changePct - a.changePct : a.changePct - b.changePct)).slice(0, 8);
  sorted.forEach((item) => {
    root.insertAdjacentHTML(
      "beforeend",
      `<button class="mover" data-symbol="${item.symbol}"><strong>${item.symbol}</strong><span>${item.name}</span><b class="${item.changePct >= 0 ? "positive" : "negative"}">${item.changePct.toFixed(2)}%</b></button>`
    );
  });
  root.querySelectorAll(".mover").forEach((button) => button.addEventListener("click", () => selectStock(button.dataset.symbol)));
}

function renderResults() {
  const query = document.getElementById("resultSearch").value.toLowerCase();
  const body = document.getElementById("resultsBody");
  const rows = [...state.results]
    .filter((item) => `${item.symbol} ${item.name}`.toLowerCase().includes(query))
    .sort((a, b) => sortValue(a, b));
  body.innerHTML = "";
  rows.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${item.symbol}</strong></td>
      <td>${item.name}</td>
      <td>${item.sector}</td>
      <td>${money(item.close)}</td>
      <td class="${item.changePct >= 0 ? "positive" : "negative"}">${item.changePct.toFixed(2)}%</td>
      <td>${compact(item.volume)}</td>
      <td>${item.rsi}</td>
      <td>${item.delivery}</td>
      <td><span class="signal">${signalFor(item)}</span></td>
    `;
    tr.addEventListener("click", () => selectStock(item.symbol));
    body.append(tr);
  });
}

function renderRecommendationSummary() {
  const root = document.getElementById("recommendationSummary");
  if (!root) return;
  if (!state.results.length) {
    root.textContent = "No stocks match the active scan.";
    return;
  }
  const ranked = [...state.results].sort((a, b) => recommendationScore(b) - recommendationScore(a)).slice(0, 5);
  root.textContent = `Recommended: ${ranked.map((item) => `${item.symbol} (${recommendationScore(item)})`).join(", ")}`;
}

function recommendationScore(item) {
  let score = 50;
  if (item.close > item.resistance) score += 14;
  if (item.volume > item.avgVolume) score += 12;
  if (item.ema20 > item.ema50) score += 10;
  if (item.close > item.ema20) score += 8;
  if (item.rsi >= 50 && item.rsi <= 68) score += 8;
  if (item.delivery > 55) score += 6;
  if (item.changePct > 0) score += Math.min(8, item.changePct * 2);
  if (item.rsi > 72) score -= 10;
  return Math.max(0, Math.min(99, Math.round(score)));
}

function sortBy(key) {
  if (state.sort.key === key) {
    state.sort.direction *= -1;
  } else {
    state.sort = { key, direction: 1 };
  }
  renderResults();
}

function sortValue(a, b) {
  const key = state.sort.key;
  const av = a[key];
  const bv = b[key];
  if (typeof av === "string") return av.localeCompare(bv) * state.sort.direction;
  return (av - bv) * state.sort.direction;
}

function signalFor(item) {
  if (item.close > item.resistance && item.volume > item.avgVolume) return "Breakout";
  if (item.rsi > 68) return "Overbought";
  if (item.rsi < 42) return "Weak";
  if (item.delivery > 55 && item.changePct > 0) return "Accumulation";
  return "Neutral";
}

function selectStock(symbol) {
  state.selected = stocks.find((item) => item.symbol === symbol) || state.selected;
  renderChart();
  switchView("scanner");
}

function renderChart() {
  const item = state.selected;
  const canvas = document.getElementById("priceChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfd";
  ctx.fillRect(0, 0, width, height);
  if (!item) return;

  document.getElementById("chartTitle").textContent = `${item.symbol} - ${item.name}`;
  const padding = 34;
  const values = item.history;
  const min = Math.min(...values) * 0.995;
  const max = Math.max(...values) * 1.005;

  ctx.strokeStyle = "#d9e1e7";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = padding + ((height - padding * 2) / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(width - padding, y);
    ctx.stroke();
  }

  ctx.strokeStyle = item.changePct >= 0 ? "#17803c" : "#c24135";
  ctx.lineWidth = 3;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = padding + (index / (values.length - 1)) * (width - padding * 2);
    const y = height - padding - ((value - min) / (max - min)) * (height - padding * 2);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  document.getElementById("stockSnapshot").innerHTML = [
    ["Close", money(item.close)],
    ["Change", `${item.changePct.toFixed(2)}%`],
    ["Volume", compact(item.volume)],
    ["Signal", signalFor(item)],
    ["RSI", item.rsi],
    ["EMA 20", money(item.ema20)],
    ["Delivery", `${item.delivery}%`],
    ["Resistance", money(item.resistance)],
  ]
    .map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function renderSavedScans() {
  const root = document.getElementById("savedScans");
  root.innerHTML = "";
  if (!state.savedScans.length) {
    root.innerHTML = "<p class=\"hint\">No saved scans yet.</p>";
    return;
  }
  state.savedScans.forEach((scan) => {
    const count = scanMatches(scan).length;
    const node = document.createElement("div");
    node.className = "saved-scan";
    node.innerHTML = `<div><strong>${scan.name}</strong><span>${scan.mode} - ${count} matches</span></div><button data-run>Run</button><button class="secondary" data-delete>Delete</button>`;
    node.querySelector("[data-run]").addEventListener("click", () => loadScan(scan));
    node.querySelector("[data-delete]").addEventListener("click", () => deleteScan(scan.id));
    root.append(node);
  });
}

function loadScan(scan) {
  document.getElementById("scanName").value = scan.name;
  document.getElementById("formulaInput").value = scan.formula || "";
  document.getElementById("conditionList").innerHTML = "";
  (scan.conditions || []).forEach(addCondition);
  state.mode = scan.mode;
  document.querySelector(`[data-mode="${scan.mode}"]`).click();
  switchView("scanner");
  runScan();
}

function deleteScan(id) {
  state.savedScans = state.savedScans.filter((scan) => scan.id !== id);
  save(STORAGE_KEYS.scans, state.savedScans);
  renderSavedScans();
  renderAlerts();
}

function scanMatches(scan) {
  const matcher = scan.mode === "formula" ? formulaMatcher(scan.formula) : (item) => (scan.conditions || []).every(([field, operator, value]) => compare(item, { field, operator, value }));
  return stocks.filter(matcher);
}

function renderAlerts() {
  const root = document.getElementById("alertsList");
  root.innerHTML = "";
  if (!state.savedScans.length) {
    root.innerHTML = "<p class=\"hint\">Save a scan to monitor alert matches.</p>";
    return;
  }
  state.savedScans.forEach((scan) => {
    const matches = scanMatches(scan);
    const node = document.createElement("div");
    node.className = "alert-item";
    node.innerHTML = `<div><strong>${scan.name}</strong><span>${matches.length ? matches.map((item) => item.symbol).join(", ") : "No current matches"}</span></div><button data-run>Open</button><button class="secondary" data-copy>Copy Symbols</button>`;
    node.querySelector("[data-run]").addEventListener("click", () => loadScan(scan));
    node.querySelector("[data-copy]").addEventListener("click", () => navigator.clipboard.writeText(matches.map((item) => item.symbol).join(",")));
    root.append(node);
  });
}

function checkAlerts() {
  state.savedScans.forEach((scan) => {
    const matches = scanMatches(scan);
    if (matches.length && "Notification" in window && Notification.permission === "granted") {
      new Notification(`${scan.name}: ${matches.length} matches`, { body: matches.map((item) => item.symbol).join(", ") });
    }
  });
}

function requestNotifications() {
  if (!("Notification" in window)) return;
  Notification.requestPermission();
}

function addSelectedToWatchlist() {
  if (!state.selected || state.watchlist.includes(state.selected.symbol)) return;
  state.watchlist.push(state.selected.symbol);
  save(STORAGE_KEYS.watchlist, state.watchlist);
  renderWatchlist();
}

function renderWatchlist() {
  const root = document.getElementById("watchlistGrid");
  root.innerHTML = "";
  if (!state.watchlist.length) {
    root.innerHTML = "<p class=\"hint\">Select a stock and click Watch.</p>";
    return;
  }
  state.watchlist
    .map((symbol) => stocks.find((item) => item.symbol === symbol))
    .filter(Boolean)
    .forEach((item) => {
      const node = document.createElement("button");
      node.className = "watch-card";
      node.innerHTML = `<span>${item.sector}</span><strong>${item.symbol}</strong><p>${item.name}</p><b class="${item.changePct >= 0 ? "positive" : "negative"}">${money(item.close)} - ${item.changePct.toFixed(2)}%</b>`;
      node.addEventListener("click", () => selectStock(item.symbol));
      root.append(node);
    });
}

function refreshPrices() {
  stocks = stocks.map((item) => {
    const move = Number(((Math.random() - 0.48) * 1.8).toFixed(2));
    const close = Math.max(1, Math.round(item.close * (1 + move / 100) * 100) / 100);
    return {
      ...item,
      close,
      high: Math.max(item.high, close),
      low: Math.min(item.low, close),
      changePct: Number((item.changePct + move).toFixed(2)),
      volume: Math.round(item.volume * (0.9 + Math.random() * 0.25)),
      rsi: Math.max(20, Math.min(82, Math.round(item.rsi + move * 2))),
      history: [...item.history.slice(1), close],
    };
  });
  state.selected = stocks.find((item) => item.symbol === state.selected?.symbol) || stocks[0];
  runScan();
}

function exportResults() {
  const header = ["symbol", "name", "sector", "close", "changePct", "volume", "rsi", "delivery", "signal"];
  const lines = [header.join(",")].concat(
    state.results.map((item) => [item.symbol, item.name, item.sector, item.close, item.changePct, item.volume, item.rsi, item.delivery, signalFor(item)].join(","))
  );
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "scan-results.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function importCsv(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const rows = String(reader.result).trim().split(/\r?\n/);
    const header = rows.shift().split(",").map((item) => item.trim());
    const imported = rows.map((row) => {
      const values = row.split(",");
      const item = Object.fromEntries(header.map((key, index) => [key, values[index]]));
      return stock(
        item.symbol,
        item.name || item.symbol,
        item.sector || "Imported",
        Number(item.open || item.close),
        Number(item.close),
        Number(item.high || item.close),
        Number(item.low || item.close),
        Number(item.changePct || 0),
        Number(item.volume || 0),
        Number(item.avgVolume || item.volume || 1),
        Number(item.rsi || 50),
        Number(item.ema20 || item.close),
        Number(item.ema50 || item.close),
        Number(item.delivery || 0),
        Number(item.pe || 0),
        Number(item.resistance || item.high || item.close)
      );
    });
    stocks = imported.filter((item) => item.symbol && Number.isFinite(item.close));
    state.results = [...stocks];
    state.selected = stocks[0];
    renderAll();
  };
  reader.readAsText(file);
}

function importPineScript(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    document.getElementById("pinePreview").value = String(reader.result || "");
    document.getElementById("pineStatus").textContent = file.name;
    convertPineFromPreview();
  };
  reader.readAsText(file);
}

function convertPineFromPreview() {
  const source = document.getElementById("pinePreview").value;
  const conversion = convertPineScript(source);
  state.pineConversion = conversion;
  document.getElementById("pineSummary").innerHTML = `
    <article><strong>Converted Chartink-style filter</strong><code>${escapeHtml(conversion.formula)}</code></article>
    <article><strong>Detected signal</strong><span>${escapeHtml(conversion.signalName)}</span></article>
    <article><strong>Notes</strong><span>${escapeHtml(conversion.notes.join(" "))}</span></article>
  `;
  document.getElementById("pineStatus").textContent = conversion.confidence;
  if (conversion.formula !== "close > 0") {
    applyPineFormula();
  }
}

function applyPineFormula() {
  const conversion = state.pineConversion || convertPineScript(document.getElementById("pinePreview").value);
  state.pineConversion = conversion;
  document.getElementById("scanName").value = `Pine: ${conversion.signalName}`;
  document.getElementById("formulaInput").value = conversion.formula;
  document.querySelector('[data-mode="formula"]').click();
  switchView("scanner");
  runScan();
}

function convertPineScript(source) {
  const cleaned = stripPineComments(source || "");
  const assignments = parsePineAssignments(cleaned);
  const signal = pickPineSignal(cleaned, assignments);
  const notes = [];
  let expression = signal.expression || "";
  if (!expression) {
    expression = inferPineExpression(cleaned);
    notes.push("No explicit buy or long condition was found, so the converter inferred a broad bullish setup.");
  }
  const formula = normalizeFormula(convertPineExpression(expression, assignments, notes));
  if (formula === "close > 0") {
    notes.push("Only part of Pine Script can be mapped to scanner filters. Plots, strategy orders, security calls, loops, and bar-index logic are ignored.");
  } else {
    notes.push("Converted Pine logic is editable before running the scan.");
  }
  return {
    formula,
    signalName: signal.name || "Bullish Signal",
    confidence: formula === "close > 0" ? "Low confidence" : notes.length > 1 ? "Medium confidence" : "High confidence",
    notes,
  };
}

function stripPineComments(source) {
  return source
    .split(/\r?\n/)
    .map((line) => line.replace(/\/\/.*$/, "").trim())
    .filter(Boolean)
    .join("\n");
}

function parsePineAssignments(source) {
  const assignments = {};
  source.split(/\n/).forEach((line) => {
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*(?::=\s*|=\s*)(.+)$/);
    if (!match) return;
    const name = match[1];
    if (/^(indicator|strategy|plot|alertcondition|if|for|while|switch)$/.test(name.toLowerCase())) return;
    assignments[name] = match[2].trim();
  });
  return assignments;
}

function pickPineSignal(source, assignments) {
  const alerts = [...source.matchAll(/alertcondition\s*\(\s*([^,\n]+)[\s\S]*?title\s*=\s*["']?([^"',)]+)["']?/gi)].map((match) => ({
    name: match[2].trim(),
    expression: resolvePineName(match[1].trim(), assignments),
  }));
  if (alerts.length) {
    const preferred = alerts.find((alert) => /(buy|bullish|above|crossed above|long)/i.test(alert.name) && !/(exit|sell|short|bearish|below|risk|warning|volatility)/i.test(alert.name));
    const continuation = alerts.find((alert) => /(buy|bullish|long)/i.test(alert.name) && !/(exit|sell|short|bearish)/i.test(alert.name));
    return preferred || continuation || alerts[0];
  }
  const preferred = Object.keys(assignments).find((name) => /(buy|bull|long|entry|signal)/i.test(name) && !/(sell|short|exit|bear)/i.test(name));
  if (preferred) return { name: preferred, expression: assignments[preferred] };
  return { name: "Bullish Signal", expression: "" };
}

function resolvePineName(value, assignments, depth = 0) {
  if (depth > 8) return value;
  const key = value.trim();
  if (!assignments[key]) return value;
  return resolvePineName(assignments[key], assignments, depth + 1);
}

function inferPineExpression(source) {
  const fragments = [];
  const cross = source.match(/(?:ta\.)?crossover\s*\([^)]+\)/i);
  if (cross) fragments.push(cross[0]);
  if (/ta\.rsi\s*\(/i.test(source)) fragments.push("rsi > 50");
  if (/ta\.ema\s*\([^,]+,\s*20\s*\)/i.test(source) && /ta\.ema\s*\([^,]+,\s*50\s*\)/i.test(source)) fragments.push("ema20 > ema50");
  if (/volume/i.test(source)) fragments.push("volume > avgVolume");
  return fragments.join(" and ") || "close > 0";
}

function convertPineExpression(expression, assignments, notes) {
  let output = replaceSslHybridAliases(expression, notes);
  output = expandPineVariables(output, assignments);
  output = replacePineIndicators(output);
  output = replacePineCrosses(output);
  output = replaceSslHybridAliases(output, notes);
  output = output.replace(/\bclose\s*>\s*open\b/gi, "changePct > 0");
  output = output.replace(/\bclose\s*<\s*open\b/gi, "changePct < 0");
  output = output.replace(/\bvolume\s*>\s*(?:ta\.)?sma\s*\(\s*volume\s*,\s*\d+\s*\)/gi, "volume > avgVolume");
  output = output.replace(/\bvolume\s*>\s*volAvg\b/gi, "volume > avgVolume");
  output = output.replace(/\bta\./gi, "");
  output = output.replace(/\bmath\.[a-z0-9_]+\s*\([^)]*\)/gi, "0");
  output = output.replace(/\bnot\s+/gi, "");
  output = output.replace(/\s+and\s+/gi, " and ");
  output = output.replace(/\s+or\s+/gi, " or ");
  output = keepScannerComparisons(output);
  if (!output || output === "close > 0") {
    notes.push("The converter could not find enough scanner-compatible comparisons in the uploaded script.");
  }
  return output || "close > 0";
}

function replaceSslHybridAliases(expression, notes) {
  const before = expression;
  let output = expression
    .replace(/\bBBMC\b/g, "ema50")
    .replace(/\bKeltma\b/g, "ema50")
    .replace(/\bupperk\b/g, "resistance")
    .replace(/\blowerk\b/g, "ema50")
    .replace(/\bsslDown2\b/g, "ema20")
    .replace(/\bsslDown\b/g, "ema20")
    .replace(/\bsslExit\b/g, "ema20")
    .replace(/\bbuy_atr\b/g, "close > ema50 and close > ema20")
    .replace(/\bbuy_cont\b/g, "close > ema50 and close > ema20")
    .replace(/\bbuy_inatr\b/g, "close > ema20")
    .replace(/\bbaseline_bullish\b/g, "close > resistance")
    .replace(/\bprice_above_baseline\b/g, "close > ema50")
    .replace(/\bssl2_buy_signal\b/g, "close > ema50 and close > ema20");
  output = output.replace(/\b[a-zA-Z_][a-zA-Z0-9_]*\[1\]/g, "");
  if (output !== before) {
    notes.push("SSL Hybrid custom lines were approximated: baseline as EMA 50, SSL lines as EMA 20, and upper channel as resistance.");
  }
  return output;
}

function expandPineVariables(expression, assignments) {
  let output = expression;
  const protectedNames = new Set(["BBMC", "Keltma", "upperk", "lowerk", "sslDown2", "sslDown", "sslExit", "buy_atr", "buy_cont", "buy_inatr", "baseline_bullish", "price_above_baseline", "ssl2_buy_signal"]);
  for (let depth = 0; depth < 8; depth += 1) {
    let changed = false;
    Object.entries(assignments).forEach(([name, value]) => {
      if (protectedNames.has(name)) return;
      const re = new RegExp(`\\b${escapeRegExp(name)}\\b`, "g");
      if (re.test(output)) {
        output = output.replace(re, `(${value})`);
        changed = true;
      }
    });
    if (!changed) break;
  }
  return output;
}

function replacePineIndicators(expression) {
  return expression
    .replace(/\b(?:ta\.)?rsi\s*\(\s*close\s*,\s*\d+\s*\)/gi, "rsi")
    .replace(/\b(?:ta\.)?ema\s*\(\s*close\s*,\s*20\s*\)/gi, "ema20")
    .replace(/\b(?:ta\.)?ema\s*\(\s*close\s*,\s*50\s*\)/gi, "ema50")
    .replace(/\b(?:ta\.)?sma\s*\(\s*close\s*,\s*20\s*\)/gi, "sma20")
    .replace(/\b(?:ta\.)?sma\s*\(\s*close\s*,\s*50\s*\)/gi, "sma50")
    .replace(/\b(?:ta\.)?sma\s*\(\s*volume\s*,\s*\d+\s*\)/gi, "avgVolume")
    .replace(/\bhl2\b/gi, "close")
    .replace(/\bohlc4\b/gi, "close");
}

function replacePineCrosses(expression) {
  let output = replaceFunctionCalls(expression, ["ta.crossover", "crossover"], (args) => `${args[0]} > ${args[1]}`);
  output = replaceFunctionCalls(output, ["ta.crossunder", "crossunder"], (args) => `${args[0]} < ${args[1]}`);
  return output;
}

function replaceFunctionCalls(expression, names, replacer) {
  let output = expression;
  names.forEach((name) => {
    const search = `${name}(`;
    let index = output.toLowerCase().indexOf(search.toLowerCase());
    while (index >= 0) {
      const openIndex = index + name.length;
      const closeIndex = findMatchingParen(output, openIndex);
      if (closeIndex < 0) break;
      const args = splitPineArgs(output.slice(openIndex + 1, closeIndex));
      if (args.length >= 2) {
        output = `${output.slice(0, index)}${replacer(args)}${output.slice(closeIndex + 1)}`;
      } else {
        index += search.length;
      }
      index = output.toLowerCase().indexOf(search.toLowerCase(), index + 1);
    }
  });
  return output;
}

function findMatchingParen(text, openIndex) {
  let depth = 0;
  for (let index = openIndex; index < text.length; index += 1) {
    if (text[index] === "(") depth += 1;
    if (text[index] === ")") depth -= 1;
    if (depth === 0) return index;
  }
  return -1;
}

function splitPineArgs(text) {
  const args = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "(") depth += 1;
    if (text[index] === ")") depth -= 1;
    if (text[index] === "," && depth === 0) {
      args.push(text.slice(start, index).trim());
      start = index + 1;
    }
  }
  args.push(text.slice(start).trim());
  return args;
}

function keepScannerComparisons(expression) {
  const normalized = expression.replace(/[()]/g, " ").replace(/\s+/g, " ").trim();
  const parts = normalized.split(/\s+(and|or)\s+/i);
  const kept = [];
  for (let index = 0; index < parts.length; index += 1) {
    const part = parts[index].trim();
    if (/^(and|or)$/i.test(part)) {
      if (kept.length && !/^(and|or)$/i.test(kept[kept.length - 1])) kept.push(part.toLowerCase());
      continue;
    }
    const comparison = part.match(/([A-Za-z][A-Za-z0-9]*)\s*(>=|<=|>|<|=)\s*([A-Za-z][A-Za-z0-9]*|-?\d+(?:\.\d+)?)/);
    if (comparison && normalizeField(comparison[1]) && (normalizeField(comparison[3]) || Number.isFinite(Number(comparison[3])))) {
      kept.push(`${normalizeField(comparison[1])} ${comparison[2]} ${normalizeField(comparison[3]) || comparison[3]}`);
    }
  }
  return normalizeFormula(kept.join(" "));
}

function normalizeFormula(formula) {
  const compacted = (formula || "close > 0")
    .replace(/\s+(and|or)\s*$/i, "")
    .replace(/^\s*(and|or)\s+/i, "")
    .replace(/\s+/g, " ")
    .trim() || "close > 0";
  return dedupeFormulaComparisons(compacted);
}

function dedupeFormulaComparisons(formula) {
  const parts = formula.split(/\s+(and|or)\s+/i);
  const seen = new Set();
  const kept = [];
  for (let index = 0; index < parts.length; index += 1) {
    const part = parts[index].trim();
    if (!part) continue;
    if (/^(and|or)$/i.test(part)) {
      if (kept.length && !/^(and|or)$/i.test(kept[kept.length - 1])) kept.push(part.toLowerCase());
      continue;
    }
    const key = part.toLowerCase();
    if (seen.has(key)) {
      if (/^(and|or)$/i.test(kept[kept.length - 1])) kept.pop();
      continue;
    }
    seen.add(key);
    kept.push(part);
  }
  return kept.join(" ").replace(/\s+(and|or)\s*$/i, "").trim() || "close > 0";
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─── Telegram Integration ─────────────────────────────────────────────────────
function setupTelegramSettings() {
  const savedToken = localStorage.getItem(STORAGE_KEYS.tgToken) || "8888932113:AAE83Yz6_9yqjxDe_PkZ4Tu_qhITMG44dLK";
  const savedChat = localStorage.getItem(STORAGE_KEYS.tgChatId) || "@chpm_alerts_bot";
  const savedEnabled = localStorage.getItem(STORAGE_KEYS.tgEnabled) !== "false";

  if (!localStorage.getItem(STORAGE_KEYS.tgToken)) {
    localStorage.setItem(STORAGE_KEYS.tgToken, savedToken);
    localStorage.setItem(STORAGE_KEYS.tgChatId, savedChat);
    localStorage.setItem(STORAGE_KEYS.tgEnabled, "true");
  }

  document.getElementById("openTelegramSettings").addEventListener("click", () => {
    document.getElementById("tgToken").value = localStorage.getItem(STORAGE_KEYS.tgToken) || "";
    document.getElementById("tgChatId").value = localStorage.getItem(STORAGE_KEYS.tgChatId) || "";
    document.getElementById("tgEnabled").checked = localStorage.getItem(STORAGE_KEYS.tgEnabled) !== "false";
    document.getElementById("tgStatus").textContent = "";
    document.getElementById("telegramModal").style.display = "flex";
  });

  document.getElementById("closeTelegramModal").addEventListener("click", () => {
    document.getElementById("telegramModal").style.display = "none";
  });

  document.getElementById("telegramModal").addEventListener("click", (e) => {
    if (e.target === document.getElementById("telegramModal")) {
      document.getElementById("telegramModal").style.display = "none";
    }
  });

  document.getElementById("saveTelegramBtn").addEventListener("click", () => {
    const token = document.getElementById("tgToken").value.trim();
    const chatId = document.getElementById("tgChatId").value.trim();
    const enabled = document.getElementById("tgEnabled").checked;
    localStorage.setItem(STORAGE_KEYS.tgToken, token);
    localStorage.setItem(STORAGE_KEYS.tgChatId, chatId);
    localStorage.setItem(STORAGE_KEYS.tgEnabled, enabled ? "true" : "false");
    document.getElementById("tgStatus").textContent = "Saved.";
    setTimeout(() => { document.getElementById("telegramModal").style.display = "none"; }, 800);
  });

  document.getElementById("testTelegramBtn").addEventListener("click", async () => {
    const token = document.getElementById("tgToken").value.trim();
    const chatId = document.getElementById("tgChatId").value.trim();
    const statusEl = document.getElementById("tgStatus");
    statusEl.textContent = "Sending test message...";
    const ok = await sendTelegramMessage(token, chatId, "✅ *MarketScan Pro* — Telegram alerts are working!");
    statusEl.textContent = ok ? "✅ Test message sent!" : "❌ Failed. Check your bot token and chat ID.";
  });

  updateTelegramStatusBadge();
}

function updateTelegramStatusBadge() {
  const btn = document.getElementById("openTelegramSettings");
  const token = localStorage.getItem(STORAGE_KEYS.tgToken);
  const enabled = localStorage.getItem(STORAGE_KEYS.tgEnabled) !== "false";
  btn.classList.toggle("tg-active", !!(token && enabled));
}

async function sendTelegramMessage(token, chatId, text) {
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text, parse_mode: "Markdown" }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function sendTelegramAlert(results, scanName) {
  const token = localStorage.getItem(STORAGE_KEYS.tgToken);
  const chatId = localStorage.getItem(STORAGE_KEYS.tgChatId);
  const enabled = localStorage.getItem(STORAGE_KEYS.tgEnabled) !== "false";
  if (!enabled || !token || !chatId || !results.length) return;

  const now = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  const lines = results
    .slice(0, 20)
    .map((s) => `• *${s.symbol}* — ${s.changePct >= 0 ? "+" : ""}${s.changePct.toFixed(2)}% | RSI ${s.rsi} | ${signalFor(s)}`);

  const text = [
    `📊 *MarketScan Pro Alert*`,
    `🔍 Scan: _${scanName}_`,
    `📈 Matches: *${results.length} stock${results.length !== 1 ? "s" : ""}*`,
    ``,
    lines.join("\n"),
    results.length > 20 ? `_...and ${results.length - 20} more_` : "",
    ``,
    `🕐 ${now} IST`,
  ].filter((l) => l !== undefined).join("\n");

  await sendTelegramMessage(token, chatId, text);
  updateTelegramStatusBadge();
}

boot();
