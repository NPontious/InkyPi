# Glacio Hidden Wi-Fi AP & InkyPi Service Deployment Design

- **Author:** Nicho (Pair Programming with Antigravity)
- **Date:** 2026-10-05
- **Status:** Approved / In Progress
- **Target Systems:**
  - `glacio` (AMD Ryzen 7 7840HS, NixOS 26.11 Flake, Qualcomm FastConnect 7800 `ath12k`)
  - Seeed Studio XIAO EE02 (ESP32-S3) + 13.3" Spectra 6 E-Ink Display (1600×1200)

---

## 1. Executive Summary

This design transitions the InkyPi e-paper display server from the developer laptop (`vesania`) to the permanent home server `glacio` (`100.85.234.127`). Because the campus Wi-Fi (`WSU-Secure`) requires 802.1X Enterprise authentication not supported by consumer ESP32 firmware, `glacio` will host a dedicated, **hidden** 2.4 GHz Wi-Fi network (`inkypi-net`) on a virtual access point interface (`ap0`). 

Simultaneously, `glacio`'s primary 5 GHz wireless uplink (`wlp5s0` connected to `WSU-Secure`) will remain uninterrupted. InkyPi will run persistently as a declarative NixOS systemd service on port **8085** (avoiding conflict with Open WebUI on port 8080). The ESP32 will connect to `inkypi-net`, obtain an IP address via DHCP, and fetch/display rendered images directly from `glacio`.

---

## 2. Constraints & Architectural Decisions

1. **Hidden SSID Requirement:**
   - The user requested that the network must not be auto-detected or visible to nearby peers.
   - Hostapd configuration will set `ignore_broadcast_ssid = 1` to suppress SSID broadcast in beacon frames.
2. **Qualcomm FastConnect 7800 Concurrent STA + AP:**
   - Hardware: Qualcomm FastConnect 7800 (`ath12k_pci`).
   - Radio capability: `#{ managed } <= 1, #{ AP } <= 16, #channels <= 2`.
   - Decision: A separate virtual interface `ap0` (`type __ap`) will be created on `phy0` with a distinct locally administered MAC address (`9e:04:b6:97:24:37`).
   - NetworkManager will be instructed to keep `ap0` unmanaged (`networking.networkmanager.unmanaged = [ "interface-name:ap0" ]`) so it does not interfere with `hostapd` or disconnect `wlp5s0`.
3. **Port Deconfliction:**
   - Port 8080 on `glacio` is already occupied by Open WebUI (`uvicorn`).
   - InkyPi will be configured to bind to port **8085** across all interfaces (`0.0.0.0:8085`), accessible via `ap0` (`192.168.101.1:8085`) and Tailscale.
4. **WPA Mode Compatibility:**
   - ESP32-S3 Arduino/ESP-IDF Wi-Fi stacks require standard WPA2-PSK (HMAC-SHA1 / CCMP).
   - Hostapd authentication mode will be `wpa2-sha1` (or transition mode) with a secure randomly generated passphrase to ensure instant, stable association.

---

## 3. Network Architecture & Configuration

```
                     [ Campus Wi-Fi: WSU-Secure ]
                                  ▲
                                  │ 5 GHz (Ch 157)
                            [ wlp5s0 ] (130.108.204.0/22)
                                  │
                 ┌────────────────┴────────────────┐
                 │          glacio (NixOS)         │
                 │                                 │
                 │   • InkyPi Server (:8085)       │
                 │   • hostapd daemon              │
                 │   • dnsmasq (DHCP 192.168.101.x)│
                 │   • NAT Masquerade on wlp5s0    │
                 └────────────────┬────────────────┘
                                  │
                             [ ap0 ] (Virtual AP, 2.4 GHz Ch 1)
                                  │ Hidden SSID: inkypi-net
                                  ▼
                      [ Seeed XIAO EE02 / ESP32 ]
                      IP: 192.168.101.x (via DHCP)
```

### 3.1 Interface Creation Unit (`create-ap0.service`)
A oneshot systemd service running before `hostapd.service`:
```nix
systemd.services.create-ap0 = {
  description = "Create virtual AP interface ap0 for hostapd";
  before = [ "hostapd.service" "network-addresses-ap0.service" ];
  wantedBy = [ "sys-subsystem-net-devices-ap0.device" ];
  serviceConfig = {
    Type = "oneshot";
    RemainAfterExit = true;
    ExecStart = "${pkgs.iw}/bin/iw phy phy0 interface add ap0 type __ap addr 9e:04:b6:97:24:37";
    ExecStop = "${pkgs.iw}/bin/iw dev ap0 del";
  };
};
```

### 3.2 Hostapd Configuration
In `/etc/nixos/hosts/glacio/networking.nix`:
```nix
networking.networkmanager.unmanaged = [ "interface-name:ap0" ];

services.hostapd = {
  enable = true;
  radios.ap0 = {
    band = "2g";
    channel = 1;
    countryCode = "US";
    networks.ap0 = {
      ssid = "inkypi-net";
      authentication = {
        mode = "wpa2-sha1";
        wpaPassword = "Sn1J1mZPitus9hJrkp8N";
      };
      settings = {
        ignore_broadcast_ssid = 1;
      };
    };
  };
};
```

### 3.3 Subnet, DHCP, NAT & Firewall
```nix
networking = {
  interfaces.ap0 = {
    ipv4.addresses = [{
      address = "192.168.101.1";
      prefixLength = 24;
    }];
  };

  nat = {
    enable = true;
    externalInterface = "wlp5s0";
    internalInterfaces = [ "enp4s0" "ap0" ];
  };

  firewall = {
    enable = true;
    trustedInterfaces = [ "docker0" "br+" "enp4s0" "ap0" ];
    allowedTCPPorts = [ 8085 ];
  };
};

services.dnsmasq.settings = {
  interface = [ "enp4s0" "ap0" ];
  dhcp-range = [
    "interface:enp4s0,192.168.100.50,192.168.100.150,12h"
    "interface:ap0,192.168.101.50,192.168.101.150,12h"
  ];
  dhcp-option = [
    "interface:enp4s0,option:router,192.168.100.1"
    "interface:enp4s0,option:dns-server,192.168.100.1"
    "interface:ap0,option:router,192.168.101.1"
    "interface:ap0,option:dns-server,192.168.101.1"
  ];
  server = [ "8.8.8.8" "1.1.1.1" ];
};
```

---

## 4. NixOS InkyPi Service Module

A new module will be created at `/etc/nixos/modules/inkypi.nix`:
```nix
{ config, lib, pkgs, ... }:

let
  cfg = config.mySystem.services.inkypi;
  pythonEnv = pkgs.python3.withPackages (ps: with ps; [
    flask
    python-dotenv
    requests
    pillow
    waitress
    psutil
    pytz
    icalendar
    feedparser
    astral
    numpy
    recurring-ical-events
  ]);
in
{
  options.mySystem.services.inkypi = {
    enable = lib.mkEnableOption "InkyPi E-Paper Image Server";
    port = lib.mkOption {
      type = lib.types.port;
      default = 8085;
      description = "Port to expose the InkyPi web interface on.";
    };
    packageDir = lib.mkOption {
      type = lib.types.str;
      default = "/home/nicho/InkyPi";
      description = "Location of the InkyPi repository checkout.";
    };
    user = lib.mkOption {
      type = lib.types.str;
      default = "nicho";
      description = "User account under which to run the service.";
    };
  };

  config = lib.mkIf cfg.enable {
    networking.firewall.allowedTCPPorts = [ cfg.port ];

    systemd.services.inkypi = {
      description = "InkyPi E-Paper Image Server";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];

      environment = {
        PYTHONPATH = "src";
        PORT = toString cfg.port;
      };

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        WorkingDirectory = cfg.packageDir;
        ExecStart = "${pythonEnv}/bin/python3 src/inkypi.py --dev --port ${toString cfg.port} --host 0.0.0.0";
        Restart = "always";
        RestartSec = "5s";
      };
    };
  };
}
```

This module is imported into `/etc/nixos/hosts/glacio/configuration.nix` and enabled with `mySystem.services.inkypi.enable = true;`.

---

## 5. Deployment & Code Synchronization

1. **Commit & Push Local Repo:**
   - Commit any pending changes on `feat/remote-photoframe-esp32` in `vesania:/home/nicho/Documents/GitHub/InkyPi`.
   - Push branch to GitHub remote `NPontious/InkyPi`.
2. **Clone & Setup on Glacio:**
   - On `glacio`, clone `https://github.com/NPontious/InkyPi.git` to `/home/nicho/InkyPi` and checkout `feat/remote-photoframe-esp32`.
   - Rsync `src/config/device_dev.json` and generated state to preserve configured plugins (Comic, Weather, etc.) and driver settings (`photoframe`).
3. **Flake Commit & System Switch:**
   - Stage nix files in `/etc/nixos`:
     - `/etc/nixos/modules/inkypi.nix` (new)
     - `/etc/nixos/hosts/glacio/networking.nix` (updated)
     - `/etc/nixos/hosts/glacio/configuration.nix` (updated)
   - Execute `sudo nixos-rebuild switch --flake /etc/nixos#glacio`.

---

## 6. ESP32 Onboarding & Verification

1. **ESP32 Wi-Fi Update:**
   - Update Wi-Fi settings on the XIAO EE02 to connect to SSID `inkypi-net` with the WPA2 passphrase.
   - Set image URL to `http://192.168.101.1:8085/api/photoframe/image`.
2. **Verification Checks:**
   - `glacio`: `ip a show ap0` has `192.168.101.1/24`.
   - `glacio`: `systemctl status hostapd` is active and running.
   - `glacio`: `systemctl status inkypi` is active and responding on `http://localhost:8085`.
   - `glacio`: `wlp5s0` is still connected to `WSU-Secure`, default route intact, Tailscale online.
   - `ESP32`: Connects to `inkypi-net`, receives DHCP lease from `dnsmasq` in `192.168.101.x`.
   - `Telemetry`: `curl http://localhost:8085/api/photoframe/status` shows ESP32 IP, battery percentage, and timestamp.
   - `Push Display Update`: Trigger manual update in InkyPi web UI; verify ESP32 receives push rotate signal and updates the physical 13.3" Spectra 6 display.
