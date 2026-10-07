(() => {
    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-copy-invitation]").forEach((button) => {
            button.addEventListener("click", async () => {
                const token = document.getElementById(button.dataset.copyInvitation);
                if (!token) return;
                try {
                    await navigator.clipboard.writeText(token.textContent.trim());
                    window.UASUI?.toast({ kind: "success", message: "Invitation token copied." });
                } catch {
                    const selection = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(token);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    window.UASUI?.toast({ kind: "info", message: "Token selected. Copy it now." });
                }
            });
        });

        document.querySelectorAll("[data-image-preview-input]").forEach((input) => {
            input.addEventListener("change", () => {
                const file = input.files?.[0];
                const preview = document.getElementById(input.dataset.imagePreviewInput);
                if (!file || !preview || !file.type.startsWith("image/")) return;
                const previous = preview.dataset.previewUrl;
                if (previous) URL.revokeObjectURL(previous);
                const url = URL.createObjectURL(file);
                preview.src = url;
                preview.dataset.previewUrl = url;
                preview.hidden = false;
            });
        });
    });
})();
