const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Sheet {
  constructor() { this.rows=[]; }
  getLastRow() { return this.rows.length; }
  getRange(row,col,n=1,m=1) {
    const sheet=this;
    return {
      getValues() {return Array.from({length:n},(_,i)=>Array.from({length:m},(_,j)=>sheet.rows[row-1+i]?.[col-1+j]??''));},
      setValues(values) {values.forEach((r,i)=>r.forEach((v,j)=>{
        sheet.rows[row-1+i]??=[]; sheet.rows[row-1+i][col-1+j]=v;
      })); return this;},
      clearContent() {for(let i=0;i<n;i++) for(let j=0;j<m;j++) sheet.rows[row-1+i][col-1+j]=''; return this;},
      setFontWeight() {return this;}, setNumberFormat() {return this;}
    };
  }
  setFrozenRows() {} autoResizeColumns() {}
}
const sheets=new Map([['Sheet1',new Sheet()]]);
sheets.get('Sheet1').rows=[['keep me']];
const book={getSheetByName:n=>sheets.get(n),insertSheet:n=>{const s=new Sheet();sheets.set(n,s);return s;}};
let locked=false, authorizedOpens=0;
const token='test-secret-with-at-least-32-characters';
const context=vm.createContext({
  PropertiesService:{getScriptProperties:()=>({getProperty:()=>token})},
  ContentService:{MimeType:{JSON:'json'},createTextOutput:text=>({text,setMimeType(){return this;}})},
  LockService:{getScriptLock:()=>({waitLock(){assert.equal(locked,false);locked=true;},hasLock:()=>locked,releaseLock(){locked=false;}})},
  SpreadsheetApp:{openById(id){assert.equal(id,'1Ks2KiCLUatlW97Krlyo2GFavp8-iIG8CGKX7m5pvQYs');authorizedOpens++;return book;},flush(){}}
});
vm.runInContext(fs.readFileSync('apps_script/Code.gs','utf8'),context);
const payload={token,match:{MatchGuid:'m1',Timestamp:'2026-11-02T22:00:00Z',Mode:'fdg',PlaylistId:3,
  Result:'WIN',WinnerTeamNum:0,TeamScore:4,OpponentScore:2,BlueScore:4,OrangeScore:2},
  players:[0,1,2].map(i=>({PrimaryId:`Steam|${i}|0`,Name:i===2?'✪ Marinho':`Player${i}`,TeamNum:0,
    Score:600,Goals:2,Assists:1,Saves:2,Shots:4,Touches:20,CarTouches:3,Demos:1}))};
function post(p) {return JSON.parse(context.doPost({postData:{contents:JSON.stringify(p)}}).text);}
assert.equal(post({...payload,token:'wrong'}).ok,false);
assert.equal(authorizedOpens,0);
assert.equal(post(payload).inserted,3);
assert.equal(post(payload).inserted,0);
assert.equal(sheets.get('FDG_Matches').getLastRow(),4);
assert.equal(sheets.get('FDG_Summary').rows[1][2],1);
// Repair a partial previous request without duplicating existing rows.
sheets.get('FDG_Matches').rows.pop();
assert.equal(post(payload).inserted,1);
const test=structuredClone(payload); test.match.Mode='casual-test';test.match.MatchGuid='m2';
test.players[0].Name='=IMPORTXML("bad")';
assert.equal(post(test).inserted,3);
assert.equal(sheets.get('TEST_Matches').rows[1][4],"'=IMPORTXML(\"bad\")");
assert.equal(sheets.get('TEST_Summary').rows[1][22],0.5);
assert.equal(sheets.get('FDG_Matches').getLastRow(),4);
assert.deepEqual(sheets.get('Sheet1').rows,[['keep me']]);
const invalid=structuredClone(payload);invalid.players[2].PrimaryId=invalid.players[0].PrimaryId;
assert.equal(post(invalid).ok,false);
assert.equal(locked,false);
console.log('Apps Script: authentication, validation, deduplication, partial retry, summaries, formula escaping and test isolation passed.');
