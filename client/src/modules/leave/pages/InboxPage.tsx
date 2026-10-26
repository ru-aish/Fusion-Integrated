import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorMessage, http } from "../../../lib/http";

type Task = { task_id: number; request_id: number; role: string; workflow_state: string;
  leave_type: string; start_date: string; end_date: string };

export default function InboxPage() {
  const client = useQueryClient();
  const tasks = useQuery({ queryKey: ["leave-cell", "inbox"],
    queryFn: async () => (await http.get<Task[]>("/leave/inbox/")).data });
  const act = useMutation({ mutationFn: async ({ id, action }: { id: number; action: string }) =>
    http.post(`/leave/requests/${id}/act/`, { action }), onSuccess: () => {
      client.invalidateQueries({ queryKey: ["leave-cell"] });
    } });
  return <main><h1>Leave Approvals</h1>
    {tasks.isError && <p role="alert">{errorMessage(tasks.error)}</p>}
    {act.isError && <p role="alert">{errorMessage(act.error)}</p>}
    {tasks.data?.map((task) => <section key={task.task_id}>
      <h2>{task.leave_type}: {task.start_date} to {task.end_date}</h2>
      <p>Assigned as {task.role}; state: {task.workflow_state}</p>
      {task.role === "substitute" && <>
        <button onClick={() => act.mutate({ id: task.request_id, action: "accept" })}>Accept</button>{" "}
        <button onClick={() => act.mutate({ id: task.request_id, action: "decline" })}>Decline</button>
      </>}
      {task.role === "unit_head" && task.leave_type in { CL: 1, RH: 1 } && <>
        <button onClick={() => act.mutate({ id: task.request_id, action: "approve" })}>Approve</button>{" "}
        <button onClick={() => act.mutate({ id: task.request_id, action: "reject" })}>Reject</button>
      </>}
      {task.role === "unit_head" && !(task.leave_type in { CL: 1, RH: 1 }) && <>
        <button onClick={() => act.mutate({ id: task.request_id, action: "recommend" })}>Recommend</button>{" "}
        <button onClick={() => act.mutate({ id: task.request_id, action: "not_recommend" })}>Do not recommend</button>
      </>}
      {task.role === "establishment" && <button onClick={() => act.mutate({ id: task.request_id, action: "route" })}>Route to authority</button>}
      {task.role === "authority" && <>
        {task.workflow_state === "resumption_review_pending"
          ? <button onClick={() => act.mutate({ id: task.request_id, action: "review_resumption" })}>Review and synchronize</button>
          : <>
            <button onClick={() => act.mutate({ id: task.request_id, action: "approve" })}>Approve</button>{" "}
            <button onClick={() => act.mutate({ id: task.request_id, action: "reject" })}>Reject</button>
          </>}
      </>}
    </section>)}
  </main>;
}
