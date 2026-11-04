/* Confirmation applies to every ERP save, upload, import, edit and deletion. */
(()=>{
 const original=window.fetch.bind(window);
 window.fetch=async(input,options={})=>{
  const request=input instanceof Request?input:null;
  const url=new URL(request?request.url:input,location.href);
  const method=(options.method||request?.method||'GET').toUpperCase();
  const write=url.origin===location.origin && !['GET','HEAD','OPTIONS'].includes(method) &&
   (url.pathname.startsWith('/api/erp') || url.pathname==='/api/catalogue/import' || url.pathname==='/api/auth/users');
  if(write){
   let description='Save these changes to the shared ERP?';
   try{const data=JSON.parse(options.body||'{}');
    if(url.pathname==='/api/erp/record-action')description=(data.action==='delete'?'Delete':'Update')+' '+data.kind+' record '+data.id+'?'+(data.action==='delete'?' This removes it from current records and retains its action history.':'');
    else if(url.pathname.includes('confirm'))description='Confirm this order and update its stock?';
    else if(url.pathname.includes('import'))description='Import these records into the shared ERP?';
    else if(url.pathname.includes('image'))description='Upload this image to the shared ERP?';
    else if(url.pathname.includes('users'))description='Create this login account?';
   }catch(_){description=url.pathname.includes('import')?'Import these records into the shared ERP?':'Upload and save this file to the ERP?';}
   if(!window.confirm(description))throw new DOMException('Action cancelled. No changes were saved.','AbortError');
   const headers=new Headers(options.headers||request?.headers);headers.set('X-ERP-Confirmed','yes');
   options={...options,headers};
  }
  return original(input,options);
 };
})();
