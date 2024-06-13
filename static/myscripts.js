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
  
  function printInvoice() {
      var printContent = document.getElementById("print-area").innerHTML; // Get the HTML content of the print area
      var originalContents = document.body.innerHTML; // Store the original HTML content of the body
      document.body.innerHTML = printContent; // Replace the body content with the print area content
      window.print(); // Print the document
      document.body.innerHTML = originalContents; // Restore the original body content
  }
  
  
  
  document.addEventListener("DOMContentLoaded", function() {
    setTimeout(function() {
        document.querySelector(".messagecontainer").classList.add("active");
    }, 100); // Adjust the delay as needed
  });
  
  
  //Graph for admin
  document.addEventListener("DOMContentLoaded", function() {
    // Set a timeout for the message container to add the 'active' class
    setTimeout(function() {
        document.querySelector(".messagecontainer").classList.add("active");
    }, 100); // Adjust the delay as needed
  
    // Retrieve data from hidden elements
    const numTeachers = parseInt(document.getElementById('num_teachers').value);
    const numStudents = parseInt(document.getElementById('num_students').value);
    const numAppointments = parseInt(document.getElementById('num_appointments').value);
    const numUsers = parseInt(document.getElementById('num_users').value);

    // Data for the bar chart
    const barChartData = {
        labels: ['Student', 'Lecturer', 'Appointment', 'User'],
        datasets: [{
            label: 'Data',
            backgroundColor: ['rgba(255, 99, 132, 0.5)', // Red
                             'rgba(54, 162, 235, 0.5)', // Blue
                             'rgba(255, 206, 86, 0.5)', // Yellow
                             'rgba(75, 192, 192, 0.5)'], // Green
            borderColor: ['rgba(255, 99, 132, 1)', // Red
                          'rgba(54, 162, 235, 1)', // Blue
                          'rgba(255, 206, 86, 1)', // Yellow
                          'rgba(75, 192, 192, 1)'], // Green
            borderWidth: 1,
            data: [numStudents, numTeachers, numAppointments, numUsers]
        }]
    };
  
    // Additional chart configuration options for the bar chart
    const barChartOptions = {
        scales: {
            yAxes: [{
                ticks: {
                    beginAtZero: true
                }
            }]
        }
    };
  
    // Get the canvas element for the bar chart
    const barChartCanvas = document.getElementById('barChart');
  
    // Initialize the bar chart
    new Chart(barChartCanvas, {
        type: 'bar',
        data: barChartData,
        options: barChartOptions
    });
  
    // Data for the line chart
    const pieChartData = {
        labels: ['Student', 'Lecturer', 'Appointment', 'User'],
        datasets: [{
            label: 'Data',
            backgroundColor: ['rgba(255, 99, 132, 0.5)', // Red
                             'rgba(54, 162, 235, 0.5)', // Blue
                             'rgba(255, 206, 86, 0.5)', // Yellow
                             'rgba(75, 192, 192, 0.5)'], // Green
            borderColor: ['rgba(255, 99, 132, 1)', // Red
                          'rgba(54, 162, 235, 1)', // Blue
                          'rgba(255, 206, 86, 1)', // Yellow
                          'rgba(75, 192, 192, 1)'], // Green
            borderWidth: 1,
            data: [numStudents, numTeachers, numAppointments, numUsers]
        }]
    };
  
    // Additional chart configuration options for the pie chart
    const pieChartOptions = {
        // Add any specific options for the pie chart here
    };
  
    // Get the canvas element for the pie chart
    const pieChartCanvas = document.getElementById('pieChart');
  
    // Initialize the pie chart
    new Chart(pieChartCanvas, {
        type: 'pie',
        data: pieChartData,
        options: pieChartOptions
    });
});

  
  
  document.addEventListener('DOMContentLoaded', function() {
      let next = document.querySelector('.next');
      let prev = document.querySelector('.prev');
  
      next.addEventListener('click', function() {
          let items = document.querySelectorAll('.item');
          document.querySelector('.slide').appendChild(items[0]);
      });
  
      prev.addEventListener('click', function() {
          let items = document.querySelectorAll('.item');
          document.querySelector('.slide').prepend(items[items.length - 1]);
      });
  });
  
  document.addEventListener("DOMContentLoaded", function () {
    const editButton = document.getElementById("editButton");
    const cancelButton = document.getElementById("cancelButton");
    const profileEditContainer = document.getElementById("profileEditContainer");

    // Add event listener to the Edit button
    editButton.addEventListener("click", function () {
        profileEditContainer.style.display = "block"; // Display the profile edit container
    });

    // Add event listener to the Cancel button
    cancelButton.addEventListener("click", function () {
        profileEditContainer.style.display = "none"; // Hide the profile edit container
    });
});

  
  window.onclick = function(event) {
      if (!event.target.matches('.dropbtn')) {
        var dropdowns = document.getElementsByClassName("dropdown-content");
        var i;
        for (i = 0; i < dropdowns.length; i++) {
          var openDropdown = dropdowns[i];
          if (openDropdown.style.display === "block") {
            openDropdown.style.display = "none";
          }
        }
      }
    }
    //Display Pin Input
    document.addEventListener('DOMContentLoaded', function () {
      var teacherRole = document.getElementById('teacherRole');
      var pinInput = document.getElementById('pinInput');
  
      teacherRole.addEventListener('change', function () {
          if (teacherRole.checked) {
              pinInput.style.display = 'flex';
          } else {
              pinInput.style.display = 'none';
          }
      });
  });

//flash message
async function displayFlashMessages() {
    try {
        const response = await fetch('/get_flash_messages');
        const messages = await response.json();
        
        messages.forEach(([message, category]) => {
            window.alert(`${category.toUpperCase()}: ${message}`);
        });
    } catch (error) {
        console.error('Error fetching flash messages:', error);
    }
}

// Call the function to display flash messages when the page loads
window.onload = displayFlashMessages;
  
  
  
  
  