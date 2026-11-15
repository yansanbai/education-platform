import {useEffect, useState} from 'react';

export const labels = {queued:'排队中', running:'批改中', done:'已完成', failed:'失败'} as const;
export type Status = keyof typeof labels;
export type Task = {id:number; title:string; status:Status; started_at:number|null; stage:number|null; progress:number; stage_label:string|null};
export type TaskDetail = Task & {result:string|null; error:string|null; has_document:boolean};
export type Report = {
  demo?:boolean;
  summary?:string;
  questions:{number:string; part?:string; verdict:string; student_answer?:string; correct_answer?:string; feedback:string}[];
  unlinked?:{record_id:string; photo:number; evidence:string; steps:string[]; final:string}[];
  coverage_warnings?:{number:string; part?:string; evidence:string}[];
  exercises:{source:string; question:string; options?:string[]; answer:string; solution?:string; image?:number; images?:number[]}[];
};
export type TaskList = {tasks:Task[]; demo:boolean; configured:boolean; seedream_configured:boolean};
export const link = (id:number) => '#/tasks/' + id;
const timeFormat = new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short',hour12:false});
export const taskTime = (time:number|null) => time ? timeFormat.format(new Date(time*1000)) : '—';
export const questionNumber = (item:{number:string; part?:string}) => item.number + (item.part ? '（'+item.part.replace(/^[（(]|[）)]$/g,'')+'）' : '');

class ApiError extends Error {
  constructor(message:string, readonly status:number) { super(message); }
}

export async function api<T>(path = '', options?:RequestInit):Promise<T> {
  const response = await fetch('/api/tasks' + path, options);
  const data = await response.json();
  if (!response.ok) {
    throw new ApiError(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入。', response.status);
  }
  return data;
}

export function usePolling<T>(path:string, revision:number) {
  const [state,setState] = useState<{data?:T; error?:string; missing?:boolean}>({});
  useEffect(() => {
    let active = true;
    let timer:ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function load() {
      try {
        const data = await api<T>(path, {signal:controller.signal});
        if (active) setState({data});
      } catch (error) {
        if (active) setState(old => ({...old,error:(error as Error).message,missing:error instanceof ApiError && error.status === 404}));
      } finally {
        if (active) timer = setTimeout(load, 1800);
      }
    }
    void load();
    return () => {active = false; controller.abort(); clearTimeout(timer);};
  },[path,revision]);
  return state;
}

