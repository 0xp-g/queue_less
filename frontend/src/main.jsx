import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import "./styles.css";
import JoinPage from "./pages/JoinPage";
import TicketPage from "./pages/TicketPage";
import CheckInPage from "./pages/CheckInPage";
import StaffLogin from "./pages/StaffLogin";
import StaffConsole from "./pages/StaffConsole";
import BoardPage from "./pages/BoardPage";

function Home() {
  return (
    <main className="page narrow">
      <h1 className="brand">QueueLess</h1>
      <p>Scan the QR code at the venue to join a queue. You'll see your live position and wait time here.</p>
      <Link className="btn" to="/staff">Staff console</Link>
    </main>
  );
}

createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/join/:queueId" element={<JoinPage />} />
      <Route path="/t/:token" element={<TicketPage />} />
      <Route path="/checkin" element={<CheckInPage />} />
      <Route path="/staff/login" element={<StaffLogin />} />
      <Route path="/staff" element={<StaffConsole />} />
      <Route path="/board/:queueId" element={<BoardPage />} />
    </Routes>
  </BrowserRouter>
);
