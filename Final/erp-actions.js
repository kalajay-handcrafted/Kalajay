/* Every ERP write is confirmed before the request reaches the server. */
(()=>{
 const original=window.fetch.bind(window);
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 function summary(value){
  if(value===undefined)return '—';
  if(typeof value==='string'&&value.startsWith('data:'))return '[Attached file]';
  if(value&&typeof value==='object')return JSON.stringify(value,(_,v)=>typeof v==='string'&&v.startsWith('data:')?'[Attached file]':v);
  return String(value??'');
 }
 function changes(before,after,path='',out=[]){
  if(same(before,after))return out;
  if(before&&after&&typeof before==='object'&&typeof after==='object'){
   if(Array.isArray(before)&&Array.isArray(after)){
    const identity=x=>x&&typeof x==='object'&&(x.code||x.id||x.username);
    if([...before,...after].every(identity)){
     const old=new Map(before.map(x=>[identity(x),x])),next=new Map(after.map(x=>[identity(x),x]));
     for(const key of new Set([...old.keys(),...next.keys()]))changes(old.get(key),next.get(key),path+' / '+key,out);
     return out;
    }
   }
   for(const key of new Set([...Object.keys(before),...Object.keys(after)]))changes(before[key],after[key],path?path+' / '+key:key,out);
  }else out.push([path||'Record',summary(before),summary(after)]);
  return out;
 }
 let queue=Promise.resolve();
 function review(description,rows,remove=false){
  if(typeof document==='undefined'||typeof HTMLDialogElement==='undefined')return Promise.resolve(window.confirm(description));
  const show=()=>new Promise(resolve=>{
   const focus=document.activeElement,dialog=document.createElement('dialog');dialog.setAttribute('aria-labelledby','erp-confirm-title');
   dialog.style.cssText='box-sizing:border-box;width:min(880px,94vw);max-height:90dvh;overflow:auto;border:1px solid #c6b491;border-radius:14px;padding:24px;background:#fffdf7;color:#40291c;font:15px/1.5 system-ui';
   const title=document.createElement('h2');title.id='erp-confirm-title';title.textContent=remove?'Confirm deletion':'Review changes';title.style.marginTop='0';dialog.append(title);
   const text=document.createElement('p');text.textContent=description;dialog.append(text);
   if(rows.length){
    const scroll=document.createElement('div');scroll.style.cssText='overflow:auto;max-height:48dvh;margin:18px 0;border:1px solid #e7dcc2';
    const table=document.createElement('table');table.style.cssText='width:100%;border-collapse:collapse;font-size:13px';
    const head=table.createTHead().insertRow();for(const label of ['Field / record','Existing value','Proposed value']){const cell=document.createElement('th');cell.textContent=label;cell.style.cssText='text-align:left;padding:10px;background:#eee7d4;position:sticky;top:0';head.append(cell);}
    const body=table.createTBody();for(const row of rows){const tr=body.insertRow();for(const value of row){const cell=tr.insertCell();cell.textContent=value;cell.style.cssText='padding:10px;border-top:1px solid #e7dcc2;vertical-align:top;overflow-wrap:anywhere;min-width:100px;max-width:300px;white-space:pre-wrap';}}
    scroll.append(table);dialog.append(scroll);
   }
   const actions=document.createElement('div');actions.style.cssText='display:flex;gap:12px;flex-wrap:wrap;justify-content:flex-end';
   const cancel=document.createElement('button'),save=document.createElement('button');cancel.textContent='Cancel';save.textContent=remove?'Confirm deletion':'Save Changes';
   for(const button of [cancel,save]){button.type='button';button.style.cssText='font:inherit;padding:12px 18px;border:1px solid #9e5430;border-radius:8px;cursor:pointer';}
   save.style.background=remove?'#9b2929':'#9e5430';save.style.color='#fff';
   const finish=ok=>{dialog.close();dialog.remove();focus?.focus?.();resolve(ok);};cancel.onclick=()=>finish(false);save.onclick=()=>finish(true);
   dialog.addEventListener('cancel',event=>{event.preventDefault();finish(false)});actions.append(cancel,save);dialog.append(actions);document.body.append(dialog);dialog.showModal();cancel.focus();
  });
  const pending=queue.then(show,show);queue=pending.then(()=>{});return pending;
 }
 async function current(path){const response=await original(path);if(!response.ok)throw Error('Could not load the existing values. Reload and try again.');return response.json();}
 window.fetch=async(input,options={})=>{
  const request=input instanceof Request?input:null;
  const url=new URL(request?request.url:input,location.href);
  const method=(options.method||request?.method||'GET').toUpperCase();
  const write=url.origin===location.origin&&!['GET','HEAD','OPTIONS'].includes(method)&&
   (url.pathname.startsWith('/api/erp')||url.pathname==='/api/catalogue/import'||url.pathname==='/api/auth/users');
  if(write){
   let description='Save these changes to the shared ERP?',rows=[],remove=false,data;
   const raw=options.body===undefined&&request?await request.clone().text():options.body;
   try{data=JSON.parse(raw||'{}')}catch(_){}
   if(url.pathname==='/api/erp/record-action'&&data){
    remove=data.action==='delete';description=(remove?'Delete ':'Update ')+data.kind+' record '+data.id+'?'+(remove?' This removes it from current records. Its action history is retained.':'');
    if(typeof document!=='undefined'){
     const list=await current('/api/erp/records?kind='+encodeURIComponent(data.kind));const old=list.records.find(r=>r.id===data.id);
     if(!old||old.version!==data.version)throw Error('This record changed. Reload before saving.');
     rows=changes(old.data,remove?undefined:data.data);
     if(remove&&data.kind==='files')description='Permanently delete this unattached uploaded file? This cannot be undone.';
    }
   }else if(url.pathname==='/api/erp'&&data){if(typeof document!=='undefined'){const old=await current('/api/erp');rows=changes({products:old.products,txns:old.txns},{products:data.products,txns:data.txns});}}
   else if(url.pathname==='/api/erp/expenses'&&data){if(typeof document!=='undefined'){const old=await current('/api/erp/expenses');rows=changes(old.book,data.book);}}
   else if(url.pathname.includes('confirm'))description='Confirm this order and update its stock?';
   else if(url.pathname.includes('import'))description='Import these records into the shared ERP? Review the import preview before confirming.';
   else if(url.pathname.includes('image'))description='Upload this image to the shared ERP?';
   else if(url.pathname.includes('users'))description='Create this login account?';
   else if(data)rows=changes({},data);
   else description='Upload and save this file to the ERP?';
   if(!await review(description,rows,remove))throw new DOMException('Action cancelled. No changes were saved.','AbortError');
   const headers=new Headers(options.headers||request?.headers);headers.set('X-ERP-Confirmed','yes');options={...options,headers};
  }
  return original(input,options);
 };
})();
