/* Studio frontend: navigation and billing in the original visual language. */
const ui = id => document.getElementById(id);
const viewNames = ["studio","library","channels","history","payments"];
let activeView="studio",previousAvailable=null,previousFocus=null,toastTimer=null;
function showView(view){
  if(!viewNames.includes(view))return;
  activeView=view;
  for(const name of viewNames)ui("view-"+name).hidden = name!==view;
  document.querySelectorAll("[data-view]").forEach(button=>{
    const selected=button.dataset.view===view;
    button.classList.toggle("active",selected);
    button.setAttribute("aria-current",selected?"page":"false");
  });
  ui("studioRightbar").dataset.hidden=String(view!=="studio");
  ui("studioWrap").classList.toggle("wide-mode",view!=="studio");
  window.scrollTo({top:0});
}
function toast(msg){
  if(!msg)return;
  const node=ui("studioToast");
  node.textContent=msg;node.classList.add("visible");
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.classList.remove("visible"),4500);
}
function showCreditModal(){
  const modal=ui("creditModal");
  if(!modal.hidden)return;
  previousFocus=document.activeElement;modal.hidden=false;ui("creditModalBuy").focus();
}
function closeCreditModal(){ui("creditModal").hidden=true;if(previousFocus?.isConnected)previousFocus.focus();}
function walletChanged(data){
  const wallet=data.wallet||{},jobs=data.jobs||[];
  const available=Number(wallet.available||0),reserved=Number(wallet.reserved||0),total=Number(wallet.total_purchased||0);
  const fmt=n=>n.toLocaleString("pt-BR");
  for(const id of ["sideCredits","paymentsCredits","historyAvailable"])ui(id).textContent=fmt(available);
  ui("topCredits").textContent="◈ "+fmt(available)+" créditos";
  ui("historyReserved").textContent=fmt(reserved);
  ui("historyPublished").textContent=fmt(jobs.filter(j=>j.status==="published").length);
  ui("creditProgress").style.width=(total?Math.min(100,100*available/total):0)+"%";
  ui("topCredits").style.borderColor=available===0?"#b4586d":"#3c4151";
  if(previousAvailable!==null&&previousAvailable>0&&available===0)showCreditModal();
  previousAvailable=available;
}
const fileButtons=()=>Array.from(document.querySelectorAll("#files .file"));
function updateLocal(){
  const selected=document.querySelector("#files .file.active");
  const ready=Boolean(selected&&ui("source").videoWidth);
  ui("emptyFeed").classList.toggle("hidden",ready);
  const count=fileButtons().length;
  ui("localCounter").textContent=count?count+" vídeo(s) na sua biblioteca":"Nenhum vídeo selecionado.";
  ui("feedTitle").textContent=selected?.firstChild?.textContent?.trim().slice(0,75)||"AutoClips Studio";
  ui("feedMeta").textContent=selected?"Corte local · "+ui("metadata").textContent:"Nenhum vídeo enviado ao servidor";
}
function navigateFile(step){
  const files=fileButtons();
  if(!files.length){showView("library");toast("Escolha um vídeo na biblioteca.");return;}
  const index=Math.max(0,files.findIndex(x=>x.classList.contains("active")));
  files[(index+step+files.length)%files.length].click();showView("studio");
}
document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>showView(b.dataset.view)));
document.querySelectorAll("[data-open-payments]").forEach(b=>b.addEventListener("click",()=>showView("payments")));
ui("topAccount").onclick=()=>showView("channels");
ui("prev").onclick=()=>navigateFile(-1);
ui("next").onclick=()=>navigateFile(1);
ui("studioAdjust").onclick=()=>{
  if(!fileButtons().length){showView("library");toast("Selecione um vídeo.");return;}
  showView("studio");ui("start").scrollIntoView({behavior:"smooth",block:"center"});ui("start").focus();
  toast("Ajuste intervalo e gancho à direita e gere um novo corte.");
};
ui("studioApprove").onclick=()=>{
  if(!window.autoclipsLocalGetExport?.()){toast("Gere e revise um corte primeiro.");return;}
  if(previousAvailable!==null&&previousAvailable<=0){showCreditModal();return;}
  if(!ui("saasApprovalCheck").checked){ui("saasApprovalCheck").focus();toast("Confirme os direitos e a publicação privada à direita.");return;}
  ui("saasPrepare").click();toast("Após reservar o crédito, confirme o envio direto ao YouTube.");
};
ui("creditModalDismiss").onclick=closeCreditModal;
ui("creditModalBuy").onclick=()=>{closeCreditModal();showView("payments");};
ui("creditModal").onclick=e=>{if(e.target===ui("creditModal"))closeCreditModal();};
window.addEventListener("keydown",e=>{if(e.key==="Escape"&&!ui("creditModal").hidden)closeCreditModal();});
document.querySelectorAll("[data-buy-credits]").forEach(button=>button.onclick=()=>{
  ui("saasBuyCount").value=button.dataset.buyCredits;
  if(!ui("saasOrg").value){showView("channels");toast("Entre na sua conta para comprar créditos.");return;}
  ui("saasCheckout").click();
});
document.querySelectorAll("[data-refresh]").forEach(b=>b.onclick=()=>ui("saasRefresh").click());
window.addEventListener("autoclips:wallet",e=>walletChanged(e.detail));
window.addEventListener("autoclips:credits-exhausted",showCreditModal);
window.addEventListener("autoclips:feedback",e=>{
  const message=e.detail?.message||"";
  if(activeView!=="channels"||/erro|crédito|pagamento|saldo|publica/i.test(message))toast(message);
});
ui("source").addEventListener("loadedmetadata",()=>{updateLocal();showView("studio");});
ui("files").addEventListener("click",e=>{if(e.target.closest(".file"))setTimeout(updateLocal,100);});
new MutationObserver(updateLocal).observe(ui("files"),{childList:true,subtree:true,attributes:true,attributeFilter:["class"]});
new MutationObserver(updateLocal).observe(ui("metadata"),{childList:true,characterData:true,subtree:true});
updateLocal();showView("studio");
