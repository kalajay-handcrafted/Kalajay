const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(__dirname+'/index.html','utf8'),script=html.match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)[1],css=fs.readFileSync(__dirname+'/assets/mobile-header.css','utf8');
const storage=new Map;
function load(path){const context={URL,URLSearchParams,document:{referrer:'https://www.kalajay.in/shop'},DCLogic:class{},window:{location:{pathname:path,search:'',origin:'https://www.kalajay.in'},sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},KALAJAY_DATA:{collections:[],products:[],soldOut:[],prices:{}}}};vm.runInNewContext(script+';this.Component=Component;',context);return new context.Component();}
assert.equal(load('/').state.intro,true);assert.equal(load('/shop').state.intro,false);assert.equal(load('/').state.intro,false);
storage.clear();assert.equal(load('/gifting-enquiry').state.intro,false);assert.equal(load('/').state.intro,false);
assert(html.includes('setTimeout(finish, 2380)'));assert(html.includes('const duration = 320;'));
assert(html.includes('href="/gifting-enquiry#gifting-contact"'));assert(html.includes('href="/gifting-enquiry"'));
assert(html.includes('href="/api/catalogue.pdf"'));assert(html.includes('wa.me/919740540847?text='));
for(const email of ['support@kalajay.in','kalajay.handcrafted@gmail.com'])assert(html.includes('href="mailto:'+email+'"'));
assert(css.includes('@keyframes kj-announcement-scroll'));assert(css.includes('translateX(-50%)'));assert(css.includes('min-width:100vw'));assert(css.includes('@media(prefers-reduced-motion:reduce)'));
console.log('PASS: intro runs once per tab, internal navigation skips it, gifting stays on its own page, catalog/contact links and announcement motion are configured.');
