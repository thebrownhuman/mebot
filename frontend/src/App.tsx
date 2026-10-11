import { Routes, Route, Navigate } from "react-router-dom";
import RecruiterPage from "./pages/RecruiterPage";
import AdminPage from "./pages/AdminPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RecruiterPage />} />
      <Route path="/admin" element={<AdminPage />} />
      {/* anything else -> public chat */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
