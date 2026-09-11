const params = new URLSearchParams(window.location.search);
const defaultBase =
  window.location.port === "8000" || window.location.port === ""
    ? "/api/v1"
    : "http://127.0.0.1:8000/api/v1";

export const API_BASE = params.get("api") || defaultBase;

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  if (response.status === 204) return null;
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch {
      try {
        detail = await response.text();
      } catch {
        /* keep status text */
      }
    }
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  return response;
}

export const api = {
  listProjects: () => request("/projects"),
  createProject: (name, description = null) =>
    request("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  getProject: (id) => request(`/projects/${id}`),

  listClasses: (projectId) => request(`/projects/${projectId}/classes`),
  createClass: (projectId, name, color_hex) =>
    request(`/projects/${projectId}/classes`, {
      method: "POST",
      body: JSON.stringify({ name, color_hex }),
    }),

  listImages: (projectId) => request(`/projects/${projectId}/images`),
  getImage: (imageId) => request(`/images/${imageId}`),
  imageFileUrl: (imageId) => `${API_BASE}/images/${imageId}/file`,

  saveAnnotations: (imageId, boxes) =>
    request(`/images/${imageId}/annotations`, {
      method: "PUT",
      body: JSON.stringify({
        boxes: boxes.map((box) => ({
          class_id: box.class_id,
          x_center: box.x_center,
          y_center: box.y_center,
          width: box.width,
          height: box.height,
        })),
      }),
    }),

  uploadImages(projectId, files, splits, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      for (const file of files) form.append("files", file);
      form.append("train", String(splits.train));
      form.append("valid", String(splits.valid));
      form.append("test", String(splits.test));
      xhr.open("POST", `${API_BASE}/projects/${projectId}/images/upload`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(event.loaded / event.total);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (err) {
            reject(err);
          }
        } else {
          let detail = xhr.responseText;
          try {
            detail = JSON.parse(xhr.responseText).detail || detail;
          } catch {
            /* raw text */
          }
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error("Ошибка сети при загрузке файлов"));
      xhr.send(form);
    });
  },

  async exportYolo(projectId) {
    const response = await fetch(`${API_BASE}/projects/${projectId}/export-yolo`);
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        /* keep status */
      }
      throw new Error(detail);
    }
    return response.blob();
  },
};
