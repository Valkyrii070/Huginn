#!/bin/sh
# Huginn's Terminal is the system's terminal: x-terminal-emulator runs it.
set -e
update-alternatives --install /usr/bin/x-terminal-emulator x-terminal-emulator /usr/bin/huginn-terminal 60
update-alternatives --set x-terminal-emulator /usr/bin/huginn-terminal
