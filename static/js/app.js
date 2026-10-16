// Formulář pohybu: zobrazí jen pole, která druh používá, a nabídne účely daného druhu.
(function () {
  "use strict";

  function sync(form, kindChanged) {
    const kind = form.elements.kind.value;
    form.querySelectorAll("[data-kinds]").forEach((label) => {
      const needed = label.dataset.kinds.split(" ").includes(kind);
      label.hidden = !needed;
      label.querySelector("select").disabled = !needed;
    });
    const accountLabel = form.querySelector("[data-label-transfer]");
    if (accountLabel) accountLabel.textContent = kind === "TRANSFER" ? "Z účtu" : "Účet";
    const select = form.elements.category_id;
    for (const option of select.options) {
      const allowed = !option.dataset.kind || option.dataset.kind === kind || option.dataset.kind === "NEUTRAL";
      if (!allowed && option.selected && kindChanged) select.value = "";
      // Už vybraný účel jiného druhu zůstane viditelný, aby šla chyba opravit.
      const hide = !allowed && !option.selected;
      option.hidden = hide;
      option.disabled = hide;
    }
  }

  function init(root) {
    root.querySelectorAll("form.entry-form").forEach((form) => sync(form, false));
  }

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target.name === "kind" && target.form && target.form.classList.contains("entry-form")) {
      sync(target.form, true);
    }
  });
  document.addEventListener("DOMContentLoaded", () => init(document));
  document.addEventListener("htmx:load", (event) => init(event.detail.elt));
})();
