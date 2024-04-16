document.addEventListener('DOMContentLoaded', function() {
  const signInLink = document.getElementById('signInLink');
  const signOutLink = document.getElementById('signOutLink');

  // Function to check if the user is signed in
  function isUserSignedIn() {
      return !!localStorage.getItem('userEmail'); // Return true if user email exists in local storage, false otherwise
  }

  // Function to update navigation bar based on sign-in status
  function updateNavBar() {
      if (isUserSignedIn()) {
          signInLink.style.display = 'none'; // Hide sign-in link
          signOutLink.style.display = 'inline'; // Show sign-out link
      } else {
          signInLink.style.display = 'inline'; // Show sign-in link
          signOutLink.style.display = 'none'; // Hide sign-out link
      }
  }

  // Event listener for sign-out link click
  signOutLink.addEventListener('click', function(event) {
      event.preventDefault(); // Prevent default link behavior
      signOut(); // Call sign-out function
      updateNavBar(); // Update navigation bar after sign-out
  });

  // Initial update of navigation bar
  updateNavBar();
});

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

document.addEventListener('DOMContentLoaded', function() {
  const emailInput = document.querySelector('input[type="email"]');
  const emailPlaceholder = 'example@gmail.com';
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  // Show placeholder when input is empty
  emailInput.addEventListener('focus', function() {
      if (emailInput.value === '') {
          emailInput.setAttribute('placeholder', emailPlaceholder);
      }
  });

  // Remove placeholder when input is focused and not empty
  emailInput.addEventListener('input', function() {
      if (emailInput.value !== '') {
          emailInput.removeAttribute('placeholder');
      }
  });

  // Restore placeholder if input is empty on blur
  emailInput.addEventListener('blur', function() {
      if (emailInput.value === '') {
          emailInput.setAttribute('placeholder', emailPlaceholder);
      }
  });

  // Email validation on form submission
  const form = document.querySelector('form');
  form.addEventListener('submit', function(event) {
      const email = emailInput.value.trim();
      if (!emailRegex.test(email)) {
          alert('Please enter a valid email address.');
          event.preventDefault(); // Prevent form submission
      }
  });

  // Remove placeholder when clicking outside of the email input field
  document.body.addEventListener('click', function(event) {
      if (event.target !== emailInput) {
          emailInput.removeAttribute('placeholder');
      }
  });
});




