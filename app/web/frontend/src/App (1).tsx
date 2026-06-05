/**
 * MCP Dashboard Application Component
 *
 * Root component that sets up routing for the MCP dashboard.
 * Provides navigation between Dashboard, Tasks, Reports, and Agents views.
 *
 * @module App
 */

import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Tasks from './pages/Tasks';
import Reports from './pages/Reports';
import Agents from './pages/Agents';

/**
 * Main application component with routing configuration.
 *
 * Routes:
 * - `/` - Dashboard home page
 * - `/tasks` - Task management view
 * - `/reports` - Reports viewer
 * - `/agents` - Agent listing
 *
 * @returns The rendered application with routing
 */
function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="reports" element={<Reports />} />
          <Route path="agents" element={<Agents />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
