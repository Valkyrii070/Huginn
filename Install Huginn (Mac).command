#!/bin/bash
# Double-click to install Huginn on your Mac (macOS 11 or later). It makes Huginn.app in
# Applications, for you only. If macOS says it can't check this file: right-click it, choose
# Open, then Open again.
cd "$(dirname "$0")" && exec /bin/bash ./installer/install.sh "$@"
