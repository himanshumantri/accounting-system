import { useCallback, useEffect, useState } from 'react';
import { api, fmt, today } from '../api.js';
import { AccountSelect, Message, accountName } from '../components.jsx';

const blank = () => ({ description: '', debit_account: '', credit_account: '', amount: '',
                       frequency: 'monthly', first_run: today(), end_date: '' });

export default function Recurring({ chart }) {
  const [form, setForm] = useState(blank);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const input = (k) => ({ value: form[k], onChange: (e) => set(k)(e.target.value) });

  const load = useCallback(() => api.get('/recurring').then(setRows).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function submit(e) {
    e.preventDefault();
    setError(''); setOk('');
    try {
      await api.post('/recurring', {
        ...form, debit_account: Number(form.debit_account), credit_account: Number(form.credit_account),
        end_date: form.end_date || null,
      });
      setForm(blank());
      load();
    } catch (err) { setError(err.message); }
  }

  async function toggle(r) {
    setError('');
    try { await api.post(`/recurring/${r.id}/active`, { active: !r.active }); load(); }
    catch (err) { setError(err.message); }
  }

  async function runNow() {
    setError(''); setOk('');
    try {
      const res = await api.post('/recurring/run-now');
      setOk(`Posted ${res.posted.length} entr${res.posted.length === 1 ? 'y' : 'ies'}.`);
      if (res.errors.length) setError(res.errors.map((x) => `#${x.recurring_id}: ${x.error}`).join('; '));
      load();
    } catch (err) { setError(err.message); }
  }

  return (
    <section>
      <h2>Recurring Entries</h2>
      <form className="grid" onSubmit={submit}>
        <label>Description<input required maxLength={200} {...input('description')} /></label>
        <label>Debit account<AccountSelect chart={chart} value={form.debit_account} onChange={set('debit_account')} required /></label>
        <label>Credit account<AccountSelect chart={chart} value={form.credit_account} onChange={set('credit_account')} required /></label>
        <label>Amount<input required inputMode="decimal" placeholder="0.00" {...input('amount')} /></label>
        <label>Frequency
          <select {...input('frequency')}><option value="monthly">Monthly</option><option value="weekly">Weekly</option></select>
        </label>
        <label>First run<input type="date" required {...input('first_run')} /></label>
        <label>End date (optional)<input type="date" {...input('end_date')} /></label>
        <div><button className="primary" type="submit">Add</button></div>
      </form>
      <div className="toolbar">
        <button className="primary" onClick={runNow}>Run due now</button>
        <span className="muted">Posts every entry that is due, including any missed periods.</span>
      </div>
      <Message error={error} ok={ok} />
      <table>
        <thead><tr><th>Description</th><th>Debit</th><th>Credit</th><th className="num">Amount</th><th>Every</th><th>Next run</th><th>Ends</th><th></th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={r.active ? '' : 'muted'}>
              <td>{r.description}</td><td>{accountName(chart, r.debit_account)}</td>
              <td>{accountName(chart, r.credit_account)}</td><td className="num">{fmt(r.amount)}</td>
              <td>{r.frequency}</td><td>{r.next_run}</td><td>{r.end_date || '—'}</td>
              <td><button className="link" onClick={() => toggle(r)}>{r.active ? 'Pause' : 'Resume'}</button></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan="8" className="muted">No recurring entries.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
