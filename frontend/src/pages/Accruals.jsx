import { useCallback, useEffect, useState } from 'react';
import { api, fmt } from '../api.js';
import { Message, accountName } from '../components.jsx';

export default function Accruals({ chart, reloadChart }) {
  const [drafts, setDrafts] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');

  const load = useCallback(() => {
    api.get('/accruals/drafts').then((d) => {
      setDrafts(d);
      setSelected((s) => new Set([...s].filter((id) => d.some((x) => x.transact === id))));
    }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function run(fn, message) {
    setError(''); setOk('');
    try { await fn(); setOk(message); await load(); reloadChart(); }
    catch (err) { setError(err.message); }
  }

  const toggle = (id) => setSelected((s) => {
    const next = new Set(s);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  return (
    <section>
      <h2>Accrual Drafts</h2>
      <p className="muted">
        Drafts do not affect the ledger or reports until you post them. Create them from the Journal tab
        by ticking “Accrual”.
      </p>
      <div className="toolbar">
        <button className="primary" disabled={selected.size === 0}
          onClick={() => run(() => api.post('/accruals/post-selected', { transacts: [...selected] }),
            `Posted ${selected.size} entr${selected.size === 1 ? 'y' : 'ies'}.`)}>
          Post selected ({selected.size})
        </button>
        <button className="link" onClick={() => setSelected(selected.size === drafts.length ? new Set() : new Set(drafts.map((d) => d.transact)))}>
          {selected.size === drafts.length && drafts.length > 0 ? 'Clear selection' : 'Select all'}
        </button>
      </div>
      <Message error={error} ok={ok} />
      <table>
        <thead><tr><th></th><th>#</th><th>Date</th><th>Description</th><th>Debit</th><th>Credit</th><th className="num">Amount</th><th></th></tr></thead>
        <tbody>
          {drafts.map((d) => (
            <tr key={d.transact}>
              <td><input type="checkbox" checked={selected.has(d.transact)} onChange={() => toggle(d.transact)}
                aria-label={`Select entry ${d.transact}`} /></td>
              <td>{d.transact}</td><td>{d.date}</td><td>{d.description}</td>
              <td>{accountName(chart, d.debit_account)}</td><td>{accountName(chart, d.credit_account)}</td>
              <td className="num">{fmt(d.amount)}</td>
              <td>
                <button className="link" onClick={() => run(() => api.post(`/accruals/drafts/${d.transact}/post`), `Entry ${d.transact} posted.`)}>Post</button>
                <button className="link danger" onClick={() => run(() => api.del(`/accruals/drafts/${d.transact}`), `Entry ${d.transact} discarded.`)}>Discard</button>
              </td>
            </tr>
          ))}
          {drafts.length === 0 && <tr><td colSpan="8" className="muted">No drafts waiting for approval.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
