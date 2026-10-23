const byId = id => document.getElementById(id);
const settings = byId("settings"), pairing = byId("pairing");
let config;
try { config = JSON.parse(window.Android ? Android.loadSettings() : localStorage.getItem("bili-remote") || "{}"); } catch { config = {}; }
if (!config || typeof config !== "object") config = {};
config.device_id ||= window.Android ? Android.deviceId() : [...crypto.getRandomValues(new Uint8Array(16))].map(x => x.toString(16).padStart(2, "0")).join("");
config.device_name ||= window.Android ? Android.deviceName() : "手机浏览器";
config.ui_style ||= "touchpad";
if (!config.schema) { if (config.target === "browser") config.target = "auto"; config.schema = 2; }
config.target ||= "auto";
config.browser_choice = ["auto", "edge", "chrome"].includes(config.browser_choice) ? config.browser_choice : "auto";
config.gears = normalizeGears(config.gears);
config.rate = config.gears.includes(Number(config.rate)) ? Number(config.rate) : config.gears.includes(2) ? 2 : config.gears[0];
config.haptics = config.haptics !== false;
config.show_hints = config.show_hints !== false;
config.mouse_tap_button = config.mouse_tap_button === "right" ? "right" : "left";
delete config.token;
let hudTimer, scanFallback, pairingTarget = null, computerListSignature = "";
let speedPointer = null;
function persist() {
  const text = JSON.stringify(config);
  if (window.Android) Android.saveSettings(text); else localStorage.setItem("bili-remote", text);
}
function hint(text) {
  byId("remoteMessage").textContent = text;
  if (!config.show_hints) return;
  byId("hud").textContent = text;
  byId("hud").classList.add("visible");
  clearTimeout(hudTimer);
  hudTimer = setTimeout(() => byId("hud").classList.remove("visible"), 1600);
}
function error(error) {
  const text = error.message || String(error);
  byId("controlStatus").textContent = `最近操作失败：${text}`;
  hint(text);
}
function previewSeek({ position, start, end }) {
  if (!config.show_hints) return;
  const time = seconds => { const tenths = Math.round(seconds * 10); return `${Math.floor(tenths / 600)}:${(tenths % 600 / 10).toFixed(1).padStart(4, "0")}`; };
  hint(`${time(position)} / ${time(end)}`);
  const bar = document.createElement("progress"); bar.max = end - start; bar.value = position - start;
  bar.setAttribute("aria-label", "预计播放进度"); byId("hud").append(bar);
}
const connection = new RemoteConnection({ config, persist, state: connectionState, discovery: renderComputers });
const send = (cmd, fields = {}) => connection.send(cmd, fields).then(result => {
  if (result.control_target?.name) {
    byId("activeTarget").textContent = `最近确认目标：${result.control_target.name}`;
    byId("controlStatus").textContent = "";
  }
  if (typeof result.volume === "number") byId("volumeText").textContent = `音量 ${Math.round(result.volume * 100)}%`;
  if (typeof result.paused === "boolean") byId("playSymbol").innerHTML = result.paused ? '<path d="M12 7 32 20 12 33Z"/>' : '<path d="M11 8h6v24h-6zM23 8h6v24h-6z"/>';
  return result;
});
function haptic() {
  if (!config.haptics) return;
  try {
    if (window.Android && Android.haptic) Android.haptic();
    else if (navigator.vibrate) navigator.vibrate(22);
  } catch { /* Devices without a vibrator still support all controls. */ }
}
function holdChanged(rate) {
  byId("holdSpeed").classList.toggle("holding", rate !== null);
  byId("holdSpeed").dataset.rate = rate ?? config.rate;
  document.querySelectorAll("#speedTrack [data-rate]").forEach(gear => gear.classList.toggle("active", Number(gear.dataset.rate) === (rate ?? config.rate)));
  byId("holdRate").textContent = `${rate ?? config.rate}×`;
}
const gestures = new GestureEngine({ send, hint, preview: previewSeek, error, rate: () => config.rate, gears: () => config.gears, haptic, changed: holdChanged, tap: (...args) => touchpad.videoTap(...args) });
const touchpad = new TouchpadController({ video: gestures, send, hint, error, haptic,
  tapButton: () => config.mouse_tap_button,
  changed: phase => {
    byId("mouseControls").hidden = phase === "video";
    byId("mouseExit").textContent = phase === "connecting" ? "连接鼠标中 · 取消" : "鼠标模式 · 返回视频";
    byId("pad").setAttribute("aria-label", phase === "video" ? "视频触摸板：轻点播放，双击进入鼠标，滑动调节，长按倍速" : "鼠标触摸板：滑动移动光标，长按右键");
  }
});
const hold = new HoldControl({ send, hint, error, rate: () => config.rate, gears: () => config.gears, haptic, changed: holdChanged });
function cancelControls() { touchpad.cancel(); hold.stop(false); speedPointer = null; }
function connectionState(state) {
  byId("connectionStatus").textContent = state.text;
  byId("deviceName").textContent = state.phase === "connected" ? state.name : state.text;
  byId("devicePhase").textContent = ({connected: "已连接 · 选择电脑", pair: "等待配对", connecting: "连接中", disconnected: "等待电脑上线", error: "连接异常"})[state.phase] || "正在寻找电脑";
  document.body.classList.toggle("connected", state.phase === "connected");
  if (state.phase === "connected") {
    byId("host").value = state.host;
    if (settings.open) settings.close();
    if (pairing.open) pairing.close();
    byId("pairingCode").value = "";
    renderHistory();
    hint("已连接电脑");
  } else if (state.phase === "pair") {
    cancelControls();
    pairingTarget = { host: state.host, computer_id: state.computer_id };
    byId("pairingComputer").textContent = state.host;
    byId("pairingMessage").textContent = state.code === "pair_invalid" ? state.text : "在电脑软件中查看配对码，连接一次后自动记住。";
    if (settings.open) settings.close();
    if (!pairing.open) { byId("pairingCode").value = ""; pairing.showModal(); }
  } else if (state.phase === "disconnected" || state.phase === "error") {
    byId("activeTarget").textContent = "电脑未连接；播放目标尚未确认。";
    cancelControls();
    hint(state.phase === "error" ? state.text : "等待电脑上线 · 双指触摸可查看连接");
  }
}
function renderHistory() {
  byId("history").replaceChildren();
  if (!config.history?.length) {
    const empty = document.createElement("p"); empty.className = "history-empty";
    empty.textContent = "还没有连接记录，手动连接后自动保存。";
    byId("history").append(empty);
  }
  for (const entry of config.history || []) {
    const row = document.createElement("div"); row.className = "history-entry";
    const connect = document.createElement("button"); connect.type = "button"; connect.className = "history-connect";
    connect.textContent = `${entry.name === entry.host ? "" : entry.name + " · "}${entry.host}`;
    connect.onclick = () => { cancelControls(); byId("host").value = entry.host; connection.connect(entry.host, entry.computer_id || "", { manual: true }); };
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "history-remove"; remove.textContent = "×"; remove.setAttribute("aria-label", "删除这条地址记录");
    remove.onclick = () => { config.history = config.history.filter(item => item.host !== entry.host); persist(); renderHistory(); };
    row.append(connect, remove); byId("history").append(row);
  }
}
function renderComputers(computers) {
  const signature = JSON.stringify(computers);
  if (signature === computerListSignature) return;
  computerListSignature = signature;
  byId("computer").replaceChildren(new Option(computers.length ? "选择电脑" : "等待电脑上线…", ""));
  for (const item of computers) byId("computer").add(new Option(`${item.name || "电脑"} · ${item.host.split(":")[0]}`, item.computer_id));
  if (connection.connected) byId("computer").value = config.computer_id;
}
function scan() {
  if (window.Android) {
    if (Android.startDiscovery) Android.startDiscovery(); else Android.discoverComputers();
  } else if (!connection.connected && config.host) connection.reconnect();
}
window.onComputersDiscovered = (computers, failure) => {
  connection.discovered(computers);
  if (failure && !connection.connected) byId("connectionStatus").textContent = failure;
};
function setStyle(style) {
  cancelControls();
  config.ui_style = style === "remote" ? "remote" : "touchpad";
  byId("remote").hidden = config.ui_style !== "remote";
  byId("pad").hidden = config.ui_style !== "touchpad";
  byId("style").value = config.ui_style;
  document.querySelectorAll("[data-style]").forEach(button => {
    const selected = button.dataset.style === config.ui_style;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  persist();
}
window.openSettings = () => { cancelControls(); if (pairing.open) pairing.close(); renderHistory(); if (!settings.open) settings.showModal(); };
window.setAppActive = active => {
  if (!active) {
    cancelControls(); clearTimeout(scanFallback);
    if (window.Android && Android.stopDiscovery) Android.stopDiscovery();
    Promise.resolve().then(() => connection.suspend());
  } else { connection.resume(); scan(); }
};
byId("style").onchange = () => setStyle(byId("style").value);
document.querySelectorAll("[data-style]").forEach(button => button.onclick = () => { setStyle(button.dataset.style); if (config.ui_style === "touchpad") hint("触摸板模式 · 双指触摸打开设置"); });
byId("target").value = config.target;
byId("target").onchange = () => { cancelControls(); config.target = byId("target").value; byId("nativeSettings").hidden = config.target !== "native"; persist(); };
byId("nativeSettings").hidden = config.target !== "native";
byId("browserChoice").value = config.browser_choice;
byId("browserChoice").onchange = () => { config.browser_choice = byId("browserChoice").value; persist(); };
byId("rate").onchange = () => { cancelControls(); config.rate = Number(byId("rate").value); holdChanged(null); persist(); };
function renderGears() {
  byId("gearCount").value = config.gears.length;
  byId("rate").replaceChildren(...config.gears.map(value => new Option(`${value} 倍`, value)));
  byId("rate").value = config.rate;
  byId("speedTrack").replaceChildren(); byId("gearEditor").replaceChildren();
  config.gears.forEach((value, index) => {
    const detent = document.createElement("span"); detent.className = "speed-detent";
    detent.dataset.rate = value; detent.textContent = `${value}×`; byId("speedTrack").append(detent);
    const row = document.createElement("label"); row.className = "setting-row";
    const title = document.createElement("span"); title.textContent = `第 ${index + 1} 挡`;
    const select = document.createElement("select"); select.setAttribute("aria-label", `第 ${index + 1} 挡倍速`);
    for (const speed of SPEED_VALUES) {
      const option = new Option(`${speed} 倍`, speed);
      option.disabled = speed !== value && config.gears.includes(speed); select.add(option);
    }
    select.value = value;
    select.onchange = () => { const gears = [...config.gears]; gears[index] = Number(select.value); saveGears(gears); };
    row.append(title, select); byId("gearEditor").append(row);
  });
  holdChanged(null);
}
function saveGears(values) {
  cancelControls(); config.gears = normalizeGears(values);
  if (!config.gears.includes(config.rate)) config.rate = config.gears.includes(2) ? 2 : config.gears[0];
  persist(); renderGears();
}
byId("gearCount").onchange = () => {
  const count = Number(byId("gearCount").value), gears = config.gears.slice(0, count);
  for (const value of SPEED_VALUES) { if (gears.length >= count) break; if (!gears.includes(value)) gears.push(value); }
  saveGears(gears);
};
renderGears();
function renderHints() {
  byId("showHints").checked = config.show_hints;
  document.body.classList.toggle("hints-off", !config.show_hints);
  if (!config.show_hints) { clearTimeout(hudTimer); byId("hud").classList.remove("visible"); }
}
byId("showHints").onchange = () => { config.show_hints = byId("showHints").checked; renderHints(); persist(); };
renderHints();
function renderHaptics() {
  byId("haptics").checked = config.haptics;
  byId("hapticToggle").setAttribute("aria-pressed", String(config.haptics));
  byId("hapticToggle").title = `震动反馈：${config.haptics ? "开启" : "关闭"}`;
}
function setHaptics(enabled) { config.haptics = enabled; renderHaptics(); persist(); }
byId("haptics").onchange = () => setHaptics(byId("haptics").checked);
byId("hapticToggle").onclick = () => { setHaptics(!config.haptics); hint(config.haptics ? "震动反馈已开启" : "震动反馈已关闭"); };
renderHaptics();
byId("mouseTapButton").value = config.mouse_tap_button;
byId("mouseTapButton").onchange = () => { cancelControls(); config.mouse_tap_button = byId("mouseTapButton").value; persist(); };
byId("mouseExit").onclick = () => touchpad.exit();
byId("enterMouse").onclick = () => { settings.close(); setStyle("touchpad"); touchpad.enter(); };
byId("host").value = config.host || (location.protocol !== "file:" ? location.host : "");
if (config.session_id) byId("session").add(new Option(config.session_id, config.session_id));
byId("session").value = config.session_id || "";
byId("session").onchange = () => { cancelControls(); config.session_id = byId("session").value; persist(); };
byId("computer").onchange = () => {
  const item = connection.computers.find(item => item.computer_id === byId("computer").value);
  if (item) { cancelControls(); connection.connect(item.host, item.computer_id); }
};
byId("connectManual").onclick = () => {
  try { cancelControls(); const host = normalizeRemoteHost(byId("host").value); connection.connect(host, config.hostIds[host] || "", { manual: true }); renderHistory(); }
  catch (failure) { byId("connectionStatus").textContent = failure.message; }
};
byId("search").onclick = () => { connection.needsPin = false; scan(); connection.reconnect(); byId("connectionStatus").textContent = connection.connected ? "电脑已连接" : "正在扫描电脑信号…"; };
byId("openSettings").onclick = window.openSettings;
byId("deviceStatus").onclick = window.openSettings;
byId("closeSettings").onclick = () => settings.close();
byId("settingsForm").onsubmit = event => { event.preventDefault(); persist(); settings.close(); if (!connection.connected && !connection.connecting) byId("connectManual").click(); };
byId("pairingForm").onsubmit = event => { event.preventDefault(); if (pairingTarget) { byId("pairingMessage").textContent = "正在验证配对码…"; connection.connect(pairingTarget.host, pairingTarget.computer_id, { pin: byId("pairingCode").value.trim() }); } };
byId("cancelPairing").onclick = () => { pairing.close(); window.openSettings(); };
byId("discover").onclick = async () => {
  try {
    const result = await send("discover");
    const selected = config.session_id || "";
    byId("session").replaceChildren(new Option("自动识别哔哩哔哩客户端", ""));
    for (const item of result.sessions || []) {
      const features = [["toggle", "暂停"], ["seek", "进度"], ["speed", "倍速"]].filter(([key]) => item[key]).map(([, label]) => label).join(" / ") || "未开放接口";
      byId("session").add(new Option(`${item.name || item.id}（${features}）`, item.id));
    }
    if (selected && !(result.sessions || []).some(item => item.id === selected)) byId("session").add(new Option(`${selected}（当前未提供会话）`, selected));
    byId("session").value = selected;
    byId("controlStatus").textContent = result.sessions?.length ? "请选择要控制的浏览器或客户端；列表显示实际开放的能力。" : "请先在浏览器或客户端播放视频，再检测。";
  } catch (failure) { byId("connectionStatus").textContent = failure.message; }
};
document.querySelectorAll("[data-command]").forEach(button => button.onclick = async () => {
  try {
    const cmd = button.dataset.command;
    await send(cmd, button.dataset.delta ? { delta: Number(button.dataset.delta) } : {});
    if (cmd === "seek") hint(`${Number(button.dataset.delta) > 0 ? "快进" : "快退"} 10 秒`);
    else if (cmd === "toggle") byId("remoteMessage").textContent = "已发送播放操作";
  } catch (failure) { error(failure); }
});
byId("launchBrowser").onclick = async () => {
  const button = byId("launchBrowser"), message = byId("browserMessage");
  button.disabled = true;
  message.textContent = "正在电脑打开哔哩哔哩…";
  try {
    cancelControls();
    const result = await send("open_browser", {browser: config.browser_choice});
    config.target = "browser";
    byId("target").value = config.target;
    byId("nativeSettings").hidden = true;
    persist();
    message.textContent = `已打开 ${result.control_target?.name || "专用网页窗口"}，并切换到专用网页控制；请在该窗口选择视频。`;
    hint(message.textContent);
  } catch (failure) {
    message.textContent = failure.message || String(failure);
    error(failure);
  } finally { button.disabled = false; }
};
const speedButton = byId("holdSpeed");
speedButton.onpointerdown = event => {
  if (speedPointer !== null || (event.pointerType === "mouse" && event.button !== 0)) return;
  event.preventDefault(); speedPointer = event.pointerId;
  speedButton.setPointerCapture(event.pointerId); hold.start(event.clientX);
};
speedButton.onpointermove = event => { if (event.pointerId === speedPointer) hold.move(event.clientX); };
speedButton.onpointerup = speedButton.onpointercancel = speedButton.onlostpointercapture = event => {
  if (event.pointerId !== speedPointer) return;
  speedPointer = null; hold.stop();
};
speedButton.onkeydown = event => { if ([" ", "Enter"].includes(event.key) && !event.repeat) { event.preventDefault(); hold.start(); } };
speedButton.onkeyup = event => { if ([" ", "Enter"].includes(event.key)) hold.stop(); };
speedButton.onblur = () => { speedPointer = null; hold.stop(); };
const pointers = new Set(); let pointerId = null;
byId("pad").onpointerdown = event => {
  event.preventDefault(); pointers.add(event.pointerId);
  if (pointers.size > 1) { cancelControls(); pointerId = null; window.openSettings(); return; }
  pointerId = event.pointerId; byId("pad").setPointerCapture(event.pointerId); touchpad.down(event.clientX, event.clientY, innerWidth, innerHeight, event.timeStamp);
};
byId("pad").onpointermove = event => {
  if (event.pointerId !== pointerId) return;
  let samples = [];
  if (touchpad.phase === "mouse" && event.getCoalescedEvents) {
    try { samples = event.getCoalescedEvents(); } catch { /* HTTP/older WebView fallback below. */ }
  }
  if (samples.length) for (const sample of samples) touchpad.move(sample.clientX, sample.clientY, sample.timeStamp);
  touchpad.move(event.clientX, event.clientY, event.timeStamp);
};
function finishPointer(event, canceled) {
  pointers.delete(event.pointerId);
  if (event.pointerId === pointerId) { if (canceled) touchpad.cancel(); else touchpad.up(event.clientX, event.clientY, event.timeStamp); pointerId = null; }
}
window.addEventListener("pointerup", event => finishPointer(event, false));
window.addEventListener("pointercancel", event => finishPointer(event, true));
byId("pad").onlostpointercapture = event => finishPointer(event, true);
window.addEventListener("blur", cancelControls);
document.addEventListener("visibilitychange", () => { pointers.clear(); pointerId = null; window.setAppActive(!document.hidden); });
window.addEventListener("pagehide", () => window.setAppActive(false));
setStyle(config.ui_style);
renderHistory();
if (!window.Android && !config.host && location.protocol !== "file:") config.host = location.host;
if (config.host) connection.connect(config.host, config.computer_id); else window.openSettings();
scan();
