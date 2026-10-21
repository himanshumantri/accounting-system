import { useEffect, useState } from 'react';
import { api, fmt } from '../api.js';
import { Message } from '../components.jsx';

function Block({ title, rows, total, totalLabel }) {
  return (
    <div>
      <h3>{title}</h3>
      <table>
        <thead><tr><th>Account</th><th>Name</th><th className="num">Balance</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.account}><td>{r.account}</td><td>{r.name} {r.contra && <span className="badge">contra</span>}</td><td className="num">{fmt(r.balance)}</td></tr>
          ))}
          <tr className="total"><td colSpan="2">{totalLabel || 'Total'}</td><td className="num">{fmt(total)}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function TrialBalance({ d }) {
  return (
    <>
      <div className="cols">
        <Block title="Debits" rows={d.debits} total={d.total_debits} totalLabel="Total debits" />
        <Block title="Credits" rows={d.credits} total={d.total_credits} totalLabel="Total credits" />
      </div>
      {d.balanced ? <p className="ok">Debits equal credits.</p> : <p className="error">Out of balance!</p>}
      {d.mismatches.length > 0 && (
        <p className="error">Chart balances differ from the ledger for accounts: {d.mismatches.join(', ')}</p>
      )}
    </>
  );
}

function IncomeStatement({ d }) {
  return (
    <>
      <div className="cols">
        <Block title="Revenue" rows={d.revenue} total={d.total_revenue} totalLabel="Total revenue" />
        <Block title="Expenses" rows={d.expenses} total={d.total_expenses} totalLabel="Total expenses" />
      </div>
      <p><strong>Net income: {fmt(d.net_income)}</strong></p>
    </>
  );
}

function BalanceSheet({ d }) {
  return (
    <>
      <div className="cols">
        <Block title="Assets" rows={d.assets} total={d.total_assets} totalLabel="Total assets" />
        <div>
          <Block title="Liabilities" rows={d.liabilities} total={d.total_liabilities} totalLabel="Total liabilities" />
          <Block title="Equity" rows={d.equity} total={d.total_equity} totalLabel="Total equity" />
        </div>
      </div>
      {d.balanced ? <p className="ok">Assets equal liabilities plus equity.</p> : <p className="error">Out of balance!</p>}
    </>
  );
}

const REPORTS = {
  'trial-balance': ['Trial Balance', TrialBalance],
  'balance-sheet': ['Balance Sheet', BalanceSheet],
  'income-statement': ['Revenue & Expense Statement', IncomeStatement],
};

export default function Reports() {
  const [which, setWhich] = useState('trial-balance');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setData(null); setError('');
    api.get(`/reports/${which}`).then(setData).catch((e) => setError(e.message));
  }, [which]);

  const View = REPORTS[which][1];
  return (
    <section>
      <h2>Reports</h2>
      <div className="toolbar">
        <select value={which} onChange={(e) => setWhich(e.target.value)}>
          {Object.entries(REPORTS).map(([id, [label]]) => <option key={id} value={id}>{label}</option>)}
        </select>
        <span className="muted">Posted entries only; drafts are excluded.</span>
      </div>
      <Message error={error} />
      {data && <View d={data} />}
    </section>
  );
}
