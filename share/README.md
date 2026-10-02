# Sharing one in-flight Wi-Fi connection

The cabin Wi-Fi on this flight was sold per device, paid for on a MacBook. The goal was to get another iPhone online too, preferably without wires.

## What doesn't work

- **The Mac as a hotspot.** macOS Internet Sharing won't re-share Wi-Fi over the same Wi-Fi radio.
- **An iPhone as the router.** It can take internet from the Mac over USB, but Personal Hotspot only ever shares cellular.
- **The other phone using the Mac as a proxy over the cabin Wi-Fi.** The cabin network isolates clients from each other, so the phone can't reach the Mac. `mac_http_proxy.py` is that attempt. It's still useful on networks without client isolation.

## What works: an Android phone as the router

```
cabin Wi-Fi -> Mac -> USB -> Android phone -> proxy -> phone's hotspot -> other phone
```

1. The Mac gives the Android phone internet over USB with [gnirehtet](https://github.com/Genymobile/gnirehtet), a reverse-tethering tool that runs as a VPN on the phone.
2. Android won't route hotspot clients through a VPN. So a small proxy runs on the phone itself (`pixelproxy`, built from this folder). Its own traffic does go through the VPN.
3. The other phone joins the Android hotspot and sends its traffic to that proxy.

Tested with a Pixel 10 on Android 17.

### Set up (on the ground, with internet)

```sh
brew install gnirehtet go                 # adb comes with: brew install --cask android-platform-tools
cd share/pixelproxy
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -ldflags='-s -w' -o pixelproxy .
```

On the phone: Settings > About phone > tap **Build number** seven times. Then Developer options > **USB debugging** on.

### In the air

```sh
adb devices                               # accept the prompt on the phone
adb push share/pixelproxy/pixelproxy /data/local/tmp/
gnirehtet run                             # keep this running; the phone shows a key icon
./share/hotspot.sh proxy                  # start the proxy on the phone (HTTP 3128, SOCKS5 1080)
./share/hotspot.sh on                     # hotspot on, via the Quick Settings tile
./share/hotspot.sh status                 # shows the address to use on the other phone
```

On the other phone, join the Android hotspot, then pick one:

- **Best: a proxy app running as a VPN** (Shadowrocket, Surge, Stash). This captures every app, including ones that open their own sockets, like WeChat, and SOCKS5 carries UDP for voice calls. For Shadowrocket, add a SOCKS5 server at the hotspot address, port `1080`, and set routing to Global. For Surge, use a profile like this:

  ```ini
  [General]
  skip-proxy = 10.0.0.0/8, 192.168.0.0/16, 127.0.0.1, localhost

  [Proxy]
  Phone = socks5, 10.216.90.164, 1080, udp-relay=true

  [Rule]
  FINAL,Phone,dns-failed
  ```

  Use the address `hotspot.sh status` prints. Keep IP-based rules out of the profile: they make Surge try local DNS, which doesn't work on the hotspot.
- **Quick and limited: the HTTP proxy.** Settings > Wi-Fi > (i) > Configure Proxy > Manual, then the hotspot address and port `3128`. Browsers and most apps follow it. Apps with their own connections don't.

`socktest/` is a tiny program that checks the SOCKS5 UDP relay from the phone itself.

### If the hotspot keeps turning itself off

Some carriers make Android run a tethering entitlement check before allowing the hotspot. With no cell signal at 38,000 ft the check fails: a dialog appears, and the hotspot gets shut down, either when you dismiss it or when the check reruns on its own. On a Pixel the check is one package, which you can disable for the flight:

```sh
adb shell pm disable-user --user 0 com.google.android.tetheringentitlement
./share/hotspot.sh on                     # the Quick Settings tile path skips the check's dialog
```

Turn it back on after landing, before you rely on mobile data again:

```sh
./share/hotspot.sh restore
```

### Undo everything

```sh
gnirehtet stop
adb shell pkill pixelproxy
./share/hotspot.sh off
./share/hotspot.sh restore
```

Then set the other phone's Wi-Fi proxy back to Off, and turn its proxy app off. gnirehtet replaces any VPN the Android phone had running, so switch that back on too.

### Gotchas

- **If the Mac sleeps or reboots, the relay stops.** Run `gnirehtet run` again. The proxy on the phone keeps running until the phone reboots.
- **Check your Wi-Fi plan's terms.** Some airlines sell per device and say so.
