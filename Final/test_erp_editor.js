const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Logic{setState(x){Object.assign(this.state,typeof x==='function'?x(this.state):x)}}
const context={DCLogic:Logic,setTimeout:()=>1,clearTimeout(){}};vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/erp/index.html','utf8').match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)[1]+';this.Component=Component;',context);
(async()=>{const c=new context.Component();c.props={};const p=code=>({code,name:code,cat:'Bags',unit:'pcs',open:5,purch:0,made:0,sold:0,dmg:0,cp:10,sp:50,mrp:60,variants:[]});c.state.products=[p('A'),p('B')];
 c.state.draft={code:'A',name:'Accidental replacement'};await c.saveDraft();assert.match(c.state.addError,/already belongs/);
 c.editOptionProduct('A');c.state.draft.code='b';await c.saveDraft();assert.match(c.state.addError,/already belongs/);
 c.editOptionProduct('A');c.state.draft.name='Updated A';c.commit=async()=>false;await c.saveDraft();assert.equal(c.state.draft.name,'Updated A');
 c.commit=async()=>true;await c.saveDraft();assert.equal(Object.keys(c.state.draft).length,0);console.log('PASS: explicit product selection, case-insensitive duplicate rejection, cancelled save preserves draft');
})().catch(e=>{console.error(e);process.exitCode=1});
