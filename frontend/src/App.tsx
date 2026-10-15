import { Routes, Route, Navigate } from "react-router-dom";
import RecruiterPage from "./pages/RecruiterPage";
import AdminPage from "./pages/AdminPage";
import SetupPage from "./pages/SetupPage";
import LoginPage from "./pages/LoginPage";
import LlmPage from "./pages/LlmPage";
import AccountPage from "./pages/admin/AccountPage";
import LimitsPage from "./pages/admin/LimitsPage";
import ProfilePage from "./pages/admin/ProfilePages";
import AdminLayout from "./components/admin/AdminLayout";
import SetupGate from "./components/SetupGate";
import RequireAdmin from "./components/RequireAdmin";

export default function App() {
  return (
    <SetupGate>
      <Routes>
        <Route path="/" element={<RecruiterPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/admin/login" element={<LoginPage />} />
        <Route
          path="/admin"
          element={<RequireAdmin>{(me) => <AdminLayout me={me} />}</RequireAdmin>}
        >
          <Route index element={<AdminPage />} />
          <Route path="profile/:page" element={<ProfilePage />} />
          <Route path="llm" element={<LlmPage />} />
          <Route path="limits" element={<LimitsPage />} />
          <Route path="account" element={<AccountPage />} />
        </Route>
        {/* anything else -> public chat */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SetupGate>
  );
}
