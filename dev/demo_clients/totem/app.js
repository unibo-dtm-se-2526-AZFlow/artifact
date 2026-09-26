import { api } from "../shared/azflow-api.js";
const formView=document.querySelector("#form-view"), success=document.querySelector("#success-view"), status=document.querySelector("#status"), input=document.querySelector("#identifier");
document.querySelector("#form").addEventListener("submit", async event => {
  event.preventDefault(); status.textContent="Checking…"; status.classList.remove("error");
  try {
    const result=await api("/check-ins",{method:"POST",body:JSON.stringify({identifier_type:"fiscal_code",identifier_value:input.value.trim().toUpperCase(),totem_reference:"TOTEM-1"})});
    document.querySelector("#code").textContent=result.public_call_code; formView.classList.add("hidden"); success.classList.remove("hidden");
  } catch(error){ status.textContent=error.message; status.classList.add("error"); }
});
document.querySelector("#again").addEventListener("click",()=>{success.classList.add("hidden");formView.classList.remove("hidden");status.textContent="";input.value="";input.focus();});
