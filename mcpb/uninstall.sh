#!/bin/bash
# mcpb/uninstall.sh — SideQuests Brain Daemon lifecycle uninstall hook
# Called by Claude Desktop when user removes the .mcpb bundle.

echo "Stopping SideQuests Brain Daemon..."

# 1. Unload daemon from launchd
python -c "
from sidequests.cli.launchd import unload_plist, PLIST_PATH
unload_plist()
print(f'  [✓] Brain Daemon stopped')
" 2>/dev/null || python3 -c "
from sidequests.cli.launchd import unload_plist
unload_plist()
print('  [✓] Brain Daemon stopped')
" || launchctl unload ~/Library/LaunchAgents/ai.sidequests.brain.plist 2>/dev/null || true

# 2. Remove launchd plist
rm -f ~/Library/LaunchAgents/ai.sidequests.brain.plist
echo "  [✓] launchd plist removed"

# 3. Data is preserved (never deleted on uninstall)
echo ""
echo "SideQuests Brain Daemon uninstalled."
echo "Your memory data is preserved at ~/.sidequests/"
echo "To permanently remove all data: rm -rf ~/.sidequests/"
