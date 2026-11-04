const fs=require('fs'),vm=require('vm'),assert=require('assert');
(async()=>{
 let called=0,prompts=0,allow=false,last;
 const context={URL,Request,Headers,DOMException,location:{href:'https://erp.kalajay.in/erp/',origin:'https://erp.kalajay.in'},window:{fetch:async(i,o)=>{called++;last=o;return {ok:true}},confirm:()=>{prompts++;return allow}}};
 vm.runInNewContext(fs.readFileSync(__dirname+'/erp-actions.js','utf8'),context);
 await assert.rejects(context.window.fetch('/api/erp',{method:'POST',body:'{}'}),{name:'AbortError'});assert.equal(called,0);
 allow=true;await context.window.fetch('/api/erp/record-action',{method:'POST',body:JSON.stringify({action:'delete',kind:'products',id:'A'})});assert.equal(called,1);assert.equal(last.headers.get('X-ERP-Confirmed'),'yes');assert.equal(prompts,2);
 await context.window.fetch('/api/erp');assert.equal(prompts,2);
 await context.window.fetch('/api/catalogue/import-preview',{method:'POST'});assert.equal(prompts,2);
 for(const path of ['/api/erp/expenses','/api/erp/team','/api/erp/product-image','/api/catalogue/import','/api/auth/users'])await context.window.fetch(path,{method:'POST',body:'{}'});
 assert.equal(prompts,7);console.log('PASS: cancelled changes never reach server; every ERP mutation confirms; reads and import previews do not prompt');
})().catch(e=>{console.error(e);process.exitCode=1});
