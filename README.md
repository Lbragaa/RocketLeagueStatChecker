# RocketLeagueStatChecker — FDG

Manually started Windows collector for the **official Rocket League Stats API**.
No mods, game commands, services, startup entries, or teammate installations.
Python 3.11+; standard library only.

## First run on Windows

1. Install Python 3.11 or later from [python.org](https://www.python.org/downloads/windows/), including the Python launcher. Check `py -3 --version`.
2. In this folder, copy `.env.example` to `.env`. No `pip install` is necessary.
3. Keep your existing Stats API configuration, restart Rocket League if you changed it:

   ```ini
   [TAGame.MatchStatsExporter_TA]
   PacketSendRate=10
   Port=49123
   WebPort=49124
   ```

4. Double-click `start_fdg.bat` before playing. It connects to TCP `127.0.0.1:49123` and retries if the game closes. Keep the console open. Ctrl+C stops cleanly; closing the window stops capture too. SQLite commits each message so interrupted matches can resume.

If an ignored portable Python exists at `.venv\python.exe`, the launcher uses it. Otherwise it uses `py -3`.

## Discover and confirm identities

The collector initially observes names but does **not** trust them for saving eligible matches. In any live game it prints discovered IDs for `bregzz_`, `Moose-`, and `✪ Marinho`, and saves candidates to `data/discovered.json`. Each player can be discovered separately.

Verify the printed platform IDs, stop capture, then run each printed command in PowerShell, for example:

```powershell
.\start_fdg.bat --confirm-id "bregzz_" "Steam|ACTUAL_ID|0"
.\start_fdg.bat --confirm-id "Moose-" "Epic|ACTUAL_ID|0"
.\start_fdg.bat --confirm-id "✪ Marinho" "Epic|ACTUAL_ID|0"
```

Use actual observed IDs, not these examples. Restart capture after confirmation. Confirmations are stored locally in `data/identities.json`. Later display-name changes do not affect recognition. Duplicate or unobserved mappings are rejected. To fix a mapping, edit the local JSON while stopped, or confirm another observed candidate for that name.

## First test: play a random casual 3v3

You do **not** need Moose- or Marinho for this test:

1. Launch capture and enter a casual Standard game so it discovers your `bregzz_` ID.
2. Stop, confirm **your ID only**, then restart by double-clicking **`start_casual_test.bat`**.
3. Play another full casual Standard match with random teammates. The collector identifies your team using your confirmed ID and records its three players. It still requires playlist `3`, a live state, and a valid `MatchEnded`.
4. Stay through the scoreboard/podium for about three seconds. Compare the printed points, goals, assists and saves with your scoreboard. Inspect `data/fdg.sqlite3` for all player fields and event totals.
5. With Sheets configured, verify exactly three rows in **`TEST_Matches`**, plus totals in **`TEST_Summary`**. Play another game to check accumulation.

Test data never enters `FDG_Matches` or `FDG_Summary`. Switch back to `start_fdg.bat` for the trio. Normal mode requires all three confirmed IDs observed together on one team in playlist `3` or `13`; only those three receive rows. Set `FDG_PLAYLISTS=13` in `.env` for competitive only. Casual-test mode always accepts only playlist `3`.

In casual backfill games, a three-player roster seen together is retained even if someone leaves before the final scoreboard. The latest qualifying roster is used if a replacement arrives; all observed players remain in raw/local snapshots. Starting halfway through a game means observed event totals cover only the portion captured.

## Connect your existing Google Sheet (one time)

This uses only [Estatisticas FDG](https://docs.google.com/spreadsheets/d/1Ks2KiCLUatlW97Krlyo2GFavp8-iIG8CGKX7m5pvQYs/edit). The collector does not obtain Google permissions from Codex or ChatGPT.

1. Open that spreadsheet in Google Sheets using an account allowed to edit it.
2. Choose **Extensions → Apps Script**. Add the complete contents of `apps_script/Code.gs` to a new script file (or replace an empty starter file). Keep any unrelated existing scripts.
3. Generate a random token of at least 32 characters locally, for example:

   ```powershell
   py -3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

4. In Apps Script **Project Settings → Script Properties → Add script property**, set name **`FDG_TOKEN`**, value your generated token. Save. Do not put the token in the source file or Git.
5. Click **Deploy → New deployment → Select type → Web app**. Execute as **Me** (the spreadsheet editor). Who has access: **Anyone**. Click Deploy, authorize the script's spreadsheet access using that same Google account, and follow Google's review/authorization screens for your own script. If your Workspace organization prohibits anonymous web apps, this endpoint deployment requires an administrator to allow it.
6. Copy the deployed URL ending in **`/exec`** (not `/dev`). Put it into `.env` as `FDG_SHEETS_URL`. Set `FDG_SHEETS_TOKEN` to the identical Script Property token. Restart capture.
7. Finish a test match. The console will report synchronization within about 30 seconds. The receiver creates `TEST_Matches`/`TEST_Summary` for tests, `FDG_Matches`/`FDG_Summary` for normal play. It leaves `Sheet1` and other tabs intact. These four named tabs are collector-owned; use other tabs for your own notes and formulas. Incompatible existing headers cause an error instead of overwriting data.

After editing Apps Script, use **Deploy → Manage deployments → Edit → New version → Deploy** to update the deployed endpoint. Rotate the token in both places if exposed. Anyone with the token can submit statistics; treat it as a password. The receiver validates the payload, serializes requests with a script lock, and escapes spreadsheet formula prefixes in text.

## Storage, reliability and meaning of statistics

- `data/fdg.sqlite3`: `active` holds durable in-progress snapshots; `matches` contains completed payloads and persistent upload status; `players` has the unique `(MatchGuid, PrimaryId)` key and full final player JSON. `MatchGuid` is also unique in `matches`. The same real match cannot be saved once in each mode: choose test/FDG mode before playing.
- `data/raw/<hash>.jsonl.gz`: timestamped complete original JSON objects, including future events/fields. SHA-256 filenames avoid using external match IDs as paths. `wire-*.bin.gz` additionally preserves received socket bytes for framing diagnostics. No automatic retention/deletion; back up or archive this folder as needed. Raw data includes all observed players, not just FDG.
- Latest player snapshots merge missing fields without replacing them with invented zeros. Missing fields are blank in Sheets. Loadout and all other state fields remain in SQLite/raw JSON; key final statistics and observed event dictionaries go to Sheets.
- A valid `MatchEnded.WinnerTeamNum` starts a three-second settling period. Later `UpdateState` snapshots and podium data are retained. `MatchDestroyed` finalizes immediately if a valid ending was seen. Closing capture preserves checkpoints; reopening resumes settlement and pending uploads. Leaving before `MatchEnded` is never treated as completion. Forfeits work when the API emits this valid ending.
- If the collector has been stopped or disconnected across the final scoreboard, it cannot reconstruct messages that the game never delivered. Start before the match and remain connected through the podium. The three-second window is a practical initial default to validate against real captures, not a guarantee of undocumented message ordering.
- Team goals come from `Game.Teams.Score`; player points from `Players.Score`; player goals from `Players.Goals`. Winner comes only from `MatchEnded`, not guessed from the score. Overtime is latched once observed.
- `DurationSeconds` intentionally remains blank: the documented `Elapsed` is replay-only and the remaining clock is not a reliable total duration for joined-in-progress games or forfeits. Timestamps are local receipt times in UTC, not a claimed server match-start time.
- `ObservedEvents` counts received BallHit/GoalScored/CrossbarHit/BoostPickup/StatfeedEvent messages, with statfeed asset names grouped per player. Player attribution requires a unique current name + shortcut + team match. These are **observed event counts**, not replacements for scoreboard statistics, and can be incomplete after disconnects or mid-match starts. No inferred possession, boost usage, speed averages or other unavailable metrics.
- History replay playback is rejected via `ReplayCreated` and replay-only `Frame`/`Elapsed` fields. A live `bReplay=false` state must be observed. Goal replay snapshots are skipped, and known goal replay events are excluded from observed totals. The API's `bReplay` also covers normal goal replays; it cannot alone identify history playback.
- The Sheets queue persists before any HTTP request. Failed requests retry every 30 seconds and on next launch. Successful ACK must include the same match ID. Receiver keys are `MatchGuid + PrimaryId`; retries repair partially written matches and rebuild the summaries without duplicate player rows.
- Summary averages use the number of games with that statistic present; shooting percentage is total goals / total shots only when both fields are present for every game (blank if zero shots). Summary tabs are rebuilt from match rows after each request. Team totals are never calculated by adding individual player statistics.

## Tests and troubleshooting

```powershell
py -3 -m unittest discover -s tests -v
node tests/apps_script_test.cjs
```

The Python tests use documented-schema simulated events, fragmented TCP JSON, Unicode, filters, late scoreboard updates, overtime, forfeits, identity discovery, deduplication, restarts, and HTTP retries. The Node test runs the actual Apps Script receiver with in-memory Google service doubles. Neither requires Google credentials or a running game.

If disconnected, start Rocket League and verify `Test-NetConnection 127.0.0.1 -Port 49123`. If Python is missing, install it and reopen the terminal. If uploads stay pending, check the `/exec` URL, token, deployment permissions, and Apps Script **Executions** log. Do not share `.env`, `data/`, or raw captures publicly. For a protocol issue, retain raw captures; the official page specifies JSON envelopes but not TCP frame delimiters, so the parser accepts concatenated objects, newlines, or NUL separators and handles UTF-8 across packets.

Source: [official Rocket League Stats API](https://www.rocketleague.com/developer/stats-api), checked November 2, 2026. Normal-play field visibility and socket framing still need verification against your first live capture. This implementation never sends API commands.

## Final-score delay and capture recovery

The default delay is now **three seconds after MatchEnded**, allowing late scoreboard updates. Set `FDG_SETTLE_SECONDS=0` in `.env` to save immediately (late updates may be missed). You do not need to close the listener to save or upload. Leaving the match after a valid ending finalizes immediately when `MatchDestroyed` arrives; otherwise the timer runs while the listener stays open, even in the menus.

The Windows exporter may encode `Data` as a JSON string; both that live format and the documentation's object format are supported. To recover a previous wire capture, stop the listener, confirm your observed identity, then run:

```powershell
.\start_fdg.bat --mode casual-test --recover-wire "data\raw\wire-EXACT_FILENAME.bin.gz"
```

Use the actual filename from `data/raw`. Recovery processes the original complete messages before finalizing, requires the same eligibility/confirmed identity checks, and retries uploads. Repeating recovery cannot duplicate an already saved match. Captures from a running or interrupted writer can be read through their last complete message.
