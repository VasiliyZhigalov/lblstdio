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
  updateProject: (id, name, description = null) =>
    request(`/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name, description }),
    }),
  getProject: (id) => request(`/projects/${id}`),
  deleteProject: (id) => request(`/projects/${id}`, { method: "DELETE" }),

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
        boxes: boxes.map((box) => {
          const payload = {
            class_id: box.class_id,
            x_center: box.x_center,
            y_center: box.y_center,
            width: box.width,
            height: box.height,
          };
          if (box.id) payload.id = box.id;
          return payload;
        }),
      }),
    }),

  propagateBox: (sourceImageId, targetImageId, sourceBox) =>
    request("/matching/propagate-box", {
      method: "POST",
      body: JSON.stringify({
        source_image_id: sourceImageId,
        target_image_id: targetImageId,
        source_box: {
          id: sourceBox.id,
          class_id: sourceBox.class_id,
          x_center: sourceBox.x_center,
          y_center: sourceBox.y_center,
          width: sourceBox.width,
          height: sourceBox.height,
        },
      }),
    }),

  propagateBoxes: (sourceImageId, targetImageId, sourceBoxes) =>
    request("/matching/propagate-boxes", {
      method: "POST",
      body: JSON.stringify({
        source_image_id: sourceImageId,
        target_image_id: targetImageId,
        source_boxes: sourceBoxes.map((sourceBox) => ({
          id: sourceBox.id,
          class_id: sourceBox.class_id,
          x_center: sourceBox.x_center,
          y_center: sourceBox.y_center,
          width: sourceBox.width,
          height: sourceBox.height,
        })),
      }),
    }),

  verifyAnnotation: (imageId, annotationId) =>
    request(`/images/${imageId}/annotations/${annotationId}/verify`, {
      method: "POST",
    }),

  verifyAllAnnotations: (imageId) =>
    request(`/images/${imageId}/verify-all`, {
      method: "POST",
    }),

  rejectAllPending: (imageId) =>
    request(`/images/${imageId}/reject-pending`, {
      method: "POST",
    }),

  markBackground: (imageId) =>
    request(`/images/${imageId}/mark-background`, {
      method: "POST",
    }),

  deleteAnnotation: (imageId, annotationId) =>
    request(`/images/${imageId}/annotations/${annotationId}`, {
      method: "DELETE",
    }),

  uploadImages(projectId, files, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      for (const file of files) {
        // Keep binary filename as basename; browsers often strip directories from
        // Content-Disposition filename. Send the relative path separately.
        form.append("files", file, file.name);
        form.append(
          "relative_paths",
          (file.webkitRelativePath || file.name || "").replace(/\\/g, "/")
        );
      }
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
          reject(new Error(typeof detail === "string" ? detail : JSON.stringify(detail)));
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

  async _downloadBlob(path) {
    const response = await fetch(`${API_BASE}${path}`);
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
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]+)"/.exec(disposition);
    return { blob, filename: match?.[1] || "download.zip" };
  },

  listDatasetVersions: (projectId) =>
    request(`/projects/${projectId}/dataset-versions`),

  createDatasetVersion: (projectId, body) =>
    request(`/projects/${projectId}/dataset-versions`, {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),

  getDatasetVersion: (versionId) => request(`/dataset-versions/${versionId}`),

  renameDatasetVersion: (versionId, name) =>
    request(`/dataset-versions/${versionId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  exportDatasetVersion: (versionId) =>
    api._downloadBlob(`/dataset-versions/${versionId}/export`),

  deleteDatasetVersion: (versionId) =>
    request(`/dataset-versions/${versionId}`, { method: "DELETE" }),

  startTraining: (projectId, body) =>
    request(`/projects/${projectId}/train`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getTrainingJob: (jobId) => request(`/training-jobs/${jobId}`),

  getTrainingDevice: () => request("/training/device"),

  listModels: (projectId) => request(`/projects/${projectId}/models`),

  uploadModel: (projectId, file, name = null) => {
    const form = new FormData();
    form.append("file", file, file.name || "best.pt");
    if (name) form.append("name", name);
    return request(`/projects/${projectId}/models/upload`, {
      method: "POST",
      body: form,
    });
  },

  renameModel: (projectId, modelId, name) =>
    request(`/projects/${projectId}/models/${modelId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  exportModel: (projectId, modelId) =>
    api._downloadBlob(`/projects/${projectId}/models/${modelId}/export`),

  deleteModel: (projectId, modelId) =>
    request(`/projects/${projectId}/models/${modelId}`, { method: "DELETE" }),

  autoLabel: (projectId, modelId, body) =>
    request(`/projects/${projectId}/models/${modelId}/auto-label`, {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),

  getAutoLabelJob: (jobId) => request(`/auto-label-jobs/${jobId}`),
};
