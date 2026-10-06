# Glacio Hidden Wi-Fi AP & InkyPi Service Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy InkyPi to run persistently as a systemd service on `glacio` (port 8085) with a cloaked 2.4 GHz Wi-Fi AP (`inkypi-net`) on interface `ap0`, route the Seeed Studio XIAO EE02 ESP32 to it, and verify end-to-end rendering on the 13.3" Spectra 6 e-ink display.

**Architecture:** A virtual wireless AP interface `ap0` is created on Qualcomm FastConnect 7800 radio (`phy0`) alongside the active 5 GHz client connection `wlp5s0` (`WSU-Secure`). Hostapd serves a hidden WPA2-Personal network on `ap0` with dnsmasq providing DHCP (`192.168.101.x`) and NAT forwarding via `wlp5s0`. InkyPi runs as a declarative NixOS systemd service on port 8085. The ESP32 associates with `inkypi-net`, receives DHCP, and updates over local HTTP.

**Tech Stack:** NixOS 26.11, systemd, hostapd, dnsmasq, iptables NAT, Python 3 / Flask / Waitress / Pillow, ESP32-S3 (Seeed XIAO EE02).

**Spec:** [`docs/superpowers/specs/2026-10-05-glacio-inkypi-deployment-design.md`](file:///home/nicho/Documents/GitHub/InkyPi/docs/superpowers/specs/2026-10-05-glacio-inkypi-deployment-design.md)

## Global Constraints

- SSID must remain strictly hidden (`ignore_broadcast_ssid = 1`).
- Passphrase: `Sn1J1mZPitus9hJrkp8N` (WPA2-PSK).
- InkyPi port on `glacio` must be **8085** (port 8080 is reserved for Open WebUI).
- `wlp5s0` connection to `WSU-Secure` and default route MUST NOT be disrupted or disconnected.
- All NixOS changes on `glacio` must be committed to `/etc/nixos` git repository and rebuilt via `sudo nixos-rebuild switch --flake /etc/nixos#glacio`.

## Review Focus

1. **Uplink Preservation:** `wlp5s0` stays connected to `WSU-Secure` with default gateway unchanged when `ap0` is brought up.
2. **Hidden SSID Association:** ESP32 successfully associates with `inkypi-net` despite beacons omitting the SSID string.
3. **Port Conflict Avoidance:** Port 8085 binds cleanly without interfering with Open WebUI on 8080 or other active services.
4. **DHCP & Routing:** `dnsmasq` serves valid leases on `ap0` (`192.168.101.50-150`) without breaking DHCP on `enp4s0` (`192.168.100.x`).
5. **Persistent Auto-start:** Both `hostapd` and `inkypi` services resume automatically across reboots.

---

### Task 1: Synchronize InkyPi Branch to GitHub and `glacio`

**Files:**
- Local: `/home/nicho/Documents/GitHub/InkyPi`
- Remote: `glacio:/home/nicho/InkyPi`

**Interfaces:**
- Consumes: Local branch `feat/remote-photoframe-esp32`
- Produces: Clean checkout on `glacio:/home/nicho/InkyPi` with device config

- [ ] **Step 1: Commit and push local branch to GitHub**

```bash
git push -u origin feat/remote-photoframe-esp32
```

- [ ] **Step 2: Verify git push succeeded**

Run: `git status`
Expected: "Your branch is up to date with 'origin/feat/remote-photoframe-esp32'."

- [ ] **Step 3: Clone or update repository on `glacio`**

```bash
ssh glacio '
  if [ -d "/home/nicho/InkyPi/.git" ]; then
    cd /home/nicho/InkyPi && git fetch origin && git checkout feat/remote-photoframe-esp32 && git pull
  else
    git clone https://github.com/NPontious/InkyPi.git /home/nicho/InkyPi &&
    cd /home/nicho/InkyPi && git checkout feat/remote-photoframe-esp32
  fi
'
```

- [ ] **Step 4: Sync device configuration to `glacio`**

```bash
rsync -avz src/config/device_dev.json glacio:/home/nicho/InkyPi/src/config/device_dev.json
```

- [ ] **Step 5: Verify repository on `glacio`**

Run: `ssh glacio "cd /home/nicho/InkyPi && git status && cat src/config/device_dev.json | grep 'photoframe'"`
Expected: Clean branch `feat/remote-photoframe-esp32`, device config contains `"display_type": "photoframe"`.

---

### Task 2: Create NixOS InkyPi Service Module on `glacio`

**Files:**
- Create: `glacio:/etc/nixos/modules/inkypi.nix`
- Modify: `glacio:/etc/nixos/hosts/glacio/configuration.nix`

**Interfaces:**
- Consumes: Python package dependencies from `nixpkgs`
- Produces: `systemd.services.inkypi` exposing port 8085

- [ ] **Step 1: Write `inkypi.nix` module on `glacio`**

Write `/etc/nixos/modules/inkypi.nix` via SSH:
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

- [ ] **Step 2: Import and enable module in `/etc/nixos/hosts/glacio/configuration.nix`**

Add `../../modules/inkypi.nix` to `imports` list and set `mySystem.services.inkypi.enable = true;`.

- [ ] **Step 3: Verify flake syntax on `glacio`**

Run: `ssh glacio "cd /etc/nixos && git add modules/inkypi.nix hosts/glacio/configuration.nix && nix flake check --no-build"`
Expected: Flake evaluation succeeds without syntax errors.

---

### Task 3: Configure Hidden Virtual AP & Routing on `glacio`

**Files:**
- Modify: `glacio:/etc/nixos/hosts/glacio/networking.nix`

**Interfaces:**
- Consumes: `phy0` wireless radio
- Produces: `ap0` virtual interface, `hostapd` 2.4 GHz hidden network, `dnsmasq` DHCP subnet

- [ ] **Step 1: Update `/etc/nixos/hosts/glacio/networking.nix`**

Update `networking.nix` with the following configuration:
```nix
{ config, pkgs, ... }:

{
  networking = {
    networkmanager.unmanaged = [ "interface-name:ap0" ];

    interfaces.eno0.useDHCP = true;

    interfaces.enp4s0 = {
      ipv4.addresses = [{
        address = "192.168.100.1";
        prefixLength = 24;
      }];
    };

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
      extraCommands = ''
        iptables -A INPUT -i enp4s0 -p vrrp -j ACCEPT
        iptables -t mangle -A POSTROUTING -o wlp5s0 -j TTL --ttl-set 64
      '';
      extraStopCommands = ''
        iptables -t mangle -D POSTROUTING -o wlp5s0 -j TTL --ttl-set 64 || true
      '';
      checkReversePath = false;
    };
  };

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

  services.dnsmasq = {
    enable = true;
    resolveLocalQueries = false;

    settings = {
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
  };
}
```

- [ ] **Step 2: Stage changes in `/etc/nixos`**

```bash
ssh glacio "cd /etc/nixos && git add hosts/glacio/networking.nix"
```

- [ ] **Step 3: Verify flake evaluation**

Run: `ssh glacio "cd /etc/nixos && nix flake check --no-build"`
Expected: Flake evaluation passes.

---

### Task 4: Rebuild NixOS and Validate Services on `glacio`

**Files:**
- System state on `glacio`

**Interfaces:**
- Consumes: Modified `/etc/nixos` flake
- Produces: Running `hostapd`, `create-ap0`, `dnsmasq`, and `inkypi` services

- [ ] **Step 1: Commit `/etc/nixos` changes on `glacio`**

```bash
ssh glacio "cd /etc/nixos && git commit -m 'feat(glacio): add inkypi service and hidden ap0 wifi network'"
```

- [ ] **Step 2: Execute nixos-rebuild switch**

Run: `ssh -t glacio "sudo nixos-rebuild switch --flake /etc/nixos#glacio"`
Expected: Build and switch succeeds.

- [ ] **Step 3: Verify network interfaces and services**

Run:
```bash
ssh glacio "
  ip a show ap0 &&
  systemctl is-active hostapd &&
  systemctl is-active inkypi &&
  systemctl is-active dnsmasq &&
  curl -I http://localhost:8085/api/status
"
```
Expected: `ap0` has IP `192.168.101.1/24`, services are active, `HTTP/1.1 200 OK` from port 8085.

- [ ] **Step 4: Verify uplink preservation**

Run:
```bash
ssh glacio "
  nmcli dev wifi | grep WSU-Secure &&
  ping -c 3 -I wlp5s0 1.1.1.1
"
```
Expected: `wlp5s0` connected to `WSU-Secure`, 0% packet loss.

---

### Task 5: Provision ESP32 with Hidden Wi-Fi Credentials

**Files:**
- Hardware: Seeed Studio XIAO EE02 (`/dev/ttyACM0` on `vesania`)

**Interfaces:**
- Consumes: SSID `inkypi-net`, passphrase `Sn1J1mZPitus9hJrkp8N`, URL `http://192.168.101.1:8085/api/photoframe/image`
- Produces: ESP32 associated with `inkypi-net` on `glacio`

- [ ] **Step 1: Send configuration payload to ESP32**

Using HTTP API via its current hotspot IP (`10.218.170.123`) or via serial CLI:
```bash
curl -X POST http://10.218.170.123/api/settings \
  -H "Content-Type: application/json" \
  -d '{
    "wifi": {
      "ssid": "inkypi-net",
      "password": "Sn1J1mZPitus9hJrkp8N"
    },
    "picture": {
      "url": "http://192.168.101.1:8085/api/photoframe/image"
    }
  }'
```

- [ ] **Step 2: Restart ESP32**

```bash
curl -X POST http://10.218.170.123/api/reboot || true
```

- [ ] **Step 3: Monitor DHCP lease on `glacio`**

Run: `ssh glacio "journalctl -u dnsmasq -n 20 --no-pager | grep DHCPACK"`
Expected: DHCPACK sent to ESP32 with IP `192.168.101.x`.

---

### Task 6: End-to-End Image Rendering & Push Notification Verification

**Files:**
- E-Paper hardware: 13.3" Spectra 6 (1600×1200)

**Interfaces:**
- Consumes: ESP32 connected to `inkypi-net`
- Produces: Physical e-paper update on panel

- [ ] **Step 1: Check InkyPi client telemetry on `glacio`**

Run: `ssh glacio "curl -s http://localhost:8085/api/photoframe/status"`
Expected: JSON response with `remote_client_ip` in `192.168.101.x` and valid battery percentage.

- [ ] **Step 2: Trigger manual refresh on InkyPi**

```bash
ssh glacio "curl -X POST http://localhost:8085/api/refresh -H 'Content-Type: application/json' -d '{\"plugin_id\": \"comic\"}'"
```

- [ ] **Step 3: Verify push notification and display refresh**

Run: `ssh glacio "journalctl -u inkypi -n 30 --no-pager | grep -i 'push'"`
Expected: Logs show push notification sent to `http://192.168.101.x/api/rotate`.
Physical check: The 13.3" Spectra 6 display flashes and renders the new comic image cleanly.
