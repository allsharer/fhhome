#!/usr/bin/env python3
"""
Push fhhome data files to GitHub Pages every 5 minutes.
Data is written by energy-monitor/update.py (runs every 15 s) —
this script only handles the git commit & push.
Run every 5 minutes via fhhome-push.timer (systemd user unit).
"""

import os
import subprocess
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.abspath(__file__))


def git(args, **kw):
    return subprocess.run(['git', '-C', REPO] + args, check=True, **kw)


def main():
    now = datetime.now(timezone.utc).isoformat()

    git(['add', 'data.json', 'history.json', 'energy_log.csv'])

    diff = subprocess.run(['git', '-C', REPO, 'diff', '--cached', '--quiet'])
    if diff.returncode == 0:
        print('No changes — skipping commit')
        return

    git(['commit', '-m', f'data: live snapshot {now[:16]}'])
    git(['push', 'origin', 'main'])

    print(f'Pushed at {now}')


if __name__ == '__main__':
    main()
