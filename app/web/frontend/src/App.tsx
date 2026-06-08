/**
 * MCP Dashboard Application Component
 *
 * Root component that sets up routing for the MCP dashboard.
 * Provides navigation between Dashboard, Tasks, Reports, and Agents views.
 *
 * @module App
 */

import { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';

const Layout = lazy(() => import('./components/Layout.tsx'));
const Dashboard = lazy(() => import('./pages/Dashboard.tsx'));
const Tasks = lazy(() => import('./pages/Tasks.tsx'));
const Reports = lazy(() => import('./pages/Reports.tsx'));
const Agents = lazy(() => import('./pages/Agents.tsx'));
const Database = lazy(() => import('./pages/Database.tsx'));
const Executor = lazy(() => import('./pages/Executor.tsx'));

/**
 * Main application component with routing configuration.
 *
 * Routes:
 * - `/` - Dashboard home page
 * - `/tasks` - Task management view
 * - `/reports` - Reports viewer
 * - `/agents` - Agent listing
 * - `/database` - Database viewer with tabbed interface
 * - `/executor` - CLI executor with form-based interface
 *
 * @returns The rendered application with routing
 */
function App() {
  return (
    <Router>
      <Suspense fallback={<div>Loading...</div>}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="reports" element={<Reports />} />
            <Route path="agents" element={<Agents />} />
            <Route path="database" element={<Database />} />
            <Route path="executor" element={<Executor />} />
          </Route>
        </Routes>
      </Suspense>
    </Router>
  );
}

export default App;
