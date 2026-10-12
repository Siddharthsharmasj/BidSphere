(function(){
  function fmtTime(total){
    total=Math.max(0,Math.floor(total));
    const d=Math.floor(total/86400); total%=86400;
    const h=Math.floor(total/3600); total%=3600;
    const m=Math.floor(total/60); const s=total%60;
    if(d) return `${d}d ${String(h).padStart(2,'0')}h`;
    if(h) return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  function tick(){
    document.querySelectorAll('[data-end]').forEach(el=>{
      const end=new Date(el.dataset.end).getTime();
      const sec=(end-Date.now())/1000;
      const prefix=el.dataset.prefix||'';
      if(Number.isNaN(end)) return;
      if(sec<=0){el.textContent=el.dataset.status==='upcoming'?'Started':(el.dataset.status==='cancelled'?'Cancelled':'Ended');return;}
      el.textContent=prefix+fmtTime(sec);
    });
  }
  setInterval(tick,1000); tick();

  const statusUrl=window.AUCTION_STATUS_URL;
  const bidsUrl=window.AUCTION_BIDS_URL;
  if(statusUrl){
    async function refreshStatus(){
      try{
        const res=await fetch(statusUrl,{headers:{'X-Requested-With':'XMLHttpRequest'},cache:'no-store'});
        if(!res.ok) return;
        const data=await res.json();
        const price=document.getElementById('current-price');
        const next=document.getElementById('next-bid');
        const count=document.getElementById('bid-count');
        const leader=document.getElementById('leader');
        const cd=document.getElementById('detail-countdown');
        if(price) price.textContent=data.current_price;
        if(next) next.textContent=data.next_bid;
        if(count) count.textContent=data.bid_count;
        if(leader) leader.textContent=data.current_bidder ? `Leading: ${data.current_bidder}` : 'No bids yet';
        if(cd){
          if(data.status==='ended' || data.status==='cancelled'){
            cd.dataset.end=new Date().toISOString();
          }else{
            const countdownSeconds=data.status==='upcoming'?data.start_remaining_seconds:data.remaining_seconds;
            if(Number.isFinite(countdownSeconds)){
              cd.dataset.end=new Date(Date.now()+Math.max(0,countdownSeconds)*1000).toISOString();
            }
          }
          cd.dataset.status=data.status;
        }
        if(data.status==='ended' || data.status==='cancelled') window.setTimeout(()=>window.location.reload(),5000);
      }catch(e){/* polling is best-effort */}
    }
    refreshStatus(); setInterval(refreshStatus,2000);
  }
  if(bidsUrl){
    async function refreshBids(){
      try{
        const res=await fetch(bidsUrl,{cache:'no-store'}); if(!res.ok) return; const data=await res.json();
        const box=document.getElementById('bid-history'); if(!box) return;
        box.innerHTML=data.results.length?data.results.map(b=>`<div class="list-row"><span><b>${escapeHtml(b.bidder)}</b><small>Maximum updated · ${new Date(b.created_at).toLocaleString()}</small></span><strong title="Displayed price after this maximum was submitted">${escapeHtml(b.price_after || b.amount)}</strong></div>`).join(''):'<div class="empty">No bids yet.</div>';
      }catch(e){}
    }
    refreshBids(); setInterval(refreshBids,3000);
  }
  function escapeHtml(v){return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
})();
