import React, { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Home from "./pages/Home";
import Projects from "./pages/Projects";

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("token"));

  const handleLogin = (newToken) => {
    localStorage.setItem("token", newToken);
    setToken(newToken);
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    setToken(null);
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={token ? <Navigate to="/" /> : <Login onLogin={handleLogin} />}
        />
        <Route
          path="/register"
          element={token ? <Navigate to="/" /> : <Register onRegistered={handleLogin} />}
        />
        <Route
          path="/"
          element={token ? <Home token={token} onLogout={handleLogout} /> : <Navigate to="/login" />}
        />
        <Route
          path="/projects"
          element={token ? <Projects token={token} /> : <Navigate to="/login" />}
        />
      </Routes>
    </BrowserRouter>
  );
}
