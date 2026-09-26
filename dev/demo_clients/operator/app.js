import { api, formatTime, queryInt } from "../shared/azflow-api.js";

const room = document.querySelector("#room");
const queue = document.querySelector("#queue");
const entries = document.querySelector("#entries");
const status = document.querySelector("#status");
const policy = document.querySelector("#policy");
const calledCard = document.querySelector("#called-card");
let currentCall = null;

function setStatus(message = "", error = false) {
  status.textContent = message;
  status.classList.toggle("error", error);
}

function selectedRoom() {
  return room.options[room.selectedIndex]?.dataset.reference;
}

async function loadDiscovery() {
  const [rooms, queues] = await Promise.all([api("/rooms"), api("/queues")]);
  room.innerHTML = rooms.map(r => `<option value="${r.id}" data-reference="${r.room_reference}">${r.label}</option>`).join("");
  queue.innerHTML = queues.filter(q => q.status === "ACTIVE").map(q => `<option value="${q.id}">Queue ${q.id} · ${q.agendas.map(a => a.name).join(", ")}</option>`).join("");
  const roomId = queryInt("room");
  const queueId = queryInt("queue");
  if (roomId) room.value = String(roomId);
  if (queueId) queue.value = String(queueId);
}

function actions(entry) {
  if (entry.state === "WAITING") return `<button data-action="call" data-id="${entry.service_access_id}">Call</button><button class="secondary" data-action="suspend" data-id="${entry.service_access_id}">Suspend</button>`;
  if (entry.state === "SUSPENDED") return `<button class="secondary" data-action="restore" data-id="${entry.service_access_id}">Restore</button>`;
  if (entry.state === "CALLED") return `<button class="secondary" data-action="cancel-call" data-id="${entry.service_access_id}">Cancel</button><button data-action="admission" data-id="${entry.service_access_id}">Admit</button>`;
  if (entry.state === "ADMITTED") return `<button data-action="recall" data-id="${entry.service_access_id}">Recall</button>`;
  return "";
}

function appointment(entry, queuePolicy) {
  if (queuePolicy !== "BY_APPOINTMENT" || !entry.scheduled_at) return "—";
  const scheduled = new Date(entry.scheduled_at);
  const timing = scheduled < new Date() && entry.state === "WAITING" ? "late" : "on-time";
  return `<span class="appointment ${timing}"><span class="dot"></span>${formatTime(entry.scheduled_at)}</span>`;
}

async function refresh() {
  if (!queue.value) return;
  try {
    const data = await api(`/queues/${queue.value}/operator-list`);
    policy.textContent = data.policy;
    entries.innerHTML = data.entries.map(e => `<tr class="state-${e.state.toLowerCase()}"><td><strong>${e.public_call_code}</strong></td><td>${e.agenda.name}</td><td><span class="badge">${e.state}</span></td><td>${formatTime(e.checked_in_at)}</td><td>${appointment(e, data.policy)}</td><td><div class="row-actions">${actions(e)}</div></td></tr>`).join("");
    if (!data.entries.length) entries.innerHTML = '<tr><td colspan="6" class="muted">No patients for this queue today.</td></tr>';
    setStatus(`Queue updated at ${new Date().toLocaleTimeString()}`);
  } catch (error) { setStatus(error.message, true); }
}

async function call(path) {
  const result = await api(path, {method:"POST", body:JSON.stringify({room_reference:selectedRoom()})});
  currentCall = result;
  document.querySelector("#called-code").textContent = result.public_call_code;
  document.querySelector("#called-room").textContent = result.room_reference;
  calledCard.classList.remove("hidden");
  await refresh();
}

document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#next").addEventListener("click", async () => {
  try { await call(`/queues/${queue.value}/calls/next`); } catch (error) { setStatus(error.message, true); }
});
entries.addEventListener("click", async event => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const id = button.dataset.id;
  try {
    if (button.dataset.action === "call") await call(`/queues/${queue.value}/service-accesses/${id}/call`);
    else {
      if (button.dataset.action === "recall") {
        const result = await api(`/service-accesses/${id}/recall`, {method:"POST"});
        currentCall = result;
        document.querySelector("#called-code").textContent = result.public_call_code;
        document.querySelector("#called-room").textContent = result.room_reference;
        calledCard.classList.remove("hidden");
        await refresh();
        return;
      }
      await api(`/service-accesses/${id}/${button.dataset.action}`, {method:"POST"});
      if (["admission", "cancel-call"].includes(button.dataset.action) && currentCall?.service_access_id === Number(id)) {
        currentCall = null;
        calledCard.classList.add("hidden");
      }
      await refresh();
    }
  } catch (error) { setStatus(error.message, true); }
});
document.querySelector("#cancel-call").addEventListener("click", async () => {
  if (!currentCall) return;
  try {
    await api(`/service-accesses/${currentCall.service_access_id}/cancel-call`, {method:"POST"});
    currentCall = null; calledCard.classList.add("hidden"); await refresh();
  } catch (error) { setStatus(error.message, true); }
});
document.querySelector("#admit").addEventListener("click", async () => {
  if (!currentCall) return;
  try {
    await api(`/service-accesses/${currentCall.service_access_id}/admission`, {method:"POST"});
    currentCall = null; calledCard.classList.add("hidden"); await refresh();
  } catch (error) { setStatus(error.message, true); }
});
queue.addEventListener("change", refresh);

try { await loadDiscovery(); await refresh(); } catch (error) { setStatus(error.message, true); }

// Keep the operator queue aligned with changes made by other clients.
setInterval(refresh, 3000);
