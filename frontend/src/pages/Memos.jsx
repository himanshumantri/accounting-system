import { useCallback, useEffect, useState } from 'react';
import { api, today } from '../api.js';
import { Message } from '../components.jsx';

export default function Memos() {
  const [transact, setTransact] = useState('');
  const [memo, setMemo] = useState('');
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    const q = transact ? `?transact=${Number(transact)}` : '';
    api.get(`/memos${q}`).then(setRows).catch((e) => setError(e.message));
  }, [transact]);
  useEffect(() => { load(); }, [load]);

  async function submit(e) {
    e.preventDefault();
    setError('');
    try {
      await api.post('/memos', { transact: Number(transact), memo, memo_date: today() });
      setMemo('');
      load();
    } catch (err) { setError(err.message); }
  }

  return (
    <section>
      <h2>Accounting Memos</h2>
      <form className="grid" onSubmit={submit}>
        <label>Journal entry #<input type="number" min="1" required value={transact}
          onChange={(e) => setTransact(e.target.value)} /></label>
        <label style={{ gridColumn: 'span 2' }}>Memo
          <textarea required rows={2} value={memo} onChange={(e) => setMemo(e.target.value)} /></label>
        <div><button className="primary" type="submit">Add memo</button></div>
      </form>
      <Message error={error} />
      <table>
        <thead><tr><th>Entry #</th><th>Date</th><th>Memo</th></tr></thead>
        <tbody>
          {rows.map((r) => <tr key={r.memo_id}><td>{r.transact}</td><td>{r.memo_date}</td><td>{r.memo}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan="3" className="muted">No memos.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
