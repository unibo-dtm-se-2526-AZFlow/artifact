import { queryInt, websocket } from "../shared/azflow-api.js";
const monitor=queryInt("monitor",1), connection=document.querySelector("#connection"), empty=document.querySelector("#empty"), panel=document.querySelector("#call");
function show(call){if(!call)return;empty.classList.add("hidden");panel.classList.remove("hidden");document.querySelector("#code").textContent=call.public_call_code;document.querySelector("#room").textContent=call.room_label;document.querySelector("#agenda").textContent=call.agenda.name;}
function connect(){const ws=websocket(`/ws/room-monitors/${monitor}`);ws.onopen=()=>connection.textContent=`Monitor ${monitor} · Live`;ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==="snapshot")show(m.calls[0]);if(m.type==="call")show(m.call);};ws.onclose=e=>{connection.textContent=e.code===4004?`Unknown monitor ${monitor}`:"Disconnected · retrying…";if(e.code!==4004)setTimeout(connect,1500);};ws.onerror=()=>ws.close();}
connect();
