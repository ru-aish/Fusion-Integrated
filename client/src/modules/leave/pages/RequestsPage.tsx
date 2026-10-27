import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { errorMessage, http } from "../../../lib/http";

type LeaveRequest = {
  id: number;
  leave_type: string;
  start_date: string;
  end_date: string;
  reason: string;
  half_day: "none" | "first" | "second";
  station_leave: boolean;
  station_leave_details: string;
  medical_evidence_reference: string;
  status: string;
  workflow_state: string;
  substitute_id: string;
  substitute_replacement_used: boolean;
};
type Page<T> = { results: T[] };
type Transition = { actor_id:string; action:string; from_state:string; to_state:string; note:string; created_at:string };

function HistoryDetails({id}:{id:number}) {
  const history=useQuery({queryKey:["leave-cell","history",id],queryFn:async()=>(await http.get<Transition[]>(`/leave/requests/${id}/history/`)).data,enabled:false});
  return <details onToggle={e=>{if((e.currentTarget as HTMLDetailsElement).open) void history.refetch();}}><summary>Decision history</summary>
    {history.isError&&<p role="alert">{errorMessage(history.error)}</p>}{history.isPending&&!history.data&&<p>Loading history…</p>}
    {history.data?.map((event,index)=><p key={`${event.created_at}-${index}`}>{new Date(event.created_at).toLocaleString()}: {event.action} ({event.from_state} → {event.to_state}){event.note&&` — ${event.note}`}</p>)}
  </details>;
}

export default function RequestsPage() {
  const client = useQueryClient();
  const [leaveType, setLeaveType] = useState("CL");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");
  const [halfDay, setHalfDay] = useState<LeaveRequest["half_day"]>("none");
  const [stationLeave, setStationLeave] = useState(false);
  const [stationLeaveDetails, setStationLeaveDetails] = useState("");
  const [medicalEvidenceReference, setMedicalEvidenceReference] = useState("");
  const [substituteId, setSubstituteId] = useState("");
  const [replacement, setReplacement] = useState<Record<number, string>>({});
  const requests = useQuery({
    queryKey: ["leave-cell", "requests"],
    queryFn: async () => (await http.get<Page<LeaveRequest>>("/leave/requests/")).data.results,
  });
  const create = useMutation({
    mutationFn: async (data: Omit<LeaveRequest,
      "id" | "status" | "workflow_state" | "substitute_replacement_used">) =>
      (await http.post<LeaveRequest>("/leave/requests/", data)).data,
    onSuccess: () => {
      setReason("");
      setHalfDay("none");
      setStationLeave(false);
      setStationLeaveDetails("");
      setMedicalEvidenceReference("");
      setSubstituteId("");
      client.invalidateQueries({ queryKey: ["leave-cell", "requests"] });
    },
  });
  const act = useMutation({ mutationFn: async ({ id, action, substitute_id }: {
    id: number; action: string; substitute_id?: string }) =>
    http.post(`/leave/requests/${id}/act/`, { action, substitute_id }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["leave-cell"] }) });
  const cancelLeave = useMutation({ mutationFn: async (id: number) =>
    http.post(`/leave/requests/${id}/cancel/`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["leave-cell"] }) });
  const extendLeave = useMutation({ mutationFn: async ({ id, end }: { id: number; end: string }) => {
    const row = requests.data?.find((item) => item.id === id);
    if (!row) throw new Error("Leave request was not found.");
    const nextDay = new Date(`${row.end_date}T00:00:00`);
    nextDay.setDate(nextDay.getDate() + 1);
    const start = `${nextDay.getFullYear()}-${String(nextDay.getMonth() + 1).padStart(2, "0")}-${String(nextDay.getDate()).padStart(2, "0")}`;
    const medical_evidence_reference = row.leave_type === "COL"
      ? window.prompt("Medical evidence reference (if required)") ?? ""
      : "";
    return http.post(`/leave/requests/${id}/extend/`, { leave_type: row.leave_type,
      start_date: start, end_date: end, reason: "Extension", half_day: "none",
      station_leave: false, station_leave_details: "", medical_evidence_reference, substitute_id: "" });
  }, onSuccess: () => client.invalidateQueries({ queryKey: ["leave-cell"] }) });
  const resumeLeave = useMutation({ mutationFn: async ({ id, actual_return_date }: {
    id: number; actual_return_date: string }) =>
    http.post(`/leave/requests/${id}/resume/`, { actual_return_date }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["leave-cell"] }) });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate({ leave_type: leaveType, start_date: startDate, end_date: endDate,
      reason, half_day: halfDay, station_leave: stationLeave,
      station_leave_details: stationLeaveDetails, medical_evidence_reference: medicalEvidenceReference,
      substitute_id: substituteId });
  }

  return <main>
    <h1>Leave Requests</h1>
    <form onSubmit={submit}>
      <label>Leave type <select value={leaveType} onChange={(e) => {
        setLeaveType(e.target.value); if (e.target.value !== "CL") setHalfDay("none");
      }}>
        <option value="CL">Casual Leave</option><option value="RH">Restricted Holiday</option>
        <option value="SCL">Special Casual Leave</option><option value="EL">Earned Leave</option>
        <option value="COL">Compensatory Off</option><option value="VL">Vacation Leave</option>
      </select></label>{" "}
      <label>From <input required type="date" value={startDate}
        onChange={(e) => setStartDate(e.target.value)} /></label>{" "}
      <label>To <input required type="date" value={endDate}
        onChange={(e) => setEndDate(e.target.value)} /></label>{" "}
      <label>Reason <input value={reason} onChange={(e) => setReason(e.target.value)} /></label>{" "}
      {leaveType === "COL" && <label>Medical evidence reference (if required) <input
        maxLength={255} value={medicalEvidenceReference}
        onChange={(e) => setMedicalEvidenceReference(e.target.value)} /></label>}{" "}
      {leaveType === "CL" && <label>Day portion <select value={halfDay}
        onChange={(e) => setHalfDay(e.target.value as LeaveRequest["half_day"])}>
        <option value="none">Full day(s)</option><option value="first">First half</option>
        <option value="second">Second half</option>
      </select></label>}{" "}
      <label><input type="checkbox" checked={stationLeave}
        onChange={(e) => setStationLeave(e.target.checked)} /> Station Leave</label>{" "}
      {stationLeave && <label>Station Leave details <input required maxLength={500}
        value={stationLeaveDetails} onChange={(e) => setStationLeaveDetails(e.target.value)} />
      </label>}{" "}
      <label>Substitute ID (if required) <input value={substituteId}
        onChange={(e) => setSubstituteId(e.target.value)} /></label>{" "}
      <button type="submit" disabled={create.isPending}>Submit request</button>
    </form>
    {create.isError && <p role="alert">{errorMessage(create.error)}</p>}
    {requests.isPending && <p>Loading requests…</p>}
    {requests.isError && <p role="alert">{errorMessage(requests.error)}</p>}
    {act.isError && <p role="alert">{errorMessage(act.error)}</p>}
    {cancelLeave.isError && <p role="alert">{errorMessage(cancelLeave.error)}</p>}
    {extendLeave.isError && <p role="alert">{errorMessage(extendLeave.error)}</p>}
    {resumeLeave.isError && <p role="alert">{errorMessage(resumeLeave.error)}</p>}
    {requests.data && <table>
      <thead><tr><th>Type</th><th>From</th><th>To</th><th>Reason</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>{requests.data.map((row) => <tr key={row.id}>
        <td>{row.leave_type}</td><td>{row.start_date}</td><td>{row.end_date}</td>
        <td>{row.reason}</td><td>{row.workflow_state}</td><td>
          {!["approved", "rejected", "withdrawn"].includes(row.workflow_state) &&
            <button onClick={() => act.mutate({ id: row.id, action: "withdraw" })}>Withdraw</button>}
          {row.workflow_state === "approved" && <button
            onClick={() => cancelLeave.mutate(row.id)}>Request cancellation</button>}
          {row.workflow_state === "approved" && ["EL", "COL", "VL"].includes(row.leave_type) && <>
            <button onClick={() => {
              const end = window.prompt("Extension end date (YYYY-MM-DD)");
              if (end) extendLeave.mutate({ id: row.id, end });
            }}>Request extension</button>
            <button onClick={() => {
              const actual_return_date = window.prompt("Actual return date (YYYY-MM-DD)");
              if (actual_return_date) resumeLeave.mutate({ id: row.id, actual_return_date });
            }}>Submit resumption</button>
          </>}
          {row.workflow_state === "applicant_action_required" && <>
            <input aria-label="Replacement substitute ID" value={replacement[row.id] ?? ""}
              onChange={(e) => setReplacement({ ...replacement, [row.id]: e.target.value })} />
            <button onClick={() => act.mutate({ id: row.id, action: "replace_substitute",
              substitute_id: replacement[row.id] })}>Nominate replacement</button>
          </>}
          <HistoryDetails id={row.id}/>
          {" "}<a href={`/api/v1/leave/requests/${row.id}/export/`} target="_blank" rel="noreferrer">Export JSON</a>
          {" "}<button type="button" onClick={() => window.print()}>Print application</button>
        </td>
      </tr>)}</tbody>
    </table>}
  </main>;
}
