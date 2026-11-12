import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, staffToken } from "../lib/api";

export default function StaffLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    try {
      const { access_token } = await api("/api/auth/login", { method: "POST", body: { email, password } });
      staffToken.set(access_token);
      navigate("/staff");
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="page narrow">
      <h1 className="brand">Staff sign in</h1>
      <form className="card form" onSubmit={submit}>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <button className="btn">Sign in</button>
        {error && <p className="error">{error}</p>}
      </form>
    </main>
  );
}
