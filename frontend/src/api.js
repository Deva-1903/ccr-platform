// Thin API client. Same-origin in production (FastAPI serves the build);
// the Vite dev server proxies /api to :8000.

async function request(path, options = {}) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp.json();
}

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request("/api/health"),
  models: () => request("/api/models"),

  listProjects: () => request("/api/projects"),
  createProject: (body) => request("/api/projects", json("POST", body)),

  listCorpora: (projectId) => request(`/api/projects/${projectId}/corpora`),
  uploadCorpus: (projectId, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/projects/${projectId}/corpora`, { method: "POST", body: form });
  },

  listConstructs: () => request("/api/constructs"),
  createConstruct: (body) => request("/api/constructs", json("POST", body)),

  createJob: (body) => request("/api/jobs", json("POST", body)),
  listJobs: (projectId) => request(`/api/jobs?project_id=${projectId}`),
  getJob: (jobId) => request(`/api/jobs/${jobId}`),
  jobResults: (jobId) => request(`/api/jobs/${jobId}/results`),

  exportUrl: (jobId) => `/api/jobs/${jobId}/export`,
  metadataUrl: (jobId) => `/api/jobs/${jobId}/metadata`,
};
