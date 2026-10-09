import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCurrentUser } from "../api";

export default function Home({ token, onLogout }) {
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchCurrentUser(token)
      .then(setUser)
      .catch((err) => setError(err.message));
  }, [token]);

  return (
    <div className="home-container">
      <h1>Welcome{user ? `, ${user.username}` : ""}!</h1>
      {user && (
        <p>
          You're logged in as <strong>{user.email}</strong>.
        </p>
      )}
      {error && <p className="error-text">{error}</p>}
      <Link to="/projects">
        <button>Manage your sites</button>
      </Link>
      <button onClick={onLogout}>Log out</button>
    </div>
  );
}
