{ lib
, python3Packages
}:

python3Packages.buildPythonApplication {
  pname = "inkypi";
  version = "1.0.0";
  format = "other";

  src = ./.;

  propagatedBuildInputs = with python3Packages; [
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
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/inkypi $out/bin
    cp -r src/* $out/lib/inkypi/

    cat > $out/bin/inkypi <<EOF
    #!/bin/sh
    export PYTHONPATH="$out/lib/inkypi:\$PYTHONPATH"
    exec ${python3Packages.python.interpreter} $out/lib/inkypi/inkypi.py "\$@"
    EOF
    chmod +x $out/bin/inkypi

    runHook postInstall
  '';

  meta = with lib; {
    description = "E-Paper photoframe and dashboard server";
    homepage = "https://github.com/npontious/InkyPi";
    license = licenses.gpl3Only;
    maintainers = [ ];
    mainProgram = "inkypi";
  };
}
