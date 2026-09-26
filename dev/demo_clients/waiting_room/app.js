import { formatTime, queryInt, websocket } from "../shared/azflow-api.js";

const monitor = queryInt("monitor", 1);
const connection = document.querySelector("#connection");
const container = document.querySelector("#calls");
const label = document.querySelector("#waiting-room-label");
let calls = [];

function appointment(call) {
  if (!call.scheduled_at) return "";
  return `<span class="appointment">${formatTime(call.scheduled_at)}</span>`;
}

function render() {
  if (!calls.length) {
    container.innerHTML = '<div class="empty">Waiting for calls</div>';
    return;
  }
  container.innerHTML = calls.slice(0, 10).map(call => `
    <article class="call ${call.state === "CALLED" ? "active" : "inactive"}">
      <div class="ticket"><div class="code">${call.public_call_code}</div>${appointment(call)}</div>
      <div class="room">${call.room_label}</div>
      <div class="called-at">${formatTime(call.occurred_at)}</div>
    </article>`).join("");
}

function update(call) {
  calls = [call, ...calls.filter(item => item.public_call_code !== call.public_call_code)]
    .sort((a, b) => new Date(b.occurred_at) - new Date(a.occurred_at))
    .slice(0, 10);
  render();
}

function connect() {
  const ws = websocket(`/ws/waiting-room-monitors/${monitor}`);
  ws.onopen = () => connection.textContent = `Monitor ${monitor} · Live`;
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === "snapshot") {
      if (message.label) label.textContent = message.label;
      calls = message.calls;
      render();
    }
    if (message.type === "call" || message.type === "state") update(message.call);
  };
  ws.onclose = event => {
    connection.textContent = event.code === 4004
      ? `Unknown monitor ${monitor}`
      : "Disconnected · retrying…";
    if (event.code !== 4004) setTimeout(connect, 1500);
  };
  ws.onerror = () => ws.close();
}

render();
connect();
