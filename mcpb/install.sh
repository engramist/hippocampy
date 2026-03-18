#!/bin/bash
# mcpb/install.sh — SideQuests Brain Daemon lifecycle install hook
# Called by Claude Desktop when user installs the .mcpb bundle.
set -e

echo "Installing SideQuests Brain Daemon..."

# 1. Install Python dependencies
pip install -r requirements.txt || pip3 install -r requirements.txt
echo "  [✓] Python dependencies installed"

# 2. Download spaCy language model
python -m spacy download en_core_web_md 2>/dev/null \
  || python3 -m spacy download en_core_web_md
echo "  [✓] spaCy model downloaded"

# 3. Create sidequests config directory
mkdir -p "$HOME/.sidequests"

# 4. Write launchd plist and load the daemon
python -c "
from sidequests.cli.launchd import write_plist, load_plist
plist = write_plist()
print(f'  [✓] launchd plist written: {plist}')
if load_plist():
    print('  [✓] Brain Daemon started via launchd')
else:
    print('  [!] launchctl load failed — start manually: sidequests start')
" 2>/dev/null || python3 -c "
from sidequests.cli.launchd import write_plist, load_plist
plist = write_plist()
print(f'  [✓] launchd plist written: {plist}')
if load_plist():
    print('  [✓] Brain Daemon started via launchd')
else:
    print('  [!] launchctl load failed — start manually: sidequests start')
"

# 5. Brief wait for daemon to initialize, then smoke test
sleep 3
echo ""
echo "Running smoke test..."
python -c "
from sidequests.cli.smoke_test import check_status
check_status()
" 2>/dev/null || python3 -c "
from sidequests.cli.smoke_test import check_status
check_status()
" || echo "  [!] Smoke test failed — daemon may still be starting. Try: sidequests status"

echo ""
echo "SideQuests Brain Daemon installation complete."
echo "Memory capture is now active for Claude Desktop sessions."
