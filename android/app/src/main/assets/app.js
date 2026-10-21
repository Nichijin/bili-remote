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
config.rate ||= 2;
delete config.token;
let hudTimer, scanFallback, pairingTarget = null, computerListSignature = "";
function persist() {
  const text = JSON.stringify(config);
  if (window.Android) Android.saveSettings(text); else localStorage.setItem("bili-remote", text);
}
function hint(text) {
  byId("hud").textContent = text;
  byId("hud").classList.add("visible");
  clearTimeout(hudTimer);
  hudTimer = setTimeout(() => byId("hud").classList.remove("visible"), 1600);
  byId("remoteMessage").textContent = text;
}
function error(error) { hint(error.message || String(error)); }
const connection = new RemoteConnection({ config, persist, state: connectionState, discovery: renderComputers });
const send = (cmd, fields = {}) => connection.send(cmd, fields).then(result => {
  if (typeof result.volume === "number") byId("volumeText").textContent = `音量 ${Math.round(result.volume * 100)}%`;
  if (typeof result.paused === "boolean") byId("playSymbol").innerHTML = result.paused ? '<path d="M12 7 32 20 12 33Z"/>' : '<path d="M11 8h6v24h-6zM23 8h6v24h-6z"/>';
  return result;
});
const gestures = new GestureEngine({ send, hint, error, rate: () => Number(config.rate) });
const hold = new HoldControl({ send, hint, error, rate: () => Number(config.rate) });
function cancelControls() { gestures.cancel(); hold.stop(); byId("holdSpeed").classList.remove("holding"); }
function connectionState(state) {
  byId("connectionStatus").textContent = state.text;
  byId("deviceName").textContent = state.phase === "connected" ? state.name : state.text;
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
    cancelControls();
    hint(state.phase === "error" ? state.text : "等待电脑上线 · 双指触摸可查看连接");
  }
}
function renderHistory() {
  byId("history").replaceChildren();
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
byId("rate").value = config.rate;
byId("rate").onchange = () => { cancelControls(); config.rate = Number(byId("rate").value); byId("holdRate").textContent = `${config.rate}×`; persist(); };
byId("holdRate").textContent = `${config.rate}×`;
byId("host").value = config.host || (location.protocol !== "file:" ? location.host : "");
if (config.session_id) byId("session").add(new Option(config.session_id, config.session_id));
byId("session").value = config.session_id || "";
byId("session").onchange = () => { config.session_id = byId("session").value; persist(); };
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
byId("closeSettings").onclick = () => settings.close();
byId("settingsForm").onsubmit = event => { event.preventDefault(); persist(); settings.close(); if (!connection.connected && !connection.connecting) byId("connectManual").click(); };
byId("pairingForm").onsubmit = event => { event.preventDefault(); if (pairingTarget) { byId("pairingMessage").textContent = "正在验证配对码…"; connection.connect(pairingTarget.host, pairingTarget.computer_id, { pin: byId("pairingCode").value.trim() }); } };
byId("cancelPairing").onclick = () => { pairing.close(); window.openSettings(); };
byId("discover").onclick = async () => {
  try {
    const result = await send("discover");
    byId("session").replaceChildren(new Option("自动识别哔哩哔哩", ""));
    for (const item of result.sessions || []) {
      const features = [["toggle", "暂停"], ["seek", "进度"], ["speed", "倍速"]].filter(([key]) => item[key]).map(([, label]) => label).join(" / ") || "未开放接口";
      byId("session").add(new Option(`${item.id}（${features}）`, item.id));
    }
    byId("connectionStatus").textContent = result.sessions?.length ? "请选择要控制的客户端" : "请先在客户端播放视频";
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
byId("launchBrowser").onclick = () => send("open_browser").then(() => hint("已在电脑打开哔哩哔哩，请选择视频")).catch(error);
const speedButton = byId("holdSpeed");
speedButton.onpointerdown = event => { event.preventDefault(); speedButton.setPointerCapture(event.pointerId); speedButton.classList.add("holding"); hold.start(); };
speedButton.onpointerup = speedButton.onpointercancel = speedButton.onlostpointercapture = () => { hold.stop(); speedButton.classList.remove("holding"); };
speedButton.onkeydown = event => { if ([" ", "Enter"].includes(event.key) && !event.repeat) { event.preventDefault(); hold.start(); } };
speedButton.onkeyup = event => { if ([" ", "Enter"].includes(event.key)) hold.stop(); };
speedButton.onblur = () => hold.stop();
const pointers = new Set(); let pointerId = null;
byId("pad").onpointerdown = event => {
  event.preventDefault(); pointers.add(event.pointerId);
  if (pointers.size > 1) { cancelControls(); pointerId = null; window.openSettings(); return; }
  pointerId = event.pointerId; byId("pad").setPointerCapture(event.pointerId); gestures.down(event.clientX, event.clientY, innerWidth, innerHeight);
};
byId("pad").onpointermove = event => { if (event.pointerId === pointerId) gestures.move(event.clientX, event.clientY); };
function finishPointer(event, canceled) {
  pointers.delete(event.pointerId);
  if (event.pointerId === pointerId) { if (canceled) gestures.cancel(); else gestures.up(event.clientX, event.clientY); pointerId = null; }
}
window.addEventListener("pointerup", event => finishPointer(event, false));
window.addEventListener("pointercancel", event => finishPointer(event, true));
window.addEventListener("blur", cancelControls);
document.addEventListener("visibilitychange", () => { pointers.clear(); pointerId = null; window.setAppActive(!document.hidden); });
window.addEventListener("pagehide", () => window.setAppActive(false));
setStyle(config.ui_style);
renderHistory();
if (!window.Android && !config.host && location.protocol !== "file:") config.host = location.host;
if (config.host) connection.connect(config.host, config.computer_id); else window.openSettings();
scan();
