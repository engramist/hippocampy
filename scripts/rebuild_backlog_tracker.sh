#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ARCHIVE="Backlog_Archive032726.md"
BACKLOG_DIR="backlog"
PLANS_DIR="$BACKLOG_DIR/plans"
TRACKER="$BACKLOG_DIR/masterBacklogTracker.md"
ROOT_TRACKER="masterBacklogTracker.md"
MATCH_REPORT="$BACKLOG_DIR/planCardMatches.md"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Missing $ARCHIVE" >&2
  exit 1
fi

mkdir -p "$BACKLOG_DIR"

# Extract card->priority from archive context.
awk '
BEGIN { p = "P99" }
/^## P[0-9]+/ {
  p = $2
}
/^### B[0-9]+/ {
  c = $2
  print c "\t" p
}
' "$ARCHIVE" > /tmp/card_priority.tsv

# Build sortable rows from split card files.
: > /tmp/tracker_rows.tsv
for f in "$BACKLOG_DIR"/B*.md; do
  [[ -f "$f" ]] || continue

  card="$(basename "$f" .md)"
  card_num="$(echo "$card" | sed -E 's/^B([0-9]+).*/\1/')"
  title="$(sed -n '1p' "$f" | sed -E 's/^# B[0-9]+ - //')"
  state="$(sed -n '3p' "$f" | sed -E 's/^State: //')"

  pri="$(grep -E "^${card}[[:space:]]" /tmp/card_priority.tsv | head -n 1 | cut -f2 || true)"
  [[ -n "$pri" ]] || pri="P99"
  pri_num="$(echo "$pri" | sed -E 's/^P([0-9]+)$/\1/')"

  plans="-"
  found=""
  if [[ -d "$PLANS_DIR" ]]; then
    for p in "$PLANS_DIR"/*.md; do
      [[ -f "$p" ]] || continue
      b="$(basename "$p")"
      if echo "$b" | grep -Eiq "(^|[^0-9])B-?${card_num}([^0-9]|$)"; then
        if [[ -z "$found" ]]; then
          found="backlog/plans/$b"
        else
          found="$found, backlog/plans/$b"
        fi
      fi
    done
  fi
  [[ -n "$found" ]] && plans="$found"

  safe_title="$(echo "$title" | sed 's/|/\\|/g')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$pri_num" "$card_num" "$card" "$safe_title" "$pri" "$state" "$plans" "backlog/${card}.md" >> /tmp/tracker_rows.tsv
done

{
  echo "# Master Backlog Tracker"
  echo
  echo "Generated from Backlog_Archive032726.md on 2026-03-27."
  echo
  echo "| Card | Title | Priority | State | Owner | Target Date | Matched Plan(s) | Card File |"
  echo "|---|---|---|---|---|---|---|---|"

  sort -t $'\t' -k1,1n -k2,2n /tmp/tracker_rows.tsv | while read -r line; do
    card="$(echo "$line" | cut -f3)"
    title="$(echo "$line" | cut -f4)"
    pri="$(echo "$line" | cut -f5)"
    state="$(echo "$line" | cut -f6)"
    plans="$(echo "$line" | cut -f7)"
    file="$(echo "$line" | cut -f8)"
    echo "| $card | $title | $pri | $state | TBD | TBD | $plans | $file |"
  done

  echo
  echo "## Summary"
  echo
  total="$(wc -l < /tmp/tracker_rows.tsv | tr -d ' ')"
  ready="$(awk -F '\t' '$6=="ready"{c++} END{print c+0}' /tmp/tracker_rows.tsv)"
  needs="$(awk -F '\t' '$6=="needs work"{c++} END{print c+0}' /tmp/tracker_rows.tsv)"
  complete="$(awk -F '\t' '$6=="complete"{c++} END{print c+0}' /tmp/tracker_rows.tsv)"
  inprog="$(awk -F '\t' '$6=="in progress"{c++} END{print c+0}' /tmp/tracker_rows.tsv)"
  blocked="$(awk -F '\t' '$6=="blocked"{c++} END{print c+0}' /tmp/tracker_rows.tsv)"

  echo "- Total cards: $total"
  echo "- Ready: $ready"
  echo "- Needs work: $needs"
  echo "- Complete: $complete"
  echo "- In progress: $inprog"
  echo "- Blocked: $blocked"
} > "$TRACKER"

cp "$TRACKER" "$ROOT_TRACKER"

{
  echo "# Backlog Plan Matches"
  echo
  echo "Generated from backlog cards and backlog/plans/*.md."
  echo
  echo "## Card -> Plan Matches"
  echo

  sort -t $'\t' -k2,2n /tmp/tracker_rows.tsv | while read -r line; do
    card="$(echo "$line" | cut -f3)"
    plans="$(echo "$line" | cut -f7)"
    [[ "$plans" == "-" ]] && plans="(none)"
    echo "- $card: $plans"
  done

  echo
  echo "## Unmatched Plan Files"
  echo

  if [[ -d "$PLANS_DIR" ]]; then
    for p in "$PLANS_DIR"/*.md; do
      [[ -f "$p" ]] || continue
      b="$(basename "$p")"
      matched=0
      while read -r row; do
        cnum="$(echo "$row" | cut -f2)"
        if echo "$b" | grep -Eiq "(^|[^0-9])B-?${cnum}([^0-9]|$)"; then
          matched=1
          break
        fi
      done < /tmp/tracker_rows.tsv
      if [[ "$matched" -eq 0 ]]; then
        echo "- backlog/plans/$b"
      fi
    done
  fi
} > "$MATCH_REPORT"

echo "Rebuilt: $TRACKER"
echo "Rebuilt: $ROOT_TRACKER"
echo "Rebuilt: $MATCH_REPORT"
