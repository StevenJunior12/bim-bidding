import { Routes, Route } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import HomePage from './pages/HomePage'
import OneClickPage from './pages/OneClickPage'
import OneClickTaskDetailPage from './pages/OneClickTaskDetailPage'
import KnowledgeBasePage from './pages/KnowledgeBasePage'
import SceneTemplatePage from './pages/SceneTemplatePage'
import SettingsPage from './pages/SettingsPage'
import TaskDetailPage from './pages/TaskDetailPage'
import ComparePage from './pages/ComparePage'
import CompareTaskDetailPage from './pages/CompareTaskDetailPage'
import ReviewPage from './pages/ReviewPage'
import ReviewTaskPage from './pages/ReviewTaskPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="one-click" element={<OneClickPage />} />
        <Route path="one-click/tasks/:id" element={<OneClickTaskDetailPage />} />
        <Route path="knowledge-base" element={<KnowledgeBasePage />} />
        <Route path="scene-template" element={<SceneTemplatePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="compare/tasks/:id" element={<CompareTaskDetailPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="review/:taskId" element={<ReviewTaskPage />} />
        <Route path="tasks/:id" element={<TaskDetailPage />} />
      </Route>
    </Routes>
  )
}

export default App
