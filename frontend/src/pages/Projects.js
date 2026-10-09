import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  createProject,
  listProjects,
  redeployProject,
  deleteProject,
} from "../api";

const STATUS_LABELS = {
  created: "Queued",
  generating: "Generating your site...",
  building: "Building & deploying...",
  running: "Live",
  failed: "Failed",
  stopped: "Stopped",
};

const IN_PROGRESS = new Set(["created", "generating", "building"]);

export default function Projects({ token }) {
  const [projects, setProjects] = useState([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(() => {
    listProjects(token).then(setProjects).catch((err) => setError(err.message));
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while anything is still generating/building.
  useEffect(() => {
    const hasInProgress = projects.some((p) => IN_PROGRESS.has(p.status));
    if (!hasInProgress) return undefined;
    const interval = setInterval(refresh, 2500);
    return () => clearInterval(interval);
  }, [projects, refresh]);

  const handleCreate = async (e) => {
    e.preventDefault();
    setError("");
    setCreating(true);
    try {
      await createProject(token, { name, description });
      setName("");
      setDescription("");
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleRedeploy = async (id) => {
    try {
      await redeployProject(token, id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this site and its data? This can't be undone.")) return;
    try {
      await deleteProject(token, id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="projects-container">
      <div className="projects-header">
        <h1>Your sites</h1>
        <Link to="/">Back home</Link>
      </div>

      <form className="new-project-form" onSubmit={handleCreate}>
        <h2>Create a new site</h2>
        <input
          type="text"
          placeholder="Business or site name (e.g. Luna Clothing Co.)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <textarea
          placeholder="Describe the site in plain language, e.g. 'I want a website for my clothing business. It should have a homepage, products page, contact form and shopping cart.'"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          minLength={10}
          required
        />
        {error && <span className="error-text">{error}</span>}
        <button type="submit" disabled={creating}>
          {creating ? "Creating..." : "Generate & deploy"}
        </button>
      </form>

      <div className="project-list">
        {projects.length === 0 && <p>No sites yet — create your first one above.</p>}
        {projects.map((p) => (
          <div className="project-card" key={p.id}>
            <div className="project-card-main">
              <h3>{p.name}</h3>
              <p className="project-desc">{p.description}</p>
              <span className={`status-badge status-${p.status}`}>
                {STATUS_LABELS[p.status] || p.status}
              </span>
              {p.status === "failed" && p.status_detail && (
                <p className="error-text">{p.status_detail}</p>
              )}
            </div>
            <div className="project-card-actions">
              {p.status === "running" && p.url && (
                <a href={p.url} target="_blank" rel="noreferrer">
                  <button>Open site</button>
                </a>
              )}
              <button onClick={() => handleRedeploy(p.id)} disabled={IN_PROGRESS.has(p.status)}>
                Redeploy
              </button>
              <button onClick={() => handleDelete(p.id)} disabled={IN_PROGRESS.has(p.status)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
