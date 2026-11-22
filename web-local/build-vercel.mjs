/* Static Vercel build. Public configuration ONLY; never bundle secret keys. */
import fs from "node:fs";
import path from "node:path";
const root=process.cwd(),dir=path.join(root,"dist");
fs.mkdirSync(dir,{recursive:true});
const publicAssets=[
  "index.html","studio.css","studio-ui.js","desktop-ui.css","desktop-ui.js","app.js","saas.js",
  "render.worker.js","captions.js","transcribe.js","transcribe.worker.js"
];
for(const name of publicAssets){
  if(!fs.existsSync(path.join(root,name)))throw Error("Missing required frontend asset: "+name);
  fs.copyFileSync(path.join(root,name),path.join(dir,name));
}
const cfg={
  apiUrl:process.env.API_URL||"",
  supabaseUrl:process.env.SUPABASE_URL||"",
  supabasePublishableKey:process.env.SUPABASE_PUBLISHABLE_KEY||"",
  googleClientId:process.env.GOOGLE_CLIENT_ID||""
};
for(const key of ["apiUrl","supabaseUrl"]){
  if(cfg[key]&&!cfg[key].startsWith("https://"))throw Error(key+" must use HTTPS");
}
if(cfg.supabasePublishableKey.startsWith("sb_secret_")||cfg.supabasePublishableKey.startsWith("eyJ")){
  throw Error("Never publish secret/service-role keys in a frontend build");
}
if(cfg.googleClientId&&!cfg.googleClientId.endsWith(".apps.googleusercontent.com")){
  throw Error("Invalid Google Web OAuth Client ID");
}
fs.writeFileSync(path.join(dir,"saas-config.json"),JSON.stringify(cfg,null,2));
console.log("AutoClips Studio build: 11 static assets; mode="+
  (Object.values(cfg).every(Boolean)?"configured":"preview-only"));
