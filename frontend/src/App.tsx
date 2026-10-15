import { Routes, Route, Navigate } from "react-router-dom";
import RecruiterPage from "./pages/RecruiterPage";
import AdminPage from "./pages/AdminPage";
import SetupPage from "./pages/SetupPage";
import LoginPage from "./pages/LoginPage";
import LlmPage from "./pages/LlmPage";
import SetupGate from "./components/SetupGate";
import RequireAdmin from "./components/RequireAdmin";

export default function App() {
  return (
    <SetupGate>
      <Routes>
        <Route path="/" element={<RecruiterPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/admin/login" element={<LoginPage />} />
        <Route path="/admin/llm" element={<RequireAdmin>{() => <LlmPage />}</RequireAdmin>} />
        <Route path="/admin" element={<RequireAdmin>{(me) => <AdminPage me={me} />}</RequireAdmin>} />
        {/* anything else -> public chat */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SetupGate>
  );
}
