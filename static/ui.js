(() => {
    const root = document.documentElement;
    const storageKey = "uas-theme";
    const themes = new Set(["system", "light", "dark"]);

    const readTheme = () => {
        try {
            const saved = localStorage.getItem(storageKey);
            return themes.has(saved) ? saved : "system";
        } catch {
            return "system";
        }
    };

    const applyTheme = (theme, persist = false) => {
        const selected = themes.has(theme) ? theme : "system";
        root.dataset.theme = selected;
        const control = document.getElementById("uas-theme");
        if (control) control.value = selected;
        if (persist) {
            try {
                localStorage.setItem(storageKey, selected);
            } catch {
                // Keep the current page usable when browser storage is disabled.
            }
        }
    };

    applyTheme(readTheme());

    const toast = ({ kind = "info", title = "", message = "" } = {}) => {
        const region = document.getElementById("toast-region");
        if (!region || !message) return null;
        const safeKind = ["success", "error", "warning", "info"].includes(kind) ? kind : "info";
        const item = document.createElement("section");
        item.className = `toast toast-${safeKind}`;
        item.setAttribute("role", ["error", "warning"].includes(safeKind) ? "alert" : "status");

        if (title) {
            const heading = document.createElement("strong");
            heading.className = "toast-title";
            heading.textContent = title;
            item.append(heading);
        }
        const body = document.createElement("p");
        body.className = "toast-message";
        body.textContent = message;
        item.append(body);

        const dismiss = document.createElement("button");
        dismiss.className = "toast-dismiss icon-button";
        dismiss.type = "button";
        dismiss.setAttribute("aria-label", "Dismiss notification");
        dismiss.textContent = "×";
        dismiss.addEventListener("click", () => item.remove());
        item.append(dismiss);
        region.append(item);

        if (["success", "info"].includes(safeKind)) {
            let remaining = 5000;
            let startedAt = 0;
            let timer;
            const pause = () => {
                if (!timer) return;
                window.clearTimeout(timer);
                timer = null;
                remaining = Math.max(0, remaining - (Date.now() - startedAt));
            };
            const resume = () => {
                if (timer || item.matches(":hover, :focus-within")) return;
                startedAt = Date.now();
                timer = window.setTimeout(() => item.remove(), remaining);
            };
            item.addEventListener("mouseenter", pause);
            item.addEventListener("mouseleave", resume);
            item.addEventListener("focusin", pause);
            item.addEventListener("focusout", (event) => {
                if (!item.contains(event.relatedTarget)) resume();
            });
            resume();
        }
        return item;
    };

    const openDialog = (id, trigger = document.activeElement) => {
        const dialog = typeof id === "string" ? document.getElementById(id) : id;
        if (!(dialog instanceof HTMLDialogElement) || dialog.open) return false;
        dialog._uasTrigger = trigger instanceof HTMLElement ? trigger : null;
        if (!dialog._uasFocusHandler) {
            dialog.addEventListener("close", () => {
                if (dialog._uasTrigger?.isConnected) dialog._uasTrigger.focus();
                dialog._uasTrigger = null;
            });
            dialog._uasFocusHandler = true;
        }
        dialog.showModal();
        return true;
    };

    const closeDialog = (id) => {
        const dialog = typeof id === "string" ? document.getElementById(id) : id;
        if (dialog instanceof HTMLDialogElement && dialog.open) dialog.close();
    };

    window.UASUI = Object.freeze({ toast, openDialog, closeDialog });

    const initialize = () => {
        const control = document.getElementById("uas-theme");
        if (control) {
            control.value = root.dataset.theme;
            control.addEventListener("change", () => applyTheme(control.value, true));
        }
        window.addEventListener("storage", (event) => {
            if (event.key === storageKey) applyTheme(event.newValue || "system");
        });
        document.addEventListener("click", (event) => {
            const target = event.target instanceof Element ? event.target : null;
            if (!target) return;
            const accountMenu = document.querySelector(".app-account-menu[open]");
            if (accountMenu && !accountMenu.contains(target)) accountMenu.open = false;
            if (target.closest(".app-account-menu a, .app-account-menu button")) {
                target.closest(".app-account-menu")?.removeAttribute("open");
            }
            const opener = target.closest("[data-dialog-open]");
            if (opener) {
                const cancelId = opener.dataset.cancelAppointment;
                if (cancelId) document.getElementById("cancel-appointment-id").value = cancelId;
                openDialog(opener.dataset.dialogOpen, opener);
            }
            const closer = target.closest("[data-dialog-close]");
            if (closer) closeDialog(closer.closest("dialog"));
            const alertCloser = target.closest("[data-alert-dismiss]");
            if (alertCloser) alertCloser.closest("[role='alert'], [role='status']")?.remove();
            const toastTrigger = target.closest("[data-toast-kind]");
            if (toastTrigger) {
                toast({
                    kind: toastTrigger.dataset.toastKind,
                    title: toastTrigger.dataset.toastTitle || "",
                    message: toastTrigger.dataset.toastMessage || "",
                });
            }
            const copyButton = target.closest("[data-copy-text]");
            if (copyButton) {
                if (!navigator.clipboard?.writeText) {
                    toast({ kind: "error", message: "Copy is unavailable. Select and copy the reference instead." });
                    return;
                }
                navigator.clipboard.writeText(copyButton.dataset.copyText).then(() => {
                    toast({ kind: "success", message: "Booking reference copied." });
                }).catch(() => {
                    toast({ kind: "error", message: "The reference could not be copied. Select and copy it instead." });
                });
            }
        });
        document.addEventListener("submit", (event) => {
            const form = event.target;
            if (event.defaultPrevented || !form.matches("[data-submit-loading]")) return;
            const button = event.submitter || form.querySelector('button[type="submit"]');
            if (!button) return;
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
            button.textContent = button.dataset.submitLabel || "Saving…";
        });
        document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") return;
            const accountMenu = document.querySelector(".app-account-menu[open]");
            if (!accountMenu) return;
            accountMenu.open = false;
            accountMenu.querySelector("summary")?.focus();
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
