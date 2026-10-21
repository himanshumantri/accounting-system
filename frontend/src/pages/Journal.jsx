import { useCallback, useEffect, useState } from 'react';
import { api, fmt, today } from '../api.js';
import { AccountSelect, Message, accountName } from '../components.jsx';

const ACCRUAL_TYPES = [
  ['accrued_expense', 'Accrued expense (incurred, not yet paid)'],
  ['accrued_revenue', 'Accrued revenue (earned, not yet billed)'],
  ['prepaid_expense', 'Prepaid expense (paid up front, spread over months)'],
  ['deferred_revenue', 'Deferred revenue (received up front, spread over months)'],
];

const HINTS = {
  accrued_expense: 'Debit = the expense account. Credit is optional (defaults to 230 Accrued Expenses).',
  accrued_revenue: 'Credit = the revenue account. Debit is optional (defaults to 135 Accrued Revenue).',
  prepaid_expense: 'Debit = the prepaid asset (e.g. 130), credit = where the cash came from. This entry and the monthly entries are all created as drafts.',
  deferred_revenue: 'Debit = where the cash went, credit = the deferred revenue liability (e.g. 240). This entry and the monthly entries are all created as drafts.',
};

const blankForm = () => ({
  entry_date: today(), description: '', amount: '', debit_account: '', credit_account: '',
  accrual: false, type: 'accrued_expense', recognition_account: '', period_end: today(),
  months: '12', auto_reverse: false,
});

export default function Journal({ chart }) {
  const [form, setForm] = useState(blankForm);
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState('all');
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const input = (k) => ({ value: form[k], onChange: (e) => set(k)(e.target.value) });

  const load = useCallback(
    () => api.get(`/journal?status=${status}`).then(setRows).catch((e) => setError(e.message)),
    [status],
  );
  useEffect(() => { load(); }, [load]);

  const periodType = form.type === 'prepaid_expense' || form.type === 'deferred_revenue';

  async function submit(e) {
    e.preventDefault();
    setError(''); setOk('');
    const body = {
      entry_date: form.entry_date, description: form.description, amount: form.amount,
      debit_account: form.debit_account ? Number(form.debit_account) : null,
      credit_account: form.credit_account ? Number(form.credit_account) : null,
    };
    if (form.accrual) {
      body.accrual = {
        type: form.type,
        auto_reverse: form.auto_reverse && !periodType,
        recognition_account: periodType && form.recognition_account ? Number(form.recognition_account) : null,
        period_end: periodType ? null : form.period_end,
        months: periodType ? Number(form.months) : null,
      };
    }
    try {
      const res = await api.post('/journal', body);
      setOk(form.accrual
        ? `Created ${res.draft_transacts.length} draft entr${res.draft_transacts.length === 1 ? 'y' : 'ies'}. Review them in the Accruals tab.`
        : `Entry ${res.transact} posted.`);
      setForm(blankForm());
      load();
    } catch (err) { setError(err.message); }
  }

  return (
    <section>
      <h2>Journal</h2>
      <form className="grid" onSubmit={submit}>
        <label>Date<input type="date" required {...input('entry_date')} /></label>
        <label>Description<input required maxLength={200} {...input('description')} /></label>
        <label>Amount<input required inputMode="decimal" placeholder="0.00" {...input('amount')} /></label>
        <label>Debit account
          <AccountSelect chart={chart} value={form.debit_account} onChange={set('debit_account')}
            required={!form.accrual} blank={form.accrual ? '(default)' : undefined} />
        </label>
        <label>Credit account
          <AccountSelect chart={chart} value={form.credit_account} onChange={set('credit_account')}
            required={!form.accrual} blank={form.accrual ? '(default)' : undefined} />
        </label>
        <label className="check">
          <input type="checkbox" checked={form.accrual} onChange={(e) => set('accrual')(e.target.checked)} />
          Accrual
        </label>
        {form.accrual && (
          <>
            <label>Accrual type
              <select {...input('type')}>
                {ACCRUAL_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            {periodType ? (
              <>
                <label>Recognition account
                  <AccountSelect chart={chart} value={form.recognition_account}
                    onChange={set('recognition_account')} required />
                </label>
                <label>Months<input type="number" min="1" max="120" required {...input('months')} /></label>
              </>
            ) : (
              <>
                <label>Period end<input type="date" required {...input('period_end')} /></label>
                <label className="check">
                  <input type="checkbox" checked={form.auto_reverse}
                    onChange={(e) => set('auto_reverse')(e.target.checked)} />
                  Auto-reverse next day
                </label>
              </>
            )}
            <p className="muted" style={{ gridColumn: '1 / -1', margin: 0 }}>{HINTS[form.type]}</p>
          </>
        )}
        <div><button className="primary" type="submit">{form.accrual ? 'Create drafts' : 'Post entry'}</button></div>
      </form>
      <Message error={error} ok={ok} />

      <div className="toolbar">
        <strong>Entries</strong>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">All</option><option value="posted">Posted</option><option value="draft">Drafts</option>
        </select>
      </div>
      <table>
        <thead>
          <tr><th>#</th><th>Date</th><th>Description</th><th>Debit</th><th>Credit</th><th className="num">Amount</th><th></th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.transact}>
              <td>{r.transact}</td><td>{r.date}</td><td>{r.description}</td>
              <td>{accountName(chart, r.debit_account)}</td><td>{accountName(chart, r.credit_account)}</td>
              <td className="num">{fmt(r.amount)}</td>
              <td>{!r.posted && <span className="badge draft">draft</span>}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan="7" className="muted">No entries yet.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
