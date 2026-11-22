
/* AutoClips screenshot-accurate desktop shell over the existing browser-local editor.
 * Never send media to AutoClips SaaS. All media operations delegate to app.js
 * (browser local) and saas.js (direct OAuth YouTube upload).
 */
const d = id => document.getElementById(id);
const pages = ["overview","create","approvals","production","posting","storage","billing","settings"];
const local = { page:"overview", blob:null, url:null, approved:false, wallet:null, jobs:[], period:"7d", search:"", lastSelected:"", speed:1, folder:"", onceCredits:false };
let toastTimeout = 0, refreshTimer = 0;

function notify(message) {
  if(!message)return;
  const n=d("adToast");
  n.textContent=String(message);n.hidden=false;
  clearTimeout(toastTimeout);
  toastTimeout=setTimeout(()=>{n.hidden=true;},5200);
}
function page(name) {
  if(!pages.includes(name))return;
  local.page=name;
  for(const p of pages) d("ad-"+p).hidden=(name!==p);
  document.querySelectorAll("[data-desktop-page]").forEach(b=>{
    const active=b.dataset.desktopPage===name;
    b.classList.toggle("active",active);
    if(b.closest(".ad-railnav"))b.setAttribute("aria-current",active?"page":"false");
  });
  if(name==="storage") storage();
  if(name==="approvals") refreshClip();
  if(name==="posting") updatePosting();
  if(name==="settings")updateChannels();
  if(name==="billing")updateBilling();
  window.scrollTo({top:0,behavior:"instant"});
}
document.querySelectorAll("[data-desktop-page]").forEach(b=>b.addEventListener("click",()=>page(b.dataset.desktopPage)));
d("adLogo").onclick=()=>page("overview");
d("adAvatar").onclick=()=>page("settings");
d("adRefresh").onclick=()=>{d("saasRefresh").click();refreshLocal();notify("Atualizando dados disponíveis.");};
d("adSearch").onclick=()=>{
  const query=window.prompt("Pesquisar seus arquivos e trabalhos (título ou nome):",local.search);
  if(query===null)return;
  local.search=query.trim().toLowerCase();page("production");refreshLocal();
};
document.querySelectorAll("[data-period]").forEach(button=>button.onclick=()=>{
  local.period=button.dataset.period;
  document.querySelectorAll("[data-period]").forEach(x=>x.classList.toggle("active",x===button));
  const labels={today:"Hoje","7d":"7 dias",month:"Este mês",custom:"Personalizado"};
  d("adRangeLabel").textContent=labels[local.period];
  if(local.period==="custom")notify("O filtro personalizado será aplicado às métricas quando o YouTube Analytics estiver conectado.");
});

function channelItems(){
  return Array.from(d("saasChannel").options).filter(option=>option.value).map(option=>({
    id:option.value,
    title:option.textContent.split("·")[0].trim()
  }));
}
function updateChannels(){
  const items=channelItems(),node=d("adSettingsChannels");
  node.replaceChildren();
  if(!items.length){
    const p=document.createElement("p");p.className="ad-muted";
    p.textContent="Nenhum canal conectado. Entre e selecione Encontrar canais.";
    node.append(p);
    d("adDestinationName").textContent="◉ Selecione um canal em Configurações";
    d("adConnectedLabel").textContent="Canal conectado: nenhum";
    d("adAvatarName").textContent="Minha conta";
  }else{
    for(const c of items){
      const div=document.createElement("div");div.className="ad-channel-settings";
      const b=document.createElement("b");b.textContent=c.title;
      const p=document.createElement("p");p.textContent="Conectado · Publicação com autorização Google";
      div.append(b,p);node.append(div);
    }
    const current=items.find(c=>c.id===d("saasChannel").value)||items[0];
    d("adDestinationName").textContent="◉ "+current.title;
    d("adConnectedLabel").textContent="Canal conectado: "+current.title;
    d("adAvatarName").textContent=current.title;
    d("adAvatarInitial").textContent=current.title.slice(0,1).toUpperCase();
  }
  d("adChannelTotal").textContent=items.length?String(items.length):"—";
}
function updateWallet(wallet,jobs){
  local.wallet=wallet||{};
  if(Array.isArray(jobs))local.jobs=jobs;
  const available=Math.max(0,Number(wallet?.available)||0);
  const reserved=Math.max(0,Number(wallet?.reserved)||0);
  const purchased=Math.max(0,Number(wallet?.total_purchased)||0);
  const last=Number(d("adCreditBalance").dataset.prev);
  d("adCreditBalance").textContent=available.toLocaleString("pt-BR");
  d("adCreditBalance").dataset.prev=String(available);
  d("adReservedBalance").textContent=reserved.toLocaleString("pt-BR")+" reservados · "+purchased.toLocaleString("pt-BR")+" comprados";
  d("adPublishedTotal").textContent=String(local.jobs.filter(job=>job.status==="published").length);
  if(Number.isFinite(last)&&last>0&&available===0&&!local.onceCredits)creditPopup();
  updatePosting();
}
window.addEventListener("autoclips:wallet",event=>updateWallet(event.detail.wallet,event.detail.jobs||[]));
window.addEventListener("autoclips:credits-exhausted",creditPopup);
window.addEventListener("autoclips:feedback",event=>{
  const msg=String(event.detail?.message||"");
  d("adAccountResponse").textContent=msg;
  if(/crédito|pagamento|publique|publica|erro|conect|login/i.test(msg))notify(msg);
  if(/créditos insuficientes|saldo insuficiente/i.test(msg))creditPopup();
});
function creditPopup(){
  local.onceCredits=true;
  d("adCreditPopup").hidden=false;
  d("adCreditBuy").focus();
}
function closeCredit(){d("adCreditPopup").hidden=true;}
d("adCreditClose").onclick=closeCredit;
d("adCreditBuy").onclick=()=>{closeCredit();page("billing");};
d("adCreditPopup").onclick=event=>{if(event.target===d("adCreditPopup"))closeCredit();};

function price(n){return (n*.15).toLocaleString("pt-BR",{style:"currency",currency:"BRL"});}
function updateBilling(){
  const n=Math.max(100,Number(d("adCustomCredits").value)||100);
  d("adCustomPrice").textContent=price(n);
}
d("adCustomCredits").oninput=updateBilling;
function buy(n){
  const amount=Number(n);
  if(!Number.isSafeInteger(amount)||amount<100||amount>100000){notify("Escolha entre 100 e 100.000 créditos.");return;}
  if(!d("saasOrg").value){notify("Entre e crie um espaço de trabalho antes de comprar créditos.");page("settings");return;}
  d("saasBuyCount").value=String(amount);
  d("saasCheckout").click();
}
document.querySelectorAll("[data-ad-buy]").forEach(button=>button.onclick=()=>buy(button.dataset.adBuy));
d("adBuyCustom").onclick=()=>buy(d("adCustomCredits").value);

function readLocalFileNames(){
  return Array.from(document.querySelectorAll("#files button.file")).map(el=>({
    name:(el.textContent||"").replace(/\s+/g," ").trim(),
    active:el.classList.contains("active"), el
  }));
}
function selectedLocal(){
  const files=readLocalFileNames();
  return files.find(f=>f.active)||files[0]||null;
}
function refreshLocal(){
  const files=readLocalFileNames(), selected=selectedLocal();
  const filter=local.search;
  const list=d("adProductionList");list.replaceChildren();
  if(!files.length){
    const node=document.createElement("div");node.className="ad-card ad-muted";node.textContent="Nenhum arquivo selecionado. Adicione vídeos em Criar cortes.";
    list.append(node);
  }else{
    files.filter(f=>!filter||f.name.toLowerCase().includes(filter)).forEach((item,i)=>{
      const row=document.createElement("button");row.className="ad-list-row";row.type="button";
      const content=document.createElement("div");
      const line=document.createElement("b");line.textContent="◈ "+(item.name.slice(0,120)||"Vídeo autorizado");
      const desc=document.createElement("p");desc.textContent="Processamento local · "+(item.active?"Selecionado para edição":"Aguardando seleção");
      content.append(line,desc);
      const status=document.createElement("span");status.className="ad-status";status.textContent=item.active?"Selecionado":"Na biblioteca";
      row.append(content,status);
      row.onclick=()=>{item.el.click();page("create");showEditor();};
      list.append(row);
    });
  }
  d("adProductionCaption").textContent=files.length?files.length+" arquivo(s) na biblioteca local":"Nenhum vídeo em produção";
  d("adProductionCount").hidden=!files.length;
  d("adProductionCount").textContent=String(files.length);
  if(selected){
    const name=selected.name.slice(0,130);
    d("adCreateStatusTitle").textContent="Original selecionado";
    d("adCreateStatus").textContent=name;
    d("adCreateStatus").title=name;
    d("adResume").textContent="Retomar edição";
    if(!local.lastSelected ||local.lastSelected!==name){
      local.lastSelected=name;
      showEditor();
      if(local.page==="create")notify("Vídeo carregado para edição local.");
    }
  }
  const status=d("status").textContent;
  if(status&&!status.startsWith("Selecione"))d("adExportFeedback").textContent=status;
  d("adCreationProgress").style.width=String(Math.min(100,Number(d("progress").value)||0))+"%";
  refreshClip();
}
function showEditor(){
  d("adEditor").hidden=false;
  if(d("source").parentElement!==d("adSourceMount"))d("adSourceMount").append(d("source"));
  if(d("composition").parentElement!==d("adCompositionMount"))d("adCompositionMount").append(d("composition"));
  const vid=d("source");
  if(vid.src && d("editing").disabled===false){
    d("adCutStart").value=d("start").value;
    d("adCutEnd").value=d("end").value;
    d("adHookWhite").value=d("hookWhite").value;
    d("adHookAccent").value=d("hookRed").value;
  }
}
d("adChooseFile").onclick=()=>d("choose").click();
d("adChooseFolder").onclick=()=>d("folder").click();
d("adChangeFolder").onclick=()=>d("folder").click();
d("adGenerate").onclick=()=>{
  if(!d("adLinkRights").checked){notify("Confirme que você tem autorização para usar este conteúdo.");return;}
  const value=d("adVideoLink").value.trim();
  if(value){
    let url;
    try{url=new URL(value);}catch{notify("Insira uma URL válida ou escolha um vídeo do computador.");return;}
    if(url.protocol!=="https:"){notify("Use URL HTTPS autorizada.");return;}
    if(/(^|\.)youtube\.com$|(^|\.)youtu\.be$/i.test(url.hostname)){
      notify("O YouTube não oferece download de originais pela API. Escolha o arquivo original autorizado no seu computador.");
      d("choose").click();return;
    }
    d("sourceUrl").value=value;
    d("downloadRights").checked=true;
    notify("Selecione onde salvar o vídeo autorizado no seu computador.");
    d("downloadSource").click();return;
  }
  if(selectedLocal()){showEditor();return;}
  d("choose").click();
};
d("adResume").onclick=()=>{
  if(!selectedLocal()){d("choose").click();return;}
  showEditor();d("adEditor").scrollIntoView({block:"start",behavior:"smooth"});
};
d("adCutStart").addEventListener("input",()=>{d("start").value=d("adCutStart").value;d("start").dispatchEvent(new Event("input",{bubbles:true}));});
d("adCutEnd").addEventListener("input",()=>{d("end").value=d("adCutEnd").value;d("end").dispatchEvent(new Event("input",{bubbles:true}));});
d("adHookWhite").addEventListener("input",()=>{d("hookWhite").value=d("adHookWhite").value;d("hookWhite").dispatchEvent(new Event("input",{bubbles:true}));});
d("adHookAccent").addEventListener("input",()=>{d("hookRed").value=d("adHookAccent").value;d("hookRed").dispatchEvent(new Event("input",{bubbles:true}));});
d("adEditRights").onchange=()=>{d("rights").checked=d("adEditRights").checked;};
d("adExport").onclick=()=>{
  d("rights").checked=d("adEditRights").checked;
  if(!selectedLocal()){notify("Selecione um vídeo antes de gerar cortes.");return;}
  notify("Gerando corte no seu navegador. Mantenha esta aba aberta.");
  d("export").click();
};
d("adPause").onclick=()=>d("pause").click();
d("adSave").onclick=()=>d("save").click();

function refreshClip(){
  const output=window.autoclipsLocalGetExport?.();
  if(output?.blob&&local.blob!==output.blob){
    if(local.url)URL.revokeObjectURL(local.url);
    local.blob=output.blob;local.url=URL.createObjectURL(output.blob);
    local.approved=false;
    d("adClipVideo").src=local.url;
    d("adClipVideo").hidden=false;
    d("adClipEmpty").hidden=true;
    d("adApprovalNotice").textContent=output.name+" · Prévia local, sem upload ao AutoClips.";
    d("adCreateStatusTitle").textContent="Corte gerado com sucesso";
    d("adCreateStatus").textContent=output.name+" — pronto para aprovação";
    d("adCreationProgress").style.width="100%";
  }
  if(!output?.blob&&local.blob){
    local.blob=null;if(local.url)URL.revokeObjectURL(local.url);local.url=null;
    d("adClipVideo").pause();d("adClipVideo").removeAttribute("src");d("adClipVideo").hidden=true;d("adClipEmpty").hidden=false;
    d("adApprovalNotice").textContent="Gere um corte local antes de aprovar.";
  }
  const count=local.blob?1:0;
  d("adApprovalCount").hidden=!count;
  d("adApprovalCount").textContent=String(count);
  d("adApprovalPill").textContent=count+" vídeo"+(count===1?"":"s");
}
d("adSpeed").onclick=()=>{
  const v=d("adClipVideo");local.speed=local.speed===1?1.5:local.speed===1.5?2:1;
  v.playbackRate=local.speed;d("adSpeed").textContent=local.speed+"×";
};
d("adClipPrev").onclick=()=>notify("Este é o corte atual. Novos cortes podem ser criados no editor.");
d("adClipNext").onclick=()=>notify("Este é o corte atual. Novos cortes podem ser criados no editor.");
d("adBack5").onclick=()=>seek(-5);d("adBack1").onclick=()=>seek(-1);
d("adFwd1").onclick=()=>seek(1);d("adFwd5").onclick=()=>seek(5);
function seek(seconds){
  const vid=d("adClipVideo");if(!vid.src||!Number.isFinite(vid.duration))return;
  vid.currentTime=Math.min(vid.duration,Math.max(0,vid.currentTime+seconds));
}
d("adClipSeek").oninput=()=>{
  const vid=d("adClipVideo");if(vid.src&&Number.isFinite(vid.duration)&&vid.duration>0)vid.currentTime=vid.duration*Number(d("adClipSeek").value)/100;
};
d("adClipVideo").ontimeupdate=()=>{
  const video=d("adClipVideo");if(Number.isFinite(video.duration)&&video.duration>0)d("adClipSeek").value=String(100*video.currentTime/video.duration);
};
d("adApproveAll").onclick=()=>{if(!local.blob){notify("Nenhum corte pendente.");return;}approvalDialog();};
d("adApprove").onclick=approvalDialog;
function approvalDialog(){
  if(!local.blob){notify("Gere um corte local para aprovar.");page("create");return;}
  if(local.wallet&&Number(local.wallet.available)<=0){creditPopup();return;}
  d("adPublishTitle").value=(d("saasTitle").value||local.blob?.name||"AutoClips Short").slice(0,100);
  d("adApprovalDialog").hidden=false;d("adRightsApproved").checked=false;
  d("adApprovalResult").textContent="";
}
d("adApprovalCancel").onclick=()=>{d("adApprovalDialog").hidden=true;};
d("adApprovalConfirm").onclick=()=>{
  if(!d("adRightsApproved").checked){notify("Confirme a autorização de direitos e a publicação privada.");return;}
  d("saasApprovalCheck").checked=true;
  d("saasTitle").value=d("adPublishTitle").value;
  d("adApprovalDialog").hidden=true;
  d("saasPrepare").click();
  notify("Preparando a publicação privada. Após confirmar a reserva, conclua o envio na área de postagem.");
};
d("adComment").onclick=()=>{
  if(!local.blob){notify("Nenhum corte disponível para comentar.");return;}
  const comment=window.prompt("Qual ajuste você deseja realizar neste corte?");
  if(comment&&comment.trim()){page("create");showEditor();notify("Ajuste solicitado: "+comment.trim().slice(0,110));}
};
d("adReject").onclick=()=>{
  if(!local.blob){notify("Nenhum corte disponível para rejeitar.");return;}
  if(window.confirm("Descartar esta prévia local? O arquivo original não será apagado.")){
    page("create");showEditor();notify("Prévia rejeitada. Ajuste os parâmetros e gere um novo corte.");
  }
};

function updatePosting(){
  const channels=channelItems();
  const tilebox=d("adChannelTiles"),jobs=local.jobs||[];
  tilebox.replaceChildren();
  if(!channels.length){
    const box=document.createElement("div");box.className="ad-channel-tile";
    box.innerHTML='<span class="folder">▣</span><span><b>Nenhum canal conectado</b><small>Conecte em Configurações</small></span>';
    box.onclick=()=>page("settings");tilebox.append(box);
  }else{
    for(const channel of channels){
      const related=jobs.filter(j=>j.channel_id===channel.id&&j.status!=="published");
      const el=document.createElement("button");el.type="button";el.className="ad-channel-tile";
      const icon=document.createElement("span");icon.className="folder";icon.textContent="▣";
      const text=document.createElement("span");
      const title=document.createElement("b");title.textContent=channel.title;
      const small=document.createElement("small");small.textContent=related.length+" vídeo(s)";
      text.append(title,small);el.append(icon,text);tilebox.append(el);
      el.onclick=()=>{d("adPostingList").scrollIntoView({behavior:"smooth"});};
    }
  }
  const list=d("adPostingList");list.replaceChildren();
  const pending=jobs.filter(j=>j.status!=="published"&&j.status!=="cancelled");
  if(!pending.length){
    const msg=document.createElement("div");msg.className="ad-muted";
    msg.textContent="Não há publicações pendentes nesta conta.";
    list.append(msg);
  }else{
    for(const job of pending){
      const row=document.createElement("div");row.className="ad-list-row";
      const left=document.createElement("div");
      const title=document.createElement("b");title.textContent=job.title||"Short sem título";
      const detail=document.createElement("p");detail.textContent="YouTube · "+(job.status||"Pendente");
      left.append(title,detail);
      const status=document.createElement("span");status.className="ad-status";status.textContent=job.status||"Na fila";
      row.append(left,status);list.append(row);
    }
  }
  d("adPostingCaption").textContent=pending.length+" vídeo(s) na fila · Envio direto ao YouTube com confirmação do cliente.";
  d("adPostingCount").hidden=!pending.length;d("adPostingCount").textContent=String(pending.length);
}
d("adPostAll").onclick=updatePosting;

async function storage(){
  try{
    if(!navigator.storage?.estimate)return;
    const estimate=await navigator.storage.estimate();
    const used=Number(estimate.usage||0),quota=Number(estimate.quota||0);
    if(!quota)return;
    const gig=n=>(n/1073741824).toFixed(1).replace(".",",")+" GB";
    d("adQuotaAvailable").textContent=gig(Math.max(0,quota-used))+" de cota do navegador disponíveis";
    d("adQuotaTotal").textContent=gig(quota)+" de cota estimada";
    d("adQuotaBar").style.width=Math.round(100*used/quota)+"%";
  }catch{d("adQuotaAvailable").textContent="Cota indisponível neste navegador";}
}
d("adFindChannels").onclick=()=>d("saasConnect").click();
d("adCreateChannel").onclick=()=>{
  const name=window.prompt("Nome do novo espaço de trabalho:");
  if(!name||!name.trim())return;
  d("saasOrgName").value=name.trim();
  d("saasCreateOrg").click();
};
d("adLogout").onclick=()=>{d("saasLogout").click();updateChannels();notify("Sessão encerrada.");};
d("adReviewMobile").onclick=()=>{window.location.assign("./review.html");};
d("adAdvanced").onclick=()=>{
  const api=d("saasApi").value||"Não configurada";
  const auth=d("saasSupabase").value||"Não configurado";
  d("adAccountResponse").textContent="API pública: "+api+" · Autenticação: "+auth+". Configure as integrações no serviço Railway/Vercel.";
};
function syncLogin(){
  d("saasEmail").value=d("adLoginEmail").value.trim();
  d("saasPassword").value=d("adLoginPass").value;
}
d("adSignin").onclick=()=>{syncLogin();d("saasLogin").click();};
d("adSignup").onclick=()=>{syncLogin();d("saasSignup").click();};
d("adApprovalDialog").onclick=event=>{if(event.target===d("adApprovalDialog"))d("adApprovalDialog").hidden=true;};
document.addEventListener("keydown",event=>{
  if(event.key==="Escape"){d("adApprovalDialog").hidden=true;closeCredit();}
});
const oldFolder=d("folder");
oldFolder.addEventListener("click",()=>{
  d("adFolderName").textContent="Pasta selecionada pelo navegador (se o acesso for concedido)";
});
const oldFiles=d("files");
new MutationObserver(()=>refreshLocal()).observe(oldFiles,{childList:true,subtree:true,attributes:true,attributeFilter:["class"]});
new MutationObserver(()=>updateChannels()).observe(d("saasChannel"),{childList:true,subtree:true});
d("source").addEventListener("loadedmetadata",()=>{showEditor();page("create");refreshLocal();});
d("status").addEventListener("DOMSubtreeModified",()=>{d("adExportFeedback").textContent=d("status").textContent;});
setInterval(()=>{if(!document.hidden){refreshClip();d("adCreationProgress").style.width=String(Math.min(100,Number(d("progress").value)||0))+"%";}},1250);
window.addEventListener("beforeunload",()=>{if(local.url)URL.revokeObjectURL(local.url);});
refreshLocal();updateChannels();updateBilling();page("overview");
