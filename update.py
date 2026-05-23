#!/usr/bin/env python3
"""
Fetch HA sensor states, write data.json + history.json, copy energy_log.csv,
then push everything to the fhhome GitHub Pages repo.
Run every 5 minutes via fhhome-push.timer.
Token stored in ~/.config/fhhome/ha_token (not in repo).
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

REPO       = os.path.dirname(os.path.abspath(__file__))
HA_URL     = 'http://localhost:8123'
TOKEN_FILE = os.path.expanduser('~/.config/fhhome/ha_token')
CSV_SRC    = '/DATA/AppData/homeassistant/config/energy_log.csv'
MAX_HIST   = 288   # 24 h at 5-min intervals

DIVIDE_10  = {'sensor.fan_one_power'}

SENSORS = [
    'sensor.accumulated_soc',
    'sensor.battery_flow_state',
    'sensor.total_watt_hours_remaining',
    'sensor.total_battery_ah_remaining',
    'sensor.battery_time_to_change',
    'sensor.estimated_solar_power',
    'sensor.total_load_power_adjusted',
    'sensor.battery_power_normalised',
    'sensor.battery_current',
    'sensor.daily_solar_production',
    'sensor.daily_consumption',
    'sensor.daily_charging',
    'sensor.daily_discharging',
    'sensor.solar_self_sufficiency',
    'sensor.battery_daily_net',
    'sensor.bms_200_bms_148_soc',
    'sensor.bms_100_bms_50_soc',
    'sensor.refrigerator_power',
    'sensor.microwave_power',
    'sensor.washer_power',
    'sensor.kettle_power',
    'sensor.egg_cooker_power',
    'sensor.fan_one_power',
    'sensor.uv_switch_power',
]


def fetch_state(token, entity_id):
    url = f'{HA_URL}/api/states/{entity_id}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())['state']


def flt(v, default=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def git(args, **kw):
    return subprocess.run(['git', '-C', REPO] + args, check=True, **kw)


def main():
    if not os.path.exists(TOKEN_FILE):
        sys.exit(f'Token file not found: {TOKEN_FILE}')

    with open(TOKEN_FILE) as f:
        token = f.read().strip()

    # ── Fetch sensor states ──────────────────────────────────────────
    states = {}
    for s in SENSORS:
        try:
            val = fetch_state(token, s)
            if s in DIVIDE_10:
                val = str(flt(val) / 10)
            states[s] = val
        except Exception as e:
            print(f'Warning: {s}: {e}', file=sys.stderr)
            states[s] = 'unavailable'

    now = datetime.now(timezone.utc).isoformat()

    # ── Build data.json ──────────────────────────────────────────────
    data = {
        'updated':          now,
        'soc':              flt(states.get('sensor.accumulated_soc')),
        'flow':             states.get('sensor.battery_flow_state', 'Unknown'),
        'wh_remaining':     flt(states.get('sensor.total_watt_hours_remaining')),
        'ah_remaining':     flt(states.get('sensor.total_battery_ah_remaining')),
        'time_to_change':   flt(states.get('sensor.battery_time_to_change')),
        'solar_w':          flt(states.get('sensor.estimated_solar_power')),
        'load_w':           flt(states.get('sensor.total_load_power_adjusted')),
        'battery_w':        flt(states.get('sensor.battery_power_normalised')),
        'battery_a':        flt(states.get('sensor.battery_current')),
        'solar_today':      flt(states.get('sensor.daily_solar_production')),
        'load_today':       flt(states.get('sensor.daily_consumption')),
        'charged_today':    flt(states.get('sensor.daily_charging')),
        'discharged_today': flt(states.get('sensor.daily_discharging')),
        'self_sufficiency': flt(states.get('sensor.solar_self_sufficiency')),
        'battery_net':      flt(states.get('sensor.battery_daily_net')),
        'bms148_soc':       flt(states.get('sensor.bms_200_bms_148_soc')),
        'bms50_soc':        flt(states.get('sensor.bms_100_bms_50_soc')),
        'consumers': sorted([
            {'name': 'Refrigerator', 'w': flt(states.get('sensor.refrigerator_power'))},
            {'name': 'Microwave',    'w': flt(states.get('sensor.microwave_power'))},
            {'name': 'Washer',       'w': flt(states.get('sensor.washer_power'))},
            {'name': 'Kettle',       'w': flt(states.get('sensor.kettle_power'))},
            {'name': 'Egg Cooker',   'w': flt(states.get('sensor.egg_cooker_power'))},
            {'name': 'Fan',          'w': flt(states.get('sensor.fan_one_power'))},
            {'name': 'UV Switch',    'w': flt(states.get('sensor.uv_switch_power'))},
        ], key=lambda x: x['w'], reverse=True),
    }

    # ── Update history.json (rolling 24 h) ──────────────────────────
    hist_path = os.path.join(REPO, 'history.json')
    try:
        with open(hist_path) as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    history.append({
        't':       now,
        'solar':   data['solar_w'],
        'load':    data['load_w'],
        'battery': data['battery_w'],
        'soc':     data['soc'],
    })
    history = history[-MAX_HIST:]

    with open(os.path.join(REPO, 'data.json'), 'w') as f:
        json.dump(data, f)
    with open(hist_path, 'w') as f:
        json.dump(history, f)

    # ── Copy energy_log.csv ──────────────────────────────────────────
    if os.path.exists(CSV_SRC):
        shutil.copy2(CSV_SRC, os.path.join(REPO, 'energy_log.csv'))
    else:
        print(f'Warning: CSV not found at {CSV_SRC}', file=sys.stderr)

    # ── Git commit & push ────────────────────────────────────────────
    git(['add', 'data.json', 'history.json', 'energy_log.csv'])

    diff = subprocess.run(['git', '-C', REPO, 'diff', '--cached', '--quiet'])
    if diff.returncode == 0:
        print('No changes — skipping commit')
        return

    last = subprocess.run(
        ['git', '-C', REPO, 'log', '-1', '--format=%s'],
        capture_output=True, text=True
    ).stdout.strip()

    if last.startswith('data:'):
        git(['commit', '--amend', '--no-edit', f'--date={now}'])
        git(['push', '--force', 'origin', 'main'])
    else:
        git(['commit', '-m', f'data: live snapshot {now[:16]}'])
        git(['push', 'origin', 'main'])

    print(f'Pushed at {now}')


if __name__ == '__main__':
    main()
