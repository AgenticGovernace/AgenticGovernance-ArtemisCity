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

const Layout = lazy(() => import('./components/Layout'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Tasks = lazy(() => import('./pages/Tasks'));
const Reports = lazy(() => import('./pages/Reports'));
const Agents = lazy(() => import('./pages/Agents'));
const Database = lazy(() => import('./pages/Database'));
const Executor = lazy(() => import('./pages/Executor'));

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
