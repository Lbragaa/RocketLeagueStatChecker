const SPREADSHEET_ID = '1Ks2KiCLUatlW97Krlyo2GFavp8-iIG8CGKX7m5pvQYs';
const HEADERS = ['UniqueKey','MatchGuid','Timestamp','PrimaryId','Name','Result','TeamScore',
  'OpponentScore','Score','Goals','Assists','Saves','Shots','Touches','CarTouches','Demos',
  'TeamNum','PlaylistId','PlaylistName','Arena','BlueScore','OrangeScore','WinnerTeamNum',
  'Overtime','DurationSeconds','Loadout','ObservedEvents','MatchObservedEvents','Mode','Revision'];

function reply(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}

function validate(p) {
  const secret = PropertiesService.getScriptProperties().getProperty('FDG_TOKEN');
  if (!secret || secret.length < 32 || p.token !== secret) throw new Error('Unauthorized');
  const m = p.match;
  if (m && m.Revision != null && (!Number.isSafeInteger(m.Revision) || m.Revision < 1)) throw new Error('Invalid revision');
  if (!m || typeof m.MatchGuid !== 'string' || !m.MatchGuid || m.MatchGuid.length > 256 ||
      !['fdg','casual-test'].includes(m.Mode) || ![3,13].includes(m.PlaylistId) ||
      (m.Mode === 'casual-test' && m.PlaylistId !== 3) ||
      !['WIN','LOSS'].includes(m.Result) || ![0,1].includes(m.WinnerTeamNum) ||
      typeof m.Timestamp !== 'string' || !Number.isFinite(Date.parse(m.Timestamp)) ||
      !Array.isArray(p.players) || p.players.length !== 3) throw new Error('Invalid match');
  ['TeamScore','OpponentScore','BlueScore','OrangeScore'].forEach(k => {
    if (!Number.isInteger(m[k]) || m[k] < 0) throw new Error('Invalid score');
  });
  const ids = new Set();
  p.players.forEach(x => {
    if (typeof x.PrimaryId !== 'string' || !x.PrimaryId || x.PrimaryId.length > 256 ||
        typeof x.Name !== 'string' || x.Name.length > 256 || ![0,1].includes(x.TeamNum)) throw new Error('Invalid player');
    ids.add(x.PrimaryId);
    ['Score','Goals','Assists','Saves','Shots','Touches','CarTouches','Demos'].forEach(k => {
      if (x[k] != null && (!Number.isInteger(x[k]) || x[k] < 0)) throw new Error('Invalid statistic');
    });
  });
  if (ids.size !== 3 || new Set(p.players.map(x => x.TeamNum)).size !== 1) throw new Error('Invalid roster');
  if ((p.players[0].TeamNum === m.WinnerTeamNum ? 'WIN' : 'LOSS') !== m.Result) throw new Error('Invalid result');
}

function table(ss, name, headers) {
  const sheet = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1,1,1,headers.length).setValues([headers]).setFontWeight('bold');
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1,headers.length);
  } else {
    const existing = sheet.getRange(1,1,1,headers.length).getValues()[0];
    if (headers[headers.length-1] === 'Revision' && existing[existing.length-1] === '' &&
        JSON.stringify(existing.slice(0,-1)) === JSON.stringify(headers.slice(0,-1))) {
      sheet.getRange(1,headers.length).setValues([['Revision']]).setFontWeight('bold');
    } else if (JSON.stringify(existing) !== JSON.stringify(headers)) {
      throw new Error('Existing tab has incompatible headers: ' + name);
    }
  }
  return sheet;
}

function safe(value) {
  if (value == null) return '';
  if (typeof value === 'object') value = JSON.stringify(value);
  // Prevent names and IDs from executing spreadsheet formulas.
  if (typeof value === 'string' && /^[=+\-@\t\r\n]/.test(value)) return "'" + value;
  return value;
}

function summary(ss, source, name) {
  const headers = ['PrimaryId','Name','Matches','Wins','Losses','Win %','Points','Goals','Assists','Saves',
    'Shots','Touches','Car touches','Demos','Points/game','Goals/game','Assists/game','Saves/game',
    'Shots/game','Touches/game','Car touches/game','Demos/game','Shooting %'];
  const dest = table(ss, name, headers);
  const rows = source.getLastRow() > 1 ? source.getRange(2,1,source.getLastRow()-1,HEADERS.length).getValues() : [];
  const grouped = new Map();
  rows.forEach(r => {
    const id = r[3];
    if (!grouped.has(id)) grouped.set(id, {name:r[4], n:0, w:0, totals:Array(8).fill(0), counts:Array(8).fill(0)});
    const a = grouped.get(id); a.name=r[4]; a.n++; a.w += r[5] === 'WIN' ? 1 : 0;
    for(let i=0;i<8;i++) if(typeof r[8+i] === 'number') {a.totals[i]+=r[8+i]; a.counts[i]++;}
  });
  const values = [...grouped].map(([id,a]) => [id,a.name,a.n,a.w,a.n-a.w,a.w/a.n,
    ...a.totals.map((v,i)=>a.counts[i] ? v : ''),
    ...a.totals.map((v,i)=>a.counts[i] ? v/a.counts[i] : ''),
    a.totals[4] && a.counts[1] === a.n && a.counts[4] === a.n ? a.totals[1]/a.totals[4] : ''].map(safe));
  if(dest.getLastRow()>1) dest.getRange(2,1,dest.getLastRow()-1,headers.length).clearContent();
  if(values.length) {
    dest.getRange(2,1,values.length,headers.length).setValues(values);
    dest.getRange(2,6,values.length,1).setNumberFormat('0.0%');
    dest.getRange(2,23,values.length,1).setNumberFormat('0.0%');
  }
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    if (!e || !e.postData || e.postData.contents.length > 200000) throw new Error('Invalid request');
    const p = JSON.parse(e.postData.contents);
    validate(p);
    lock.waitLock(20000);
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const prefix = p.match.Mode === 'fdg' ? 'FDG' : 'TEST';
    const sheet = table(ss, prefix + '_Matches', HEADERS);
    const existing = sheet.getLastRow()>1 ? sheet.getRange(2,1,sheet.getLastRow()-1,HEADERS.length).getValues() : [];
    const keys = new Map(existing.map((row,i)=>[row[0],{row:i+2,revision:Number(row[HEADERS.length-1]) || 0}]));
    const rows = [];
    let updated = 0;
    const revision = p.match.Revision || 1;
    p.players.forEach(player => {
      const m=p.match, key=m.MatchGuid+'|'+player.PrimaryId;
      const r = {...m,...player,UniqueKey:key,MatchObservedEvents:m.ObservedEvents,Revision:revision};
      const values = HEADERS.map(h=>safe(r[h]));
      if(keys.has(key)) {
        const previous=keys.get(key);
        if(revision>previous.revision) {
          sheet.getRange(previous.row,1,1,HEADERS.length).setValues([values]);
          updated++;
        }
      } else {
        rows.push(values);
      }
    });
    if(rows.length) sheet.getRange(sheet.getLastRow()+1,1,rows.length,HEADERS.length).setValues(rows);
    // Rebuild even on retries, recovering if a previous request failed after appending rows.
    summary(ss,sheet,prefix+'_Summary');
    SpreadsheetApp.flush();
    return reply({ok:true,protocol:2,matchGuid:p.match.MatchGuid,revision,inserted:rows.length,updated});
  } catch(err) {
    return reply({ok:false,error:String(err.message)});
  } finally {
    if(lock.hasLock()) lock.releaseLock();
  }
}
