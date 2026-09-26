import { queryInt, websocket } from "../shared/azflow-api.js";
const monitor=queryInt("monitor",1), connection=document.querySelector("#connection"), container=document.querySelector("#calls");let calls=[];
function key(c){return `${c.public_call_code}|${c.room_reference}|${c.occurred_at}`;}
function render(){if(!calls.length){container.innerHTML='<div class="empty">Waiting for calls</div>';return;}container.innerHTML=calls.slice(0,10).map(c=>`<article class="call"><div class="code">${c.public_call_code}</div><div class="room">${c.room_label}</div><div class="agenda">${c.agenda.name}</div></article>`).join("");}
function add(call){calls=[call,...calls.filter(c=>key(c)!==key(call))].slice(0,10);render();}
function connect(){const ws=websocket(`/ws/waiting-room-monitors/${monitor}`);ws.onopen=()=>connection.textContent=`Monitor ${monitor} · Live`;ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==="snapshot"){calls=m.calls;render();}if(m.type==="call")add(m.call);};ws.onclose=e=>{connection.textContent=e.code===4004?`Unknown monitor ${monitor}`:"Disconnected · retrying…";if(e.code!==4004)setTimeout(connect,1500);};ws.onerror=()=>ws.close();}
render();connect();
