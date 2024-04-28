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

document.addEventListener("DOMContentLoaded", function() {
  // Get the canvas element
  const appointmentChartCanvas = document.getElementById("appointmentChart");
  const ctx = appointmentChartCanvas.getContext("2d");

  // Sample data for appointments over several months
  const data = {
      labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
      datasets: [{
          label: "Appointments",
          data: [10, 20, 30, 25, 35, 40],
          backgroundColor: "rgba(75, 192, 192, 0.2)",
          borderColor: "rgba(75, 192, 192, 1)",
          borderWidth: 2,
          pointRadius: 5,
          pointBackgroundColor: "rgba(75, 192, 192, 1)",
          pointBorderColor: "#fff",
          pointHoverRadius: 8,
          pointHoverBackgroundColor: "#fff",
          pointHoverBorderColor: "rgba(75, 192, 192, 1)"
      }]
  };

  // Create the line chart
  const appointmentChart = new Chart(ctx, {
      type: 'line',
      data: data,
      options: {
          scales: {
              y: {
                  beginAtZero: true
              }
          },
          plugins: {
              title: {
                  display: true,
                  text: 'Appointment Growth Over Time'
              }
          }
      }
  });
});




function sortTable(column, sort_asc) {
    [...table_rows].sort((a, b) => {
        let first_row = a.querySelectorAll('td')[column].textContent.toLowerCase(),
            second_row = b.querySelectorAll('td')[column].textContent.toLowerCase();

        return sort_asc ? (first_row < second_row ? 1 : -1) : (first_row < second_row ? -1 : 1);
    })
        .map(sorted_row => document.querySelector('tbody').appendChild(sorted_row));
}

// 3. Converting HTML table to PDF

const pdf_btn = document.querySelector('#toPDF');
const customers_table = document.querySelector('#customers_table');


const toPDF = function (customers_table) {
    const html_code = `
    <!DOCTYPE html>
    <link rel="stylesheet" type="text/css" href="style.css">
    <main class="table" id="customers_table">${customers_table.innerHTML}</main>`;

    const new_window = window.open();
     new_window.document.write(html_code);

    setTimeout(() => {
        new_window.print();
        new_window.close();
    }, 400);
}

pdf_btn.onclick = () => {
    toPDF(customers_table);
}

// 4. Converting HTML table to JSON

const json_btn = document.querySelector('#toJSON');

const toJSON = function (table) {
    let table_data = [],
        t_head = [],

        t_headings = table.querySelectorAll('th'),
        t_rows = table.querySelectorAll('tbody tr');

    for (let t_heading of t_headings) {
        let actual_head = t_heading.textContent.trim().split(' ');

        t_head.push(actual_head.splice(0, actual_head.length - 1).join(' ').toLowerCase());
    }

    t_rows.forEach(row => {
        const row_object = {},
            t_cells = row.querySelectorAll('td');

        t_cells.forEach((t_cell, cell_index) => {
            const img = t_cell.querySelector('img');
            if (img) {
                row_object['customer image'] = decodeURIComponent(img.src);
            }
            row_object[t_head[cell_index]] = t_cell.textContent.trim();
        })
        table_data.push(row_object);
    })

    return JSON.stringify(table_data, null, 4);
}

json_btn.onclick = () => {
    const json = toJSON(customers_table);
    downloadFile(json, 'json')
}

// 5. Converting HTML table to CSV File

const csv_btn = document.querySelector('#toCSV');

const toCSV = function (table) {
    // Code For SIMPLE TABLE
    // const t_rows = table.querySelectorAll('tr');
    // return [...t_rows].map(row => {
    //     const cells = row.querySelectorAll('th, td');
    //     return [...cells].map(cell => cell.textContent.trim()).join(',');
    // }).join('\n');

    const t_heads = table.querySelectorAll('th'),
        tbody_rows = table.querySelectorAll('tbody tr');

    const headings = [...t_heads].map(head => {
        let actual_head = head.textContent.trim().split(' ');
        return actual_head.splice(0, actual_head.length - 1).join(' ').toLowerCase();
    }).join(',') + ',' + 'image name';

    const table_data = [...tbody_rows].map(row => {
        const cells = row.querySelectorAll('td'),
            img = decodeURIComponent(row.querySelector('img').src),
            data_without_img = [...cells].map(cell => cell.textContent.replace(/,/g, ".").trim()).join(',');

        return data_without_img + ',' + img;
    }).join('\n');

    return headings + '\n' + table_data;
}

csv_btn.onclick = () => {
    const csv = toCSV(customers_table);
    downloadFile(csv, 'csv', 'customer orders');
}

// 6. Converting HTML table to EXCEL File

const excel_btn = document.querySelector('#toEXCEL');

const toExcel = function (table) {
    // Code For SIMPLE TABLE
    // const t_rows = table.querySelectorAll('tr');
    // return [...t_rows].map(row => {
    //     const cells = row.querySelectorAll('th, td');
    //     return [...cells].map(cell => cell.textContent.trim()).join('\t');
    // }).join('\n');

    const t_heads = table.querySelectorAll('th'),
        tbody_rows = table.querySelectorAll('tbody tr');

    const headings = [...t_heads].map(head => {
        let actual_head = head.textContent.trim().split(' ');
        return actual_head.splice(0, actual_head.length - 1).join(' ').toLowerCase();
    }).join('\t') + '\t' + 'image name';

    const table_data = [...tbody_rows].map(row => {
        const cells = row.querySelectorAll('td'),
            img = decodeURIComponent(row.querySelector('img').src),
            data_without_img = [...cells].map(cell => cell.textContent.trim()).join('\t');

        return data_without_img + '\t' + img;
    }).join('\n');

    return headings + '\n' + table_data;
}

excel_btn.onclick = () => {
    const excel = toExcel(customers_table);
    downloadFile(excel, 'excel');
}

const downloadFile = function (data, fileType, fileName = '') {
    const a = document.createElement('a');
    a.download = fileName;
    const mime_types = {
        'json': 'application/json',
        'csv': 'text/csv',
        'excel': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }
    a.href = `
        data:${mime_types[fileType]};charset=utf-8,${encodeURIComponent(data)}
    `;
    document.body.appendChild(a);
    a.click();
    a.remove();
}



