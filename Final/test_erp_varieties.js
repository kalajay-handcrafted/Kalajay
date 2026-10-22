const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('erp/index.html','utf8'),site=fs.readFileSync('index.html','utf8'),backend=fs.readFileSync('shared_store.py','utf8'),script=html.match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)[1];
const ctx={DCLogic:class{setState(s){Object.assign(this.state,s)}},fetch:async()=>({ok:true,json:async()=>({image:'/media/products/photo.webp'})}),setTimeout,clearTimeout};
vm.createContext(ctx);vm.runInContext(script+';this.Component=Component;',ctx);
async function run(){
 assert(backend.includes('def ensure_variant_skus(db):'));
 assert(backend.includes("'variantOf':parent['product_code']") || backend.includes("variantOf=parent['product_code']"));
 assert(backend.includes('This variety is out of stock:'));
 assert(backend.includes("order_rows.append((oid,v['code']"));
 assert(site.includes('v.soldOut ? " · Out of stock" : ""'));
 assert(site.includes('selectedVariant ? !!selectedVariant.soldOut : a.soldOut'));
 assert(html.includes('Each option is a separate inventory item with its own stock.'));
 const c=new ctx.Component();c.props={};c.state.loaded=true;c.state.products=[{code:'KJ-TEST-101',name:'Test',cat:'Bags',unit:'pcs',open:10,purch:3,made:5,sold:2,dmg:1,reorder:2,cp:100,sp:200,mrp:220,gst:0,variantSequence:2,variants:[{code:'KJ-TEST-101-1',label:'Yellow',images:['/assets/yellow.jpg']},{code:'KJ-TEST-101-2',label:'Blue',images:['/assets/blue.jpg']}]}];
 c.editOptionProduct('KJ-TEST-101');let v=c.renderVals();assert.equal(v.variantRows.length,2);v.addVariant();v=c.renderVals();assert.equal(v.variantRows[2].code,'KJ-TEST-101-3');v.variantRows[2].onLabel({target:{value:'Pink'}});await c.uploadProductImage({target:{files:[{size:100,type:'image/png'}],value:''}},2);assert.equal(c.state.draft.variants[2].images[0],'/media/products/photo.webp');
 c.commit=products=>{const p=products[0];assert.equal(p.code,'KJ-TEST-101');assert.equal(p.open,10);assert.equal(p.sold,2);assert.equal(p.variants.length,3)};c.saveDraft();
 const expenseScript=fs.readFileSync('expenses.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];new vm.Script(expenseScript);
 const elements={};for(const name of ['type','date','description','category','subcategory','treatment','frequency','method','status','quantity','unitPrice','amount','party','paidBy','notes','badInvestment'])elements[name]={value:'',options:[{value:'paid',textContent:'Paid'}],type:'text',tagName:'INPUT'};
 const nodes={entryCode:{},vendorSelect:{},entryTitle:{},saveEntry:{},entryDialog:{showModal(){},close(){}}};
 const form={elements,reset(){},querySelectorAll(){return []}};
 const income={form,$:id=>nodes[id],loaded:true,busy:false,editing:null,book:{entries:[]},fileJob:0,processing:false,draftBills:[],structuredClone,entryOptions(){},dateISO:()=> '2026-10-18',renderBills(){},renderPermissions(){},admin:()=>true,crypto:{randomUUID:()=> 'income-fixture'},FormData:class{constructor(form){this.form=form}get(k){return this.form.elements[k]?.value??null}},save:async next=>{income.saved=next}};
 vm.createContext(income);for(const prefix of ['function openEntry(', 'function entryTypeLabels(', 'form.onsubmit='])vm.runInContext(expenseScript.split('\n').find(line=>line.startsWith(prefix)),income);
 vm.runInContext("openEntry(null,'income')",income);assert.equal(elements.type.value,'income');assert.equal(nodes.entryTitle.textContent,'Add income');assert.equal(elements.status.options[0].textContent,'Received');
 Object.entries({description:'Fixture sale',amount:'500',quantity:'1',unitPrice:'',status:'paid',category:'Others',subcategory:'Others',treatment:'Others',frequency:'Others',method:'UPI'}).forEach(([key,value])=>elements[key].value=value);
 await form.onsubmit({preventDefault(){}});assert.equal(income.saved.entries[0].type,'income');assert.equal(income.saved.entries[0].amount,50000);
 console.log('Variety editing, upload, stock preservation and income entry checks passed.');
}
run().catch(error=>{console.error(error);process.exitCode=1});

