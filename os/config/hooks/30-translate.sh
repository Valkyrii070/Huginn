#!/bin/sh
# Offline translation (Argos Translate) for the Translate app. Ubuntu doesn't package it, so it comes from PyPI.
# It is asked for with the CPU-only build of its largest part (PyTorch); the ordinary build drags in graphics-card
# libraries and came to 5.5 GB when measured. If the CPU-only build can't be fetched this step is skipped and the
# image is built without it: Translate then says the translator isn't installed, and nothing else is affected.
# Language packs are not in the image: each person fetches the ones they want inside the app (about 100 MB a direction).
# To leave Translate out on purpose, delete this file.
apt-get install -y python3-pip python3-venv || exit 0
python3 -m venv --system-site-packages /opt/huginn-translate || exit 0
if /opt/huginn-translate/bin/pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
   && /opt/huginn-translate/bin/pip install --no-cache-dir argostranslate; then
    # The apps run on the system Python: let it see the translator's packages.
    site=$(python3 -c 'import site; print(site.getsitepackages()[0])')
    echo "$(echo /opt/huginn-translate/lib/python3*/site-packages)" > "$site/huginn-translate.pth"
    echo "Translate: installed ($(du -sh /opt/huginn-translate | cut -f1))."
else
    rm -rf /opt/huginn-translate
    echo "Translate: could not be fetched, so the image is built without it."
fi
exit 0
