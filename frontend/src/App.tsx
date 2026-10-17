import { Routes, Route, Navigate } from "react-router-dom";
import RecruiterPage from "./pages/RecruiterPage";
import AdminPage from "./pages/AdminPage";
import SetupPage from "./pages/SetupPage";
import LoginPage from "./pages/LoginPage";
import LlmPage from "./pages/LlmPage";
import AccountPage from "./pages/admin/AccountPage";
import LimitsPage from "./pages/admin/LimitsPage";
import NotificationsPage from "./pages/admin/NotificationsPage";
import ContactsPage from "./pages/admin/ContactsPage";
import ConversationsPage from "./pages/admin/ConversationsPage";
import OpenQuestionsPage from "./pages/admin/OpenQuestionsPage";
import MemoryPage from "./pages/admin/MemoryPage";
import WidgetPage from "./pages/admin/WidgetPage";
import ImportPage from "./pages/admin/ImportPage";
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
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="conversations" element={<ConversationsPage />} />
          <Route path="contacts" element={<ContactsPage />} />
          <Route path="open-questions" element={<OpenQuestionsPage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="widget" element={<WidgetPage />} />
          <Route path="import" element={<ImportPage />} />
          <Route path="account" element={<AccountPage />} />
        </Route>
        {/* anything else -> public chat */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SetupGate>
  );
}
