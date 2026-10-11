import { Routes, Route, Navigate } from "react-router-dom";
import RecruiterPage from "./pages/RecruiterPage";
import AdminPage from "./pages/AdminPage";

export default function App() {
  return (
    <Routes>
      <Route path="/talkaboutshivansh" element={<RecruiterPage />} />
      <Route path="/talkaboutshivansh/aaddmmiinn" element={<AdminPage />} />
      {/* anything else -> recruiter portal */}
      <Route path="*" element={<Navigate to="/talkaboutshivansh" replace />} />
    </Routes>
  );
}
