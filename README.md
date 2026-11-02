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
.\start_fdg.bat --confirm-player "bregzz_"
.\start_fdg.bat --confirm-player "Moose-"
.\start_fdg.bat --confirm-player "✪ Marinho"
```

These commands confirm the sole observed ID for each named player. If multiple IDs were observed for the same name, select the correct one using Python directly: `.\.venv\python.exe -m fdg --confirm-id "NAME" "PLATFORM|ACTUAL_ID|0"` (or `py -3 -m fdg ...` with installed Python). Avoid passing pipe-containing IDs through a batch launcher from PowerShell. Restart capture after confirmation. Confirmations are stored locally in `data/identities.json`. Later display-name changes do not affect recognition. Duplicate or unobserved mappings are rejected. To fix a mapping, edit the local JSON while stopped, or confirm another observed candidate for that name.

## First test: play a random casual 3v3

You do **not** need Moose- or Marinho for this test:

1. Launch capture and enter a casual Standard game so it discovers your `bregzz_` ID.
2. Stop, confirm **your ID only**, then restart by double-clicking **`start_casual_test.bat`**.
3. Play another full casual Standard match with random teammates. The collector identifies your team using your confirmed ID and records its three players. It still requires playlist `3`, a live state, and a valid `MatchEnded`.
4. No scoreboard wait is required: keep the listener running and let the match finish. Compare the printed points, goals, assists and saves with your scoreboard. Inspect `data/fdg.sqlite3` for all player fields and event totals.
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
- `data/raw/<hash>.jsonl.gz`: timestamped complete original JSON objects, including future events/fields. SHA-256 filenames avoid using external match IDs as paths. `wire-*.bin.gz` additionally preserves received socket bytes for framing diagnostics. Debug captures are automatically pruned after 7 days or when the approximate 250 MB capture budget is exceeded; back up captures you want to keep. Raw data includes all observed players, not just FDG.
- Latest player snapshots merge missing fields without replacing them with invented zeros. Missing fields are blank in Sheets. Loadout and all other state fields remain in SQLite/raw JSON; key final statistics and observed event dictionaries go to Sheets.
- A valid `MatchEnded.WinnerTeamNum` saves immediately by default using the latest received snapshots. Later final `UpdateState` statistics revise the same match and player records, even after a collector restart. Missing fields preserve their previous values. Only the originally selected players can be updated; replay playback is excluded. Set `FDG_SETTLE_SECONDS` to a positive value if you prefer to delay the initial save. `MatchDestroyed` finalizes immediately if a valid ending was seen. Closing capture preserves checkpoints; reopening resumes settlement and pending uploads. Leaving before `MatchEnded` is never treated as completion. Forfeits work when the API emits this valid ending.
- If the collector has been stopped or disconnected across the final scoreboard, it cannot reconstruct messages that the game never delivered. Start before the match and keep the listener connected until it receives `MatchEnded`. Staying on the scoreboard or podium is not required. Later delivered final snapshots update the saved record. Data the game never sends cannot be recovered.
- Team goals come from `Game.Teams.Score`; player points from `Players.Score`; player goals from `Players.Goals`. Winner comes only from `MatchEnded`, not guessed from the score. Overtime is latched once observed.
- `DurationSeconds` intentionally remains blank: the documented `Elapsed` is replay-only and the remaining clock is not a reliable total duration for joined-in-progress games or forfeits. Timestamps are local receipt times in UTC, not a claimed server match-start time.
- `ObservedEvents` counts received BallHit/GoalScored/CrossbarHit/BoostPickup/StatfeedEvent messages, with statfeed asset names grouped per player. Player attribution requires a unique current name + shortcut + team match. These are **observed event counts**, not replacements for scoreboard statistics, and can be incomplete after disconnects or mid-match starts. No inferred possession, boost usage, speed averages or other unavailable metrics.
- History replay playback is rejected via `ReplayCreated` and replay-only `Frame`/`Elapsed` fields. A live `bReplay=false` state must be observed. Goal replay snapshots are skipped, and known goal replay events are excluded from observed totals. The API's `bReplay` also covers normal goal replays; it cannot alone identify history playback.
- The Sheets queue persists before any HTTP request. Failed requests retry every 30 seconds and on next launch. Successful ACK must include the same match ID. Receiver keys are `MatchGuid + PrimaryId`; higher revisions update existing rows and refresh summaries. Duplicate or older revisions cannot overwrite newer statistics. Retries repair partial requests. An acknowledgment for an older local payload never clears a newer pending upload. Existing match tabs gain a trailing `Revision` column without deleting their data.
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

The default delay is **zero seconds**: a valid `MatchEnded` saves immediately. You may leave the scoreboard once the match ends. Set `FDG_SETTLE_SECONDS=3` in `.env` if you prefer a short window for late updates; that timer also runs in the menus. With zero delay, later final statistics still revise the existing record and are uploaded on the next synchronization attempt (normally within 30 seconds). Offline recovery always processes later captured snapshots before finalizing. You do not need to close the listener to save or upload. Leaving the match after a valid ending finalizes immediately when `MatchDestroyed` arrives; otherwise the timer runs while the listener stays open, even in the menus.

The Windows exporter may encode `Data` as a JSON string; both that live format and the documentation's object format are supported. To recover a previous wire capture, stop the listener, confirm your observed identity, then run:

```powershell
.\start_fdg.bat --mode casual-test --recover-wire "data\raw\wire-EXACT_FILENAME.bin.gz"
```

Use the actual filename from `data/raw`. Recovery processes the original complete messages before finalizing, requires the same eligibility/confirmed identity checks, and retries uploads. Repeating recovery cannot duplicate an already saved match. Captures from a running or interrupted writer can be read through their last complete message.

## Upgrade for late scoreboard corrections

1. Stop the listener with Ctrl+C.
2. Replace the collector script in Apps Script with the current complete `apps_script/Code.gs` file.
3. **Deploy → Manage deployments → Edit (pencil) → Version: New version → Deploy**. Update the existing deployment to keep the same `/exec` URL and token.
4. Restart `start_casual_test.bat` or `start_fdg.bat`. No scoreboard waiting is required.

The collector detects the previous receiver version and keeps uploads pending until you upgrade. Local capture and revisions continue safely. No spreadsheet row deletion or manual sheet reset is needed.

## Automatic local cleanup

Cleanup runs at normal startup and about once per minute while listening. No service or scheduled task is installed. Restart the listener after upgrading to enable it.

- Raw debug captures: at most 7 days, with an approximate 250 MB total budget. Oldest captures go first. Files written in the last minute are temporarily protected; active/recent segments can exceed the budget briefly. Wire captures rotate every 16 MB of received data; per-match compressed JSONL files rotate at about 16 MB.
- Full local match/player records: synchronized matches older than 30 days are removed. Tiny match-ID entries remain to prevent re-counting archived matches. Database space is reclaimed when possible, or reused if busy.
- Pending uploads are never removed by match cleanup, regardless of age. Raw debug captures can expire independently; the complete structured upload payload remains until acknowledged.
- Abandoned in-progress checkpoints older than 7 days are removed; checkpoints with a valid completion event remain recoverable.
- Confirmed identities, configuration, and all Google Sheets match history and summaries are retained.

Optional `.env` overrides: `FDG_RAW_DAYS=7`, `FDG_RAW_MAX_MB=250`, `FDG_LOCAL_MATCH_DAYS=30`. Defaults apply to existing `.env` files too. Local storage can grow beyond these limits if uploads keep failing, because pending match statistics are deliberately preserved. To keep a permanent debug archive, copy captures elsewhere before they expire. Offline recovery skips cleanup so its input cannot be deleted during recovery.
