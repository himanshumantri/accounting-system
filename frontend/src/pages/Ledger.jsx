import { useEffect, useState } from 'react';
import { api, fmt } from '../api.js';
import { AccountSelect, Message } from '../components.jsx';

export default function Ledger({ chart }) {
  const [account, setAccount] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setError('');
    if (!account) { setData(null); return; }
    api.get(`/ledger/${account}`).then(setData).catch((e) => setError(e.message));
  }, [account]);

  return (
    <section>
      <h2>General Ledger</h2>
      <div className="toolbar">
        <AccountSelect chart={chart} value={account} onChange={setAccount} />
        {data && <span className="muted">{data.type} account</span>}
      </div>
      <Message error={error} />
      {data && (
        <table>
          <thead><tr><th>#</th><th>Date</th><th>Description</th><th className="num">Amount</th><th className="num">Balance</th></tr></thead>
          <tbody>
            {data.entries.map((e, i) => (
              <tr key={i}>
                <td>{e.transact}</td><td>{e.date}</td><td>{e.description}</td>
                <td className="num">{fmt(e.amount)}</td><td className="num">{fmt(e.balance)}</td>
              </tr>
            ))}
            {data.entries.length === 0 && <tr><td colSpan="5" className="muted">No postings.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
