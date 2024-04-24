document.addEventListener("DOMContentLoaded", function () {
  const passwordField = document.getElementById("passwordField");
  const showPasswordCheckbox = document.getElementById("showPasswordCheckbox");

  showPasswordCheckbox.addEventListener("change", function () {
    if (showPasswordCheckbox.checked) {
      passwordField.type = "text";
    } else {
      passwordField.type = "password";
    }
  });
});

// dashboard.js

document.addEventListener("DOMContentLoaded", function() {
  // Get the canvas element
  const chartCanvas = document.getElementById("dashboardChart");
  const ctx = chartCanvas.getContext("2d");

  // Data for the chart
  const data = {
      labels: ["Students", "Lecturers", "Appointments", "Users"],
      datasets: [{
          label: "Data",
          backgroundColor: ["#3e95cd", "#8e5ea2", "#3cba9f", "#e8c3b9"],
          data: [54, 65, 20, 120]
      }]
  };

  // Create the chart
  const chart = new Chart(ctx, {
      type: "bar",
      data: data,
      options: {
          legend: { display: false },
          title: {
              display: true,
              text: "Admin Dashboard"
          }
      }
  });
});


