import { BrowserRouter, NavLink, Routes, Route } from 'react-router-dom';
import Overview from './pages/Overview';
import Signals from './pages/Signals';
import Orders from './pages/Orders';
import Risk from './pages/Risk';
import Analytics from './pages/Analytics';
import Extensions from './pages/Extensions';
import Logs from './pages/Logs';
import Settings from './pages/Settings';
import { SafetyBanner } from './lib';
import './styles.css';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <h1>Trading Control Room</h1>
          <nav className="main-nav">
            {[
              { to: '/', label: 'Overview' },
              { to: '/signals', label: 'Signals' },
              { to: '/orders', label: 'Orders' },
              { to: '/risk', label: 'Risk' },
              { to: '/analytics', label: 'Analytics' },
              { to: '/extensions', label: 'Extensions' },
              { to: '/logs', label: 'Logs' },
              { to: '/settings', label: 'Settings' },
            ].map(({ to, label }) => (
              <NavLink key={to} to={to} className={({ isActive }) => `nav-link${isActive ? ' nav-link-active' : ''}`}>
                {label}
              </NavLink>
            ))}
          </nav>
        </header>
        <SafetyBanner />
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/risk" element={<Risk />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/extensions" element={<Extensions />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
