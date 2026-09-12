#!/bin/sh
# The compose `agent` service's loop: one `--consume` tick a minute (claims a
# queued run or fires a due schedule, then exits) and a `--ground-only`
# refresh every 15th tick. One-shot ticks under a loop mean a crashed pass
# never takes the ticker down — the next check happens a minute later.
#
# Each tick runs as a child under `wait` with TERM/INT forwarded to it, so a
# `docker stop` reaches the Python job — which fails the run it was driving
# on the way out — instead of only killing this shell: a `sh -c` loop as PID
# 1 never delivers the signal to its foreground child. The sleep is
# backgrounded for the same reason; a foreground sleep would hold the trap
# until it finished.
set -u

child=0

stop() {
  if [ "$child" -ne 0 ]; then
    kill -TERM "$child" 2>/dev/null
    wait "$child"
  fi
  exit 0
}
trap stop TERM INT

# run one command as the supervised child
tick() {
  "$@" &
  child=$!
  wait "$child"
  child=0
}

i=0
while :; do
  tick python main.py --consume
  i=$((i + 1))
  if [ $((i % 15)) -eq 0 ]; then
    tick python main.py --ground-only
  fi
  tick sleep 60
done
