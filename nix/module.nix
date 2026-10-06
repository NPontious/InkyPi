flakeSelf:
{ config, lib, pkgs, ... }:

let
  cfg = config.services.inkypi;
  configFile = pkgs.writeText "inkypi-device.json" (builtins.toJSON cfg.settings);

  pythonEnv = pkgs.python3.withPackages (ps: 
    (with ps; [
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
    ]) ++ (cfg.extraPythonPackages ps)
  );

  pluginPathArgs = lib.optionalString (cfg.extraPlugins != [ ])
    "--plugin-path ${lib.concatStringsSep ":" (map toString cfg.extraPlugins)}";
in
{
  options.services.inkypi = {
    enable = lib.mkEnableOption "InkyPi E-Paper Image Server";

    package = lib.mkOption {
      type = lib.types.package;
      default = flakeSelf.packages.${pkgs.system}.default;
      description = "The InkyPi package to use.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8085;
      description = "Port to listen on.";
    };

    host = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "Host address to bind to.";
    };

    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/inkypi";
      description = "State directory for mutable rendered images and cache.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "inkypi";
      description = "User account under which to run the service.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "inkypi";
      description = "Group under which to run the service.";
    };

    environmentFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Optional environment file (e.g. from agenix/sops-nix) for API keys.";
    };

    extraPlugins = lib.mkOption {
      type = lib.types.listOf lib.types.path;
      default = [ ];
      description = "Additional plugin directories to load.";
    };

    extraPythonPackages = lib.mkOption {
      type = lib.types.functionTo (lib.types.listOf lib.types.package);
      default = ps: [ ];
      description = "Extra Python packages to make available for community plugins.";
    };

    chromiumPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = pkgs.chromium;
      description = "Chromium package for rendering HTML-based plugins (e.g. calendar, weather).";
    };


    settings = lib.mkOption {
      type = lib.types.attrsOf lib.types.anything;
      default = { };
      description = "Declarative InkyPi device configuration matching device.json.";
    };
  };

  config = lib.mkIf cfg.enable {
    networking.firewall.allowedTCPPorts = [ cfg.port ];

    users.users = lib.mkIf (cfg.user == "inkypi") {
      inkypi = {
        isSystemUser = true;
        group = cfg.group;
        home = cfg.stateDir;
        createHome = false;
      };
    };

    users.groups = lib.mkIf (cfg.group == "inkypi") {
      inkypi = { };
    };

    systemd.services.inkypi = {
      description = "InkyPi E-Paper Image Server";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];

      environment = {
        PYTHONPATH = "${cfg.package}/lib/inkypi";
      };

      path = lib.optional (cfg.chromiumPackage != null) cfg.chromiumPackage;

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.group;
        StateDirectory = "inkypi";
        WorkingDirectory = cfg.stateDir;
        EnvironmentFile = lib.optional (cfg.environmentFile != null) cfg.environmentFile;
        ExecStart = "${pythonEnv}/bin/python3 ${cfg.package}/lib/inkypi/inkypi.py "
          + "--config-file ${configFile} "
          + "--state-dir ${cfg.stateDir} "
          + "--port ${toString cfg.port} "
          + "--host ${cfg.host} "
          + "--declarative "
          + pluginPathArgs;
        Restart = "always";
        RestartSec = "5s";
      };
    };
  };
}
