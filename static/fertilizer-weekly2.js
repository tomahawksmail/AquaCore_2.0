"use strict";
(() => {
  const host = document.getElementById("fertilizer2-weekdays");
  const toggle = document.getElementById("fertilizer2-scheduler-toggle");
  const reveal = document.getElementById("fertilizer2-weekly-reveal");
  const save = document.getElementById("fertilizer2-weekly-save");
  const count = document.getElementById("fertilizer2-weekly-count");
  const feedback = document.getElementById("fertilizer2-weekly-feedback");
  if (!host || !toggle || !reveal || !save || !count || !feedback) return;

  const inputs = [...host.querySelectorAll('input[type="checkbox"]')];
  const readDays = () => inputs.filter(i => i.checked).map(i => Number(i.value));
  let saved = readDays();
  let busy = false;
  const same = (a, b) => a.length === b.length && a.every((day, i) => day === b[i]);
  const notice = (message, state = "idle") => {
    feedback.textContent = message;
    feedback.dataset.state = state;
  };
  const refresh = () => {
    const selected = readDays();
    const n = selected.length;
    count.textContent = n + (n === 1 ? " time" : " times") + " per week";
    const changed = !same(selected, saved);
    save.disabled = busy || !changed || inputs.some(i => i.disabled);
    if (!busy && changed) notice("Unsaved changes", "dirty");
    if (!busy && !changed && feedback.dataset.state === "dirty") notice("", "idle");
  };
  const setOpen = (open) => {
    toggle.setAttribute("aria-expanded", String(open));
    reveal.setAttribute("aria-hidden", String(!open));
    reveal.inert = !open;
    reveal.classList.toggle("is-open", open);
    if (!open && !busy && !same(readDays(), saved)) {
      for (const input of inputs) input.checked = saved.includes(Number(input.value));
      refresh();
      notice("Unsaved changes discarded", "idle");
    }
  };
  toggle.addEventListener("click", () => {
    if (!busy) setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });
  inputs.forEach(i => i.addEventListener("change", refresh));
  refresh();
  save.addEventListener("click", async () => {
    if (busy || save.disabled) return;
    const days = readDays();
    busy = true;
    save.disabled = true;
    notice("Saving schedule…", "idle");
    try {
      const response = await fetch("/api/fertilizer/2/schedule/days", {
        method:"POST", credentials:"same-origin",
        headers: {"Content-Type":"application/json", "X-CSRF-Token":window.AQUACORE_CSRF},
        body:JSON.stringify({days})
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || "Unable to save schedule");
      saved = [...days];
      notice(days.length === 0 ?
        "Saved. Automatic dosing is now off; manual dosing stays available." :
        "Saved. " + result.times_per_week + " scheduled dose(s) per week.", "saved");
    } catch (error) {
      notice("Not saved: " + error.message, "error");
    } finally {
      busy = false;
      refresh();
    }
  });
})();
