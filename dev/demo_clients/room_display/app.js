import { queryInt, websocket } from "../shared/azflow-api.js";

const monitor = queryInt("id", 1);
const connection = document.querySelector("#connection");
const panel = document.querySelector("#call");
const code = document.querySelector("#code");
const room = document.querySelector("#room");
const agenda = document.querySelector("#agenda");

function clear() {
  panel.classList.add("idle");
  code.textContent = "—";
  room.textContent = "";
  agenda.textContent = "";
}

function show(call) {
  if (!call || call.state !== "CALLED") {
    clear();
    return;
  }
  panel.classList.remove("idle");
  code.textContent = call.public_call_code;
  room.textContent = call.room_label;
  agenda.textContent = call.agenda?.name ?? "";
}

function connect() {
  const ws = websocket(`/ws/room-monitors/${monitor}`);
  ws.onopen = () => connection.textContent = `Monitor ${monitor} · Live`;
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === "snapshot") show(message.calls[0]);
    if (message.type === "call" || message.type === "state") show(message.call);
  };
  ws.onclose = event => {
    clear();
    connection.textContent = event.code === 4004
      ? `Unknown monitor ${monitor}`
      : "Disconnected · retrying…";
    if (event.code !== 4004) setTimeout(connect, 1500);
  };
  ws.onerror = () => ws.close();
}

clear();
connect();
