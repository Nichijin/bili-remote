package com.biliremote.app;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.os.Build;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetSocketAddress;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.UUID;
import java.util.Iterator;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

public final class MainActivity extends Activity {
    private WebView webView;
    private final AtomicInteger discoveryEpoch = new AtomicInteger(0);
    private volatile DatagramSocket discoverySocket;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        webView = new WebView(this);
        webView.setBackgroundColor(Color.BLACK);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setSupportZoom(false);
        webView.getSettings().setAllowFileAccess(false);
        webView.addJavascriptInterface(new SettingsBridge(), "Android");
        webView.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) { return true; }
        });
        setContentView(webView);
        // Packaged assets remain readable even with general file access disabled.
        webView.loadUrl("file:///android_asset/index.html");
        immersive();
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) immersive();
    }

    @Override protected void onPause() {
        stopDiscovery();
        if (webView != null) webView.evaluateJavascript("window.setAppActive && window.setAppActive(false)", null);
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        if (webView != null) webView.evaluateJavascript("window.setAppActive && window.setAppActive(true)", null);
    }

    @Override public void onBackPressed() {
        webView.evaluateJavascript("window.openSettings && window.openSettings()", null);
    }

    @Override protected void onDestroy() {
        stopDiscovery();
        if (webView != null) { webView.removeJavascriptInterface("Android"); webView.destroy(); }
        super.onDestroy();
    }

    private final class SettingsBridge {
        @JavascriptInterface public String deviceId() {
            String value = getSharedPreferences("remote", MODE_PRIVATE).getString("device_id", "");
            if (value.isEmpty()) {
                value = UUID.randomUUID().toString();
                getSharedPreferences("remote", MODE_PRIVATE).edit().putString("device_id", value).apply();
            }
            return value;
        }
        @JavascriptInterface public String deviceName() { return Build.MANUFACTURER + " " + Build.MODEL; }
        @JavascriptInterface public void haptic() {
            runOnUiThread(new Runnable() { @Override public void run() {
                if (isFinishing() || isDestroyed() || !hasWindowFocus()) return;
                try {
                    JSONObject settings = new JSONObject(getSharedPreferences("remote", MODE_PRIVATE).getString("settings", "{}"));
                    if (!settings.optBoolean("haptics", true)) return;
                    Vibrator vibrator = (Vibrator) getSystemService(VIBRATOR_SERVICE);
                    if (vibrator != null && vibrator.hasVibrator())
                        vibrator.vibrate(VibrationEffect.createOneShot(22, VibrationEffect.DEFAULT_AMPLITUDE));
                } catch (Exception ignored) { /* Vibration is optional on all devices. */ }
            }});
        }
        @JavascriptInterface public void stopDiscovery() { MainActivity.this.stopDiscovery(); }
        @JavascriptInterface public void discoverComputers() { startDiscovery(); }
        @JavascriptInterface public void startDiscovery() {
            final int epoch = discoveryEpoch.incrementAndGet();
            DatagramSocket old = discoverySocket;
            if (old != null) old.close();
            Thread worker = new Thread(new Runnable() { @Override public void run() {
                try (DatagramSocket socket = new DatagramSocket(null)) {
                    socket.setReuseAddress(true);
                    try { socket.bind(new InetSocketAddress(8767)); }
                    catch (Exception occupied) { socket.bind(new InetSocketAddress(0)); }
                    if (epoch != discoveryEpoch.get()) return;
                    discoverySocket = socket;
                    socket.setBroadcast(true);
                    socket.setSoTimeout(400);
                    LinkedHashMap<String, JSONObject> found = new LinkedHashMap<>();
                    LinkedHashMap<String, Long> seen = new LinkedHashMap<>();
                    long nextSend = 0, nextPublish = 0;
                    String nonce = "";
                    while (epoch == discoveryEpoch.get()) {
                        if (System.currentTimeMillis() >= nextSend) {
                            Set<InetAddress> destinations = new LinkedHashSet<>();
                            destinations.add(InetAddress.getByName("255.255.255.255"));
                            for (NetworkInterface network : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                                if (!network.isUp() || network.isLoopback()) continue;
                                for (InterfaceAddress address : network.getInterfaceAddresses()) {
                                    if (address.getBroadcast() != null) destinations.add(address.getBroadcast());
                                }
                            }
                            nonce = UUID.randomUUID().toString();
                            JSONObject request = new JSONObject();
                            request.put("kind", "bili_remote_discover").put("version", 1).put("nonce", nonce);
                            byte[] data = request.toString().getBytes(StandardCharsets.UTF_8);
                            for (InetAddress destination : destinations) {
                                try { socket.send(new DatagramPacket(data, data.length, destination, 8766)); }
                                catch (Exception ignored) { }
                            }
                            nextSend = System.currentTimeMillis() + 3000;
                        }
                        DatagramPacket packet = new DatagramPacket(new byte[4096], 4096);
                        try {
                            socket.receive(packet);
                            JSONObject reply = new JSONObject(new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8));
                            if (!"bili_remote_computer".equals(reply.optString("kind")) || reply.optInt("version") != 1) continue;
                            if (!reply.optBoolean("announce") && !nonce.equals(reply.optString("nonce"))) continue;
                            String id = reply.optString("computer_id");
                            int port = reply.optInt("port");
                            if (id.length() < 8 || id.length() > 128 || port < 1 || port > 65535) continue;
                            JSONObject computer = new JSONObject();
                            computer.put("computer_id", id).put("name", reply.optString("name", "电脑")).put("host", packet.getAddress().getHostAddress() + ":" + port);
                            found.put(id, computer);
                            seen.put(id, System.currentTimeMillis());
                        } catch (SocketTimeoutException ignored) { }
                        catch (java.net.SocketException socketFailure) { throw socketFailure; }
                        catch (Exception ignored) { }
                        if (System.currentTimeMillis() >= nextPublish) {
                            Iterator<Map.Entry<String, Long>> iterator = seen.entrySet().iterator();
                            while (iterator.hasNext()) {
                                Map.Entry<String, Long> entry = iterator.next();
                                if (System.currentTimeMillis() - entry.getValue() > 9000) {
                                    found.remove(entry.getKey()); iterator.remove();
                                }
                            }
                            JSONArray computers = new JSONArray();
                            for (JSONObject reply : found.values()) computers.put(reply);
                            publishComputers(computers, "", epoch);
                            nextPublish = System.currentTimeMillis() + 1000;
                        }
                    }
                } catch (Exception failure) {
                    if (epoch == discoveryEpoch.get()) publishComputers(new JSONArray(), "无法扫描电脑信号，可手动输入 IP 连接", epoch);
                }
            }}, "computer-discovery");
            worker.setDaemon(true);
            worker.start();
        }
        @JavascriptInterface public String loadSettings() {
            return getSharedPreferences("remote", MODE_PRIVATE).getString("settings", "{}");
        }
        @JavascriptInterface public void saveSettings(String value) {
            getSharedPreferences("remote", MODE_PRIVATE).edit().putString("settings", value).apply();
        }
    }

    private void stopDiscovery() {
        discoveryEpoch.incrementAndGet();
        DatagramSocket socket = discoverySocket;
        if (socket != null) socket.close();
        discoverySocket = null;
    }

    private void publishComputers(JSONArray computers, String error, final int epoch) {
        final String script = "window.onComputersDiscovered && window.onComputersDiscovered(" + computers + "," + JSONObject.quote(error) + ")";
        runOnUiThread(new Runnable() { @Override public void run() {
            if (epoch == discoveryEpoch.get() && !isFinishing() && !isDestroyed()) webView.evaluateJavascript(script, null);
        }});
    }
}
