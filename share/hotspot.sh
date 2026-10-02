#!/bin/zsh
# Control the Pixel's Wi-Fi hotspot over adb.
#   ./hotspot.sh status | on | off | toggle | proxy | restore
# Toggles go through the Quick Settings tile, which starts tethering without the
# carrier entitlement UI. The entitlement app itself is disabled for the flight
# (see `restore` to undo).

set -e
ENT=com.google.android.tetheringentitlement

is_on() { adb shell dumpsys tethering | grep -q 'wlan[0-9] - TetheredState'; }

status() {
  if is_on; then
    ip=$(adb shell dumpsys tethering | grep -oE 'iface=wlan[0-9] state=TETHERED lp=\{InterfaceName: wlan[0-9] LinkAddresses: \[ [0-9.]+' | tail -1 | grep -oE '[0-9.]+$')
    echo "hotspot: ON  (clients: SOCKS5 ${ip:-?}:1080 with UDP, or HTTP ${ip:-?}:3128)"
  else
    echo "hotspot: OFF"
  fi
  adb shell 'pidof pixelproxy >/dev/null && echo "pixelproxy: running" || echo "pixelproxy: NOT running"'
}

tap_tile() {
  adb shell cmd statusbar expand-settings
  sleep 2
  adb shell uiautomator dump /data/local/tmp/ui.xml >/dev/null 2>&1
  b=$(adb shell cat /data/local/tmp/ui.xml | grep -oE 'content-desc="Hotspot"[^>]*bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1 | grep -oE '[0-9]+' | tail -4 | tr '\n' ' ')
  [[ -z $b ]] && { echo "Hotspot tile not found in Quick Settings"; adb shell cmd statusbar collapse; exit 1; }
  set -- ${=b}
  adb shell input tap $(( ($1 + $3) / 2 )) $(( ($2 + $4) / 2 ))
  sleep 5
  adb shell cmd statusbar collapse
}

case ${1:-status} in
  status) status ;;
  on)     is_on && echo "already on" || tap_tile; status ;;
  off)    is_on && tap_tile || echo "already off"; status ;;
  toggle) tap_tile; status ;;
  proxy)  adb shell 'pidof pixelproxy >/dev/null || (cd /data/local/tmp && setsid nohup ./pixelproxy :3128 > pixelproxy.log 2>&1 < /dev/null &)' &
          sleep 3; kill $! 2>/dev/null || true; status ;;
  restore) adb shell pm enable $ENT ;;
  *) echo "usage: $0 status|on|off|toggle|proxy|restore"; exit 1 ;;
esac
