document.addEventListener("DOMContentLoaded", () => {
    const password = document.getElementById("passwordField");
    const showPassword = document.getElementById("showPasswordCheckbox");
    if (password && showPassword) {
        showPassword.addEventListener("change", () => { password.type = showPassword.checked ? "text" : "password"; });
    }

    document.querySelectorAll("dialog[data-auto-open-dialog]").forEach((dialog) => {
        window.UASUI?.openDialog(dialog);
        dialog.querySelector("input, select, textarea")?.focus();
    });

    const accountToken = document.getElementById("account-token");
    if (accountToken) {
        const fragment = new URLSearchParams(window.location.hash.slice(1));
        const token = fragment.get("token") || "";
        accountToken.value = token;
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
        if (!token) {
            const error = document.getElementById("token-error");
            if (error) error.hidden = false;
        }
    }

    const next = document.querySelector(".next");
    const previous = document.querySelector(".prev");
    const slide = document.querySelector(".slide");
    next?.addEventListener("click", () => { const first = slide?.querySelector(".item"); if (first) slide.append(first); });
    previous?.addEventListener("click", () => { const items = slide?.querySelectorAll(".item"); if (items?.length) slide.prepend(items[items.length - 1]); });

    const studentRole = document.getElementById("studentRole");
    const teacherRole = document.getElementById("teacherRole");
    const pinInput = document.getElementById("pinInput");
    const signupDetails = document.getElementById("signupDetails");
    const emailNotice = document.getElementById("emailFormatNotice");
    const setSignupRole = () => {
        if (!pinInput || !signupDetails) return;
        pinInput.hidden = !teacherRole?.checked;
        signupDetails.hidden = !studentRole?.checked && !teacherRole?.checked;
        if (emailNotice) emailNotice.textContent = studentRole?.checked
            ? "Students must use an @student.mmu.edu.my email address."
            : teacherRole?.checked ? "Lecturers must use an @mmu.edu.my email address." : "";
    };
    studentRole?.addEventListener("change", setSignupRole);
    teacherRole?.addEventListener("change", setSignupRole);
    if (studentRole || teacherRole) setSignupRole();
});
