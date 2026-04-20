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
          <h1>交易控制台</h1>
          <nav className="main-nav">
            {[
              { to: '/', label: '总览' },
              { to: '/signals', label: '信号' },
              { to: '/orders', label: '订单' },
              { to: '/risk', label: '风控' },
              { to: '/analytics', label: '分析' },
              { to: '/extensions', label: '扩展' },
              { to: '/logs', label: '日志' },
              { to: '/settings', label: '设置' },
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
