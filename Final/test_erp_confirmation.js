const fs=require('fs'),vm=require('vm'),assert=require('assert');
(async()=>{
 let sent=0,last,dialog;
 class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.style={};this.events={};this.textContent='';}
  append(...children){this.children.push(...children)}
  setAttribute(){} addEventListener(name,fn){this.events[name]=fn} focus(){}
  close(){this.open=false} remove(){this.removed=true} showModal(){this.open=true;dialog=this}
  createTHead(){const value=new Element('thead');this.append(value);return value}
  createTBody(){const value=new Element('tbody');this.append(value);return value}
  insertRow(){const value=new Element('tr');this.append(value);return value}
  insertCell(){const value=new Element('td');this.append(value);return value}
 }
 const find=(el,fn)=>[...(fn(el)?[el]:[]),...el.children.flatMap(child=>find(child,fn))];
 const text=el=>el.textContent+' '+el.children.map(text).join(' ');
 const current={records:[{id:'A',version:'v1',data:{code:'A',name:'Original bag',sp:500}}]};
 const context={URL,Request,Headers,DOMException,HTMLDialogElement:Element,document:{activeElement:new Element('input'),body:new Element('body'),createElement:tag=>new Element(tag)},location:{href:'https://erp.kalajay.in/erp/',origin:'https://erp.kalajay.in'},window:{fetch:async(input,options)=>{if(options?.method==='POST'){sent++;last=options;return {ok:true}}return {ok:true,json:async()=>current}}}};
 vm.runInNewContext(fs.readFileSync(__dirname+'/erp-actions.js','utf8'),context);
 const options={method:'POST',body:JSON.stringify({kind:'products',action:'edit',id:'A',version:'v1',data:{code:'A',name:'New bag',sp:600}})};
 let pending=context.window.fetch('/api/erp/record-action',options);await new Promise(setImmediate);
 assert(dialog.open);assert(text(dialog).includes('Original bag'));assert(text(dialog).includes('New bag'));assert(text(dialog).includes('500'));assert(text(dialog).includes('600'));assert.equal(sent,0);
 find(dialog,el=>el.tagName==='button'&&el.textContent==='Cancel')[0].onclick();await assert.rejects(pending,{name:'AbortError'});assert.equal(sent,0);
 pending=context.window.fetch('/api/erp/record-action',options);await new Promise(setImmediate);
 find(dialog,el=>el.tagName==='button'&&el.textContent==='Save Changes')[0].onclick();await pending;assert.equal(sent,1);assert.equal(last.headers.get('X-ERP-Confirmed'),'yes');
 current.records[0].version='v2';await assert.rejects(context.window.fetch('/api/erp/record-action',options),/record changed/);assert.equal(sent,1);
 pending=context.window.fetch('/api/erp/record-action',{method:'POST',body:JSON.stringify({kind:'products',action:'delete',id:'A',version:'v2'})});await new Promise(setImmediate);
 assert(text(dialog).includes('Original bag'));assert(text(dialog).includes('Confirm deletion'));dialog.events.cancel({preventDefault(){}});await assert.rejects(pending,{name:'AbortError'});assert.equal(sent,1);
 console.log('PASS: before/after review, cancel and Escape block writes, explicit save confirms, stale records cannot save.');
})().catch(error=>{console.error(error);process.exitCode=1});
