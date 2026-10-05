document.addEventListener("DOMContentLoaded", () => {
    const password = document.getElementById("passwordField");
    const showPassword = document.getElementById("showPasswordCheckbox");
    if (password && showPassword) {
        showPassword.addEventListener("change", () => { password.type = showPassword.checked ? "text" : "password"; });
    }

    const edit = document.getElementById("editButton");
    const cancel = document.getElementById("cancelButton");
    const editor = document.getElementById("profileEditContainer");
    if (edit && editor) edit.addEventListener("click", () => { editor.style.display = "block"; editor.querySelector("input")?.focus(); });
    if (cancel && editor) cancel.addEventListener("click", () => { editor.style.display = "none"; edit?.focus(); });

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

function printInvoice() {
    const content = document.getElementById("print-area");
    if (!content) return;
    const original = document.body.innerHTML;
    document.body.innerHTML = content.innerHTML;
    window.print();
    document.body.innerHTML = original;
    window.location.reload();
}
