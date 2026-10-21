export function AccountSelect({ chart, value, onChange, blank, required }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} required={required}>
      <option value="">{blank || 'Select account…'}</option>
      {chart.map((a) => (
        <option key={a.account} value={a.account}>{a.account} {a.name}</option>
      ))}
    </select>
  );
}

export function accountName(chart, number) {
  const a = chart.find((x) => x.account === number);
  return a ? `${a.account} ${a.name}` : String(number);
}

export function Message({ error, ok }) {
  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      {ok && <p className="ok">{ok}</p>}
    </>
  );
}
