#!/bin/bash
# Start the 13F research app on :8001.
#
# One-command startup alias — add to ~/.zshrc:
#   alias 13f='cd ~/ClaudeWorkspace/Projects/13f-ownership && ./scripts/start_app.sh && open http://localhost:8001'
#
# Then run `13f` from any terminal to boot the server and open the UI.

cd ~/ClaudeWorkspace/Projects/13f-ownership
python3 scripts/app.py --port 8001
