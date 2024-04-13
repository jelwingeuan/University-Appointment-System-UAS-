document.addEventListener("DOMContentLoaded", function() {
    const passwordField = document.getElementById("passwordField");
    const showPasswordCheckbox = document.getElementById("showPasswordCheckbox");

    showPasswordCheckbox.addEventListener("change", function() {
        if (showPasswordCheckbox.checked) {
            passwordField.type = "text";
        } else {
            passwordField.type = "password";
        }
    });
});

function validatePhoneNumber() {
    var phoneNumber = document.getElementById('phoneInput').value;
    var regex = /^\d{10}$/; // Regular expression for a 10-digit phone number
  
    if (regex.test(phoneNumber)) {
      document.getElementById('validationMessage').innerHTML = 'Phone number is valid';
      document.getElementById('validationMessage').style.color = 'green';
    } else {
      document.getElementById('validationMessage').innerHTML = 'Please enter a valid 10-digit phone number';
      document.getElementById('validationMessage').style.color = 'red';
    }
  }
  