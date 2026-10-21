import { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';
import Journal from './pages/Journal.jsx';
import Ledger from './pages/Ledger.jsx';
import Chart from './pages/Chart.jsx';
import Reports from './pages/Reports.jsx';
import Memos from './pages/Memos.jsx';
import Recurring from './pages/Recurring.jsx';
import Accruals from './pages/Accruals.jsx';

const TABS = [
  ['journal', 'Journal', Journal],
  ['ledger', 'Ledger', Ledger],
  ['chart', 'Chart of Accounts', Chart],
  ['reports', 'Reports', Reports],
  ['accruals', 'Accruals', Accruals],
  ['recurring', 'Recurring', Recurring],
  ['memos', 'Memos', Memos],
];

export default function App() {
  const [tab, setTab] = useState('journal');
  const [chart, setChart] = useState([]);
  const [error, setError] = useState('');

  const reloadChart = useCallback(
    () => api.get('/chart').then(setChart).catch((e) => setError(e.message)),
    [],
  );
  // Balances change whenever entries are posted, so refresh the chart each time the user switches tabs.
  useEffect(() => { reloadChart(); }, [reloadChart, tab]);

  const Page = TABS.find(([id]) => id === tab)[2];
  return (
    <div className="app">
      <header>
        <h1>Open Accounting</h1>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} className={id === tab ? 'tab active' : 'tab'} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      <main>
        <Page chart={chart} reloadChart={reloadChart} />
      </main>
    </div>
  );
}
