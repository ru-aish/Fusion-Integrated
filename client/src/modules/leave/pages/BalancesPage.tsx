import { useQuery } from "@tanstack/react-query";

import { errorMessage, http } from "../../../lib/http";

type Balance = { employee_id: string; leave_type: string; balance: string;
  available_balance: string; last_updated: string };
type Page<T> = { results: T[] };
type Account = { employee_id:string; leave_type:string; year:number; opening_balance:string; available_balance:string; source:string; reconciled:boolean };

export default function BalancesPage() {
  const balances = useQuery({
    queryKey: ["leave-cell", "balances"],
    queryFn: async () => (await http.get<Page<Balance>>("/leave/balances/")).data.results,
  });
  const accounts=useQuery({queryKey:["leave-cell","accounts"],queryFn:async()=>(await http.get<Account[]>("/leave/accounts/")).data});

  return <main>
    <h1>Leave Balances</h1>
    {balances.isPending && <p>Loading balances…</p>}
    {balances.isError && <p role="alert">{errorMessage(balances.error)}</p>}
    {accounts.isError && <p role="alert">{errorMessage(accounts.error)}</p>}
    {accounts.data?.length ? <table><thead><tr><th>Year</th><th>Category</th><th>Opening</th><th>Available</th><th>Ledger check</th></tr></thead><tbody>{accounts.data.map(row=><tr key={`${row.year}-${row.leave_type}`}><td>{row.year}</td><td>{row.leave_type}</td><td>{row.opening_balance}</td><td>{row.available_balance}</td><td>{row.reconciled ? "Reconciled" : "Review account ledger"}</td></tr>)}</tbody></table> : balances.data && (balances.data.length ? <table>
      <thead><tr><th>Leave type</th><th>Available</th><th>Updated</th></tr></thead>
      <tbody>{balances.data.map((row) => <tr key={row.leave_type}>
        <td>{row.leave_type}</td><td>{row.available_balance}</td>
        <td>{new Date(row.last_updated).toLocaleDateString()}</td>
      </tr>)}</tbody>
    </table> : <p>No leave balances are available yet.</p>)}
  </main>;
}
