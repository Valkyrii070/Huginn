#!/usr/bin/env bash
# Installs Huginn on Linux, for you only: run it in a terminal with
#   bash "Install Huginn (Linux).sh"
# It puts Huginn in your apps menu (and, if you like, on the desktop and the dock).
cd "$(dirname "$0")" && exec bash ./installer/install.sh "$@"
