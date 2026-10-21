import { useState } from 'react';
import { api, fmt } from '../api.js';
import { Message } from '../components.jsx';

export default function Chart({ chart, reloadChart }) {
  const [form, setForm] = useState({ account: '', name: '', type: 'DEBIT' });
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const input = (k) => ({ value: form[k], onChange: (e) => setForm((f) => ({ ...f, [k]: e.target.value })) });

  async function submit(e) {
    e.preventDefault();
    setError(''); setOk('');
    try {
      await api.post('/chart', { account: Number(form.account), name: form.name, type: form.type });
      setOk(`Account ${form.account} added.`);
      setForm({ account: '', name: '', type: 'DEBIT' });
      reloadChart();
    } catch (err) { setError(err.message); }
  }

  return (
    <section>
      <h2>Chart of Accounts</h2>
      <form className="grid" onSubmit={submit}>
        <label>Account (100-699)<input type="number" min="100" max="699" required {...input('account')} /></label>
        <label>Name<input required maxLength={60} {...input('name')} /></label>
        <label>Normal side
          <select {...input('type')}><option>DEBIT</option><option>CREDIT</option></select>
        </label>
        <div><button className="primary" type="submit">Add account</button></div>
      </form>
      <p className="muted">New accounts open at zero. Record opening balances with a journal entry.</p>
      <Message error={error} ok={ok} />
      <table>
        <thead><tr><th>Account</th><th>Name</th><th>Type</th><th className="num">Balance</th></tr></thead>
        <tbody>
          {chart.map((a) => (
            <tr key={a.account}>
              <td>{a.account}</td><td>{a.name}</td><td>{a.type}</td><td className="num">{fmt(a.balance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
