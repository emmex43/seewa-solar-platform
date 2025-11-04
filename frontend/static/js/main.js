const apiURL = "http://127.0.0.1:5000/projects";
const tableBody = document.querySelector("#projectsTable tbody");
const form = document.getElementById("projectForm");

async function loadProjects() {
  const res = await fetch(apiURL);
  const projects = await res.json();
  tableBody.innerHTML = "";
  projects.forEach(p => {
    const row = `
      <tr>
        <td>${p.id}</td>
        <td>${p.project_name}</td>
        <td>${p.location}</td>
        <td>${p.capacity_kw}</td>
        <td>${p.cost_usd}</td>
        <td>${p.status}</td>
        <td><button onclick="deleteProject(${p.id})">Delete</button></td>
      </tr>
    `;
    tableBody.insertAdjacentHTML("beforeend", row);
  });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = {
    project_name: document.getElementById("project_name").value,
    location: document.getElementById("location").value,
    capacity_kw: document.getElementById("capacity_kw").value,
    cost_usd: document.getElementById("cost_usd").value,
    status: document.getElementById("status").value
  };

  await fetch(apiURL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });

  form.reset();
  loadProjects();
});

async function deleteProject(id) {
  await fetch(`${apiURL}/${id}`, { method: "DELETE" });
  loadProjects();
}

loadProjects();
