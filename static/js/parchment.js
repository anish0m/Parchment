// Shared behaviour for every page: theme toggle, user menu, modals, confirmations.
// Pages mark elements with data-* attributes; nothing here is page-specific.
(() => {
  const root = document.documentElement;

  /* Theme ------------------------------------------------------------------ */
  const syncThemeButtons = () => {
    const dark = root.dataset.theme === "dark";
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
      const icon = button.querySelector("[data-theme-icon]");
      if (icon) icon.textContent = dark ? "☀" : "☾";
    });
  };
  const toggleTheme = () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("parchment-theme", root.dataset.theme); } catch (e) { /* storage blocked */ }
    syncThemeButtons();
  };

  /* User menu -------------------------------------------------------------- */
  const menu = () => document.querySelector("[data-user-menu]");
  const menuButton = () => document.querySelector("[data-user-button]");
  const setMenu = (open) => {
    menu()?.classList.toggle("open", open);
    menuButton()?.setAttribute("aria-expanded", String(open));
  };

  /* Modals ----------------------------------------------------------------- */
  const openers = new Map(); // modal id -> element to refocus when it closes
  const focusable = 'input:not([type="hidden"]):not([disabled]), textarea, select, button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

  const openModal = (id, opener) => {
    const modal = document.getElementById(id);
    if (!modal) return;
    openers.set(id, opener || document.activeElement);
    modal.classList.add("open");
    modal.removeAttribute("aria-hidden");
    document.body.classList.add("modal-open");
    setMenu(false);
    const target = modal.querySelector("[autofocus]") || modal.querySelector(`.modal-body ${focusable}`) || modal.querySelector(".modal");
    requestAnimationFrame(() => target?.focus({ preventScroll: true }));
  };

  const closeModal = (id) => {
    const modal = document.getElementById(id);
    if (!modal || !modal.classList.contains("open")) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    if (!document.querySelector(".modal-backdrop.open")) document.body.classList.remove("modal-open");
    // A material finished while its progress was showing: refresh the page's counts.
    if (modal.querySelector("[data-reload-on-close]")) { window.location.reload(); return; }
    // Content loaded from the server (and anything polling inside it) is dropped.
    if (modal.hasAttribute("data-clear-on-close")) {
      const body = modal.querySelector("[data-modal-body]");
      if (body) body.innerHTML = '<p class="modal-loading">Loading…</p>';
    }
    const opener = openers.get(id);
    openers.delete(id);
    if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
  };

  // Open a modal whose content comes from the server (data-modal-url).
  const openRemoteModal = (id, url, opener) => {
    const modal = document.getElementById(id);
    const body = modal?.querySelector("[data-modal-body]");
    if (!body) return;
    openModal(id, opener);
    window.htmx.ajax("GET", url, { target: body, swap: "innerHTML" }).then(() => {
      const first = body.querySelector("[autofocus]") || body.querySelector(focusable);
      first?.focus({ preventScroll: true });
    });
  };

  window.openModal = openModal;
  window.closeModal = closeModal;

  /* Confirmations ---------------------------------------------------------- */
  let pendingConfirm = null;
  const askToConfirm = (source, onConfirm) => {
    const modal = document.getElementById("confirm-modal");
    if (!modal) { if (window.confirm(source.dataset.confirm)) onConfirm(); return; }
    modal.querySelector("[data-confirm-title]").textContent = source.dataset.confirmTitle || "Are you sure?";
    modal.querySelector("[data-confirm-message]").textContent = source.dataset.confirm;
    const ok = modal.querySelector("[data-confirm-ok]");
    ok.textContent = source.dataset.confirmButton || "Delete";
    ok.className = `btn ${source.dataset.confirmStyle === "primary" ? "btn-primary" : "btn-danger-solid"}`;
    pendingConfirm = onConfirm;
    openModal("confirm-modal", document.activeElement);
    requestAnimationFrame(() => ok.focus());
  };

  // HTMX requests: hold the request until the modal is confirmed.
  document.addEventListener("htmx:confirm", (event) => {
    const source = event.detail.elt.closest("[data-confirm]");
    if (!source) return;
    event.preventDefault();
    askToConfirm(source, () => event.detail.issueRequest(true));
  });

  // Plain forms (no HTMX): hold the submit the same way.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form.matches("form[data-confirm]") || form.hasAttribute("hx-post") || form.dataset.confirmed) return;
    event.preventDefault();
    askToConfirm(form, () => { form.dataset.confirmed = "1"; form.requestSubmit(); });
  }, true);

  /* Clicks ------------------------------------------------------------------ */
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (target.closest("[data-theme-toggle]")) toggleTheme();

    if (target.closest("[data-user-button]")) {
      setMenu(!menu()?.classList.contains("open"));
    } else if (!target.closest("[data-user-menu]")) {
      setMenu(false);
    }

    const opener = target.closest("[data-open-modal]");
    if (opener) {
      event.preventDefault();
      if (opener.dataset.modalUrl) openRemoteModal(opener.dataset.openModal, opener.dataset.modalUrl, opener);
      else openModal(opener.dataset.openModal, opener);
    }
    const closer = target.closest("[data-close-modal]");
    if (closer) closeModal(closer.dataset.closeModal || closer.closest(".modal-backdrop")?.id);
    if (target.classList.contains("modal-backdrop")) closeModal(target.id);

    if (target.closest("[data-confirm-ok]")) {
      const action = pendingConfirm;
      pendingConfirm = null;
      closeModal("confirm-modal");
      action?.();
    }

    const dismiss = target.closest("[data-dismiss]");
    if (dismiss) dismiss.closest("[data-dismissable]")?.remove();

    // Tabs that pick how a material is added (upload a PDF or paste text).
    const tab = target.closest("[data-material-tab]");
    if (tab) {
      const scope = tab.closest("form") || document;
      const choice = tab.dataset.materialTab;
      scope.querySelectorAll("[data-material-tab]").forEach((t) => {
        const active = t === tab;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", String(active));
        t.tabIndex = active ? 0 : -1;
      });
      scope.querySelectorAll("[data-material-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.materialPanel === choice);
      });
      const input = scope.querySelector('input[name="source_type"]');
      if (input) input.value = choice;
    }
  });

  /* Keyboard ---------------------------------------------------------------- */
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = [...document.querySelectorAll(".modal-backdrop.open")].pop();
    if (open) { closeModal(open.id); event.stopPropagation(); return; }
    if (menu()?.classList.contains("open")) { setMenu(false); menuButton()?.focus(); }
  });

  // Keep Tab inside an open modal.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const open = [...document.querySelectorAll(".modal-backdrop.open")].pop();
    if (!open) return;
    const items = [...open.querySelectorAll(focusable)].filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
    else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
  });

  /* Files ------------------------------------------------------------------- */
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (input.matches("[data-file-input]")) {
      const label = input.closest("form")?.querySelector("[data-file-name]");
      if (label) label.textContent = input.files?.[0]?.name || "No file selected.";
    }
    // A material that's still processing has no cards yet: show its progress instead.
    if (input.matches("select[data-processing-aware]")) {
      const option = input.selectedOptions[0];
      if (option?.dataset.statusUrl) {
        event.stopPropagation(); // don't run the filter
        input.value = input.dataset.current || "";
        openRemoteModal("processing-modal", option.dataset.statusUrl, input);
      } else {
        input.dataset.current = input.value;
      }
    }
  }, true);

  ["dragenter", "dragover"].forEach((type) => document.addEventListener(type, (event) => {
    const drop = event.target.closest?.(".file-drop");
    if (drop) { event.preventDefault(); drop.classList.add("dragging"); }
  }));
  ["dragleave", "drop"].forEach((type) => document.addEventListener(type, (event) => {
    const drop = event.target.closest?.(".file-drop");
    if (!drop) return;
    drop.classList.remove("dragging");
    if (type === "drop" && event.dataTransfer?.files?.length) {
      event.preventDefault();
      const input = drop.querySelector('input[type="file"]');
      input.files = event.dataTransfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }));

  /* Toasts ------------------------------------------------------------------ */
  // showToast({ level: "success" | "danger" | "warning" | "info", title, message })
  const toastIcons = { success: "✓", danger: "✕", warning: "!", info: "i" };
  const showToast = ({ level = "info", title = "", message = "" } = {}) => {
    const region = document.querySelector("[data-toasts]");
    if (!region) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${level}`;
    toast.innerHTML = '<span class="toast-icon" aria-hidden="true"></span><div class="toast-text"><strong></strong><p></p></div><button type="button" class="toast-close" aria-label="Dismiss">×</button>';
    toast.querySelector(".toast-icon").textContent = toastIcons[level] || toastIcons.info;
    toast.querySelector("strong").textContent = title;
    toast.querySelector("p").textContent = message;
    // Up to three at once (one on a phone, where they'd cover the page); oldest go first.
    const limit = window.matchMedia("(max-width: 560px)").matches ? 1 : 3;
    [...region.children].slice(0, Math.max(region.children.length - limit + 1, 0)).forEach((old) => old.remove());
    region.append(toast);
    let timer;
    const remove = () => {
      clearTimeout(timer);
      toast.classList.add("leaving");
      setTimeout(() => toast.remove(), 200);
    };
    const wait = () => { timer = setTimeout(remove, 5000); };
    toast.addEventListener("mouseenter", () => clearTimeout(timer));
    toast.addEventListener("mouseleave", wait);
    toast.querySelector(".toast-close").addEventListener("click", remove);
    wait();
  };
  window.showToast = showToast;

  /* Server-sent instructions (HX-Trigger headers) --------------------------- */
  document.addEventListener("parchment:toast", (event) => showToast(event.detail));
  document.addEventListener("parchment:close-modal", (event) => closeModal(event.detail.id || event.detail.value));
  document.addEventListener("parchment:open-modal", (event) => openModal(event.detail.id || event.detail.value));

  // Modals that the server rendered open (e.g. a form with errors, without JavaScript
  // having opened it) get the same focus handling.
  const init = () => {
    syncThemeButtons();
    // Links like ?processing=<pk> open a modal once; a reload shouldn't reopen it.
    const url = new URL(window.location.href);
    if (["processing", "new"].some((key) => url.searchParams.has(key))) {
      url.searchParams.delete("processing");
      url.searchParams.delete("new");
      window.history.replaceState(window.history.state, "", url);
    }
    document.querySelectorAll(".modal-backdrop.open").forEach((modal) => {
      modal.classList.remove("open");
      openModal(modal.id);
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
