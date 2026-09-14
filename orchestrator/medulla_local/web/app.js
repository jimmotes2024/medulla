'use strict';

const $ = id => document.getElementById(id);
const state = {data: null, project: null, task: null, view: 'work', signedIn: false, pendingAction: null, workerKey: null};
const labels = {queued:'Queued', claimed:'Claimed', delivered:'Delivered', running:'Working', review:'Ready for review',
  completed:'Accepted', awaiting_approval:'Needs approval', failed:'Failed', cancelled:'Cancelled', interrupted:'Interrupted', changes_requested:'Changes requested'};
const attention = ['review','awaiting_approval','interrupted','failed','changes_requested'];
let listKey = '', detailKey = '', eventKey = '';

function node(tag, className, value) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (value !== undefined) result.textContent = value;
  return result;
}
function button(label, action, className = 'secondary') {
  const result = node('button', className, label);
  result.type = 'button'; result.addEventListener('click', action); return result;
}
function badge(status) { return node('span', 'badge ' + status, labels[status] || status); }
function when(seconds) { return new Date(seconds * 1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
function name(id) { return state.data.agents.find(a => a.id === id)?.name || (id === 'operator' ? 'Operator' : id === 'coordinator' ? 'Coordinator' : id); }
function notice(message, type = 'success') { $('notice').hidden = false; $('notice').className = type; $('notice').textContent = message; }
function lock() { state.signedIn = false; $('workspace').hidden = true; $('login').hidden = false; }

async function api(path, data) {
  const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST', credentials:'same-origin',
    headers: data === undefined ? {} : {'Content-Type':'application/json'}, body:data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/session') lock();
    throw new Error(result.error || 'Request failed');
  }
  return result;
}
async function refresh() {
  try {
    state.data = await api('/api/state'); state.signedIn = true;
    $('login').hidden = true; $('workspace').hidden = false;
    $('connection').textContent = 'Local · connected'; $('version').textContent = 'v' + state.data.version;
    render();
  } catch (error) { if (state.signedIn) { $('connection').textContent = 'Connection lost'; notice('The coordinator is unavailable. Displayed records may be stale.', 'error'); } }
}
function render() {
  const data = state.data;
  $('page-title').textContent = state.view === 'work' ? data.projects.find(p => p.id === state.project)?.name || 'All projects' : state.view === 'agents' ? 'Agent registry' : 'Activity';
  $('pause').textContent = data.paused ? 'Resume dispatch' : 'Pause dispatch'; $('paused-banner').hidden = !data.paused;
  $('nav-work-count').textContent = data.tasks.filter(t => !['completed','cancelled'].includes(t.state)).length;
  $('nav-agent-count').textContent = data.agents.length;
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('selected', b.dataset.view === state.view));
  ['work','agents','activity'].forEach(v => $(v + '-view').hidden = v !== state.view);
  renderProjects(); renderWork(); renderAgents(); renderEvents();
}
function renderProjects() {
  const list = $('project-list');
  const items = [{id:null,name:'All projects'}, ...state.data.projects];
  if (list.dataset.key === JSON.stringify([items, state.project])) return;
  list.dataset.key = JSON.stringify([items, state.project]);
  list.replaceChildren(...items.map(p => button(p.name, () => {state.project=p.id;state.view='work';state.task=null;render();}, 'project-item' + (p.id === state.project ? ' active' : ''))));
}
function renderWork() {
  let tasks = state.data.tasks.filter(t => !state.project || t.project_id === state.project);
  const counts = [tasks.filter(t => ['claimed','delivered','running'].includes(t.state)).length,
    tasks.filter(t => t.state === 'queued').length, tasks.filter(t => attention.includes(t.state)).length,
    tasks.filter(t => t.state === 'completed').length];
  $('summary').replaceChildren(...['Active','Queued','Needs attention','Accepted'].map((label,i) => {
    const stat = node('div','stat');stat.append(node('strong','',counts[i]),node('span','',label));return stat;
  }));
  const filter = $('status-filter').value;
  tasks = tasks.filter(t => filter === 'all' || (filter === 'attention' && attention.includes(t.state)) ||
    (filter === 'completed' && t.state === 'completed') || (filter === 'open' && !['completed','cancelled'].includes(t.state)));
  const key = JSON.stringify([tasks, state.task, state.project, state.data.agents.map(a => [a.id,a.name])]);
  if (listKey !== key) {
    listKey = key;
    if (!tasks.length) {
      const empty = node('div','empty');
      empty.append(node('h2','',state.data.tasks.length ? 'No matching assignments' : 'Start with a clear assignment'),
        node('p','',state.data.tasks.length ? 'Choose another project or state to see its work.' : 'Create a project and connect a worker, or try the isolated rehearsal with the local text worker.'));
      if (!state.data.projects.length) empty.append(button('Create project', () => openDialog('project-dialog'), 'primary'));
      if (state.data.local_agent_id) empty.append(button('Run isolated rehearsal', runRehearsal));
      $('task-list').replaceChildren(empty);
    } else {
      $('task-list').replaceChildren(...tasks.slice().reverse().map(task => {
        const row = button('', () => {state.task=task.id;renderWork();renderDetail();}, 'task' + (state.task === task.id ? ' selected' : ''));
        row.setAttribute('aria-pressed',String(state.task === task.id));
        const head = node('div','task-top');head.append(node('strong','',task.title),badge(task.state));
        row.append(head,node('div','task-sub',name(task.agent_id) + ' · ' + when(task.updated)));
        if (task.waiting_on.length && task.state === 'queued') row.append(node('div','task-wait','Waiting for acceptance: ' + task.waiting_on.join(', ')));
        return row;
      }));
    }
  }
  renderDetail();
}
function renderDetail() {
  const task = state.data.tasks.find(t => t.id === state.task);
  const key = JSON.stringify(task);
  if (detailKey === key) return;detailKey = key;
  const detail = $('task-detail');detail.replaceChildren();
  if (!task) {detail.append(node('div','detail-empty','Select an assignment to see its owner, receipts, and evidence.'));return;}
  detail.append(badge(task.state),node('h2','detail-title',task.title),node('div','meta',name(task.agent_id) + ' · Created ' + when(task.created)));
  const attempt = task.attempts.at(-1);
  const progress = [!!attempt?.acknowledged,!!attempt?.started,task.artifacts.some(a=>a.attempt_id===attempt?.id),task.state==='completed'];
  const steps = node('div','steps');['Received','Started','Artifact','Accepted'].forEach((label,i) => steps.append(node('div','step' + (progress[i] ? ' done' : ''),label)));
  detail.append(steps,node('h3','','Instructions'),node('p','',task.instruction));
  if (attempt?.failure) detail.append(node('p','task-wait',attempt.failure));
  if (task.waiting_on.length) detail.append(node('p','task-wait','Depends on: ' + task.waiting_on.join(', ')));
  const actions = node('div','detail-actions');
  if (task.state === 'awaiting_approval') actions.append(button('Approve this assignment', () => act(task,'approve'), 'primary'));
  if (task.state === 'review') {actions.append(button('Accept result', () => act(task,'accept'), 'primary'),button('Request changes', () => act(task,'reject')));}
  if (['failed','interrupted','changes_requested'].includes(task.state)) actions.append(button('Retry assignment', () => act(task,'retry')));
  if (!['completed','cancelled'].includes(task.state)) actions.append(button('Cancel assignment', () => act(task,'cancel')));
  detail.append(actions);
  if (task.artifacts.length) {
    const artifacts = node('section','detail-section');artifacts.append(node('h3','','Evidence'));
    task.artifacts.slice().reverse().forEach((artifact,i) => {
      const section = node('details','artifact');section.open = i === 0;
      section.append(node('summary','',artifact.name + (task.accepted_artifact_id===artifact.id?' · accepted':'')),
        node('pre','',artifact.content),node('div','hash','SHA-256 ' + artifact.sha256),
        button('Download artifact', () => download(artifact.name,artifact.content,'text/plain')));
      artifacts.append(section);
    });detail.append(artifacts);
  }
  const history = node('section','detail-section');history.append(node('h3','','Handoff history'));
  task.history.slice().reverse().forEach(event => {
    const item = node('div','mini-event',eventLabel(event));item.append(node('small','',name(event.actor) + ' · ' + when(event.at)));
    if (event.data.note) item.append(node('p','',event.data.note));history.append(item);
  });detail.append(history,node('div','hash','Assignment ' + task.id + '\nPayload ' + task.payload_hash));
}
function renderAgents() {
  if (state.view !== 'agents') return;
  $('agent-list').replaceChildren(...state.data.agents.map(agent => {
    const card = node('article','agent-card');
    const online = agent.enabled && agent.last_seen && state.data.now-agent.last_seen<15;
    card.append(node('h3','',agent.name),node('div','meta',agent.provider),
      badge(!agent.enabled?'Revoked':online?'Connected':'Disconnected'),node('p','meta',agent.last_seen?'Last received ' + when(agent.last_seen):'No worker heartbeat received'),
      node('div','agent-id',agent.id));
    if (agent.enabled && agent.id !== state.data.local_agent_id) card.append(button('Revoke credential', async () => {
      if (!confirm('Revoke this worker’s access? In-flight work will be marked interrupted; the worker must observe revocation and stop.')) return;
      try {await api('/api/agents/revoke',{agent_id:agent.id});await refresh();}catch(error){notice(error.message,'error');}
    }));return card;
  }));
  if (!state.data.agents.length) $('agent-list').append(node('p','muted','No workers enrolled. Enrollment creates a scoped key; it does not launch an agent.'));
}
function eventLabel(event) {
  const words = {'task.created':'Assignment created','attempt.claimed':'Worker claimed assignment','attempt.ack':'Delivery acknowledged',
    'attempt.start':'Worker started','attempt.complete':'Artifact submitted for review','task.accept':'Result accepted',
    'task.reject':'Changes requested','task.approve':'Execution approved','task.retry':'New attempt requested','task.cancel':'Assignment cancelled',
    'attempt.interrupted':'Worker attempt interrupted','attempt.fail':'Worker reported failure','agent.enrolled':'Worker enrolled',
    'agent.revoked':'Worker credential revoked','project.created':'Project created','dispatch.paused':'Dispatch paused','dispatch.resumed':'Dispatch resumed'};
  return words[event.kind] || event.kind;
}
function renderEvents() {
  if (state.view !== 'activity') return;
  const key = JSON.stringify(state.data.events);if (eventKey===key) return;eventKey=key;
  $('event-list').replaceChildren(...state.data.events.slice().reverse().map(event => {
    const row = node('article','event-row');const body = node('div');
    const task = state.data.tasks.find(t=>t.id===event.task_id);
    body.append(node('p','',eventLabel(event)),node('small','',name(event.actor) + (task?' · ' + task.title:'') + (event.data.name?' · ' + event.data.name:'')));
    if(event.data.note) body.append(node('p','',event.data.note));row.append(node('time','',when(event.at)),body);return row;
  }));
}
function openDialog(id) {
  const dialog = $(id);dialog.querySelector('form')?.reset();
  const error = dialog.querySelector('.form-error');if(error)error.textContent='';dialog.showModal();
}
function taskOptions() {
  const project = $('task-project').value;
  $('task-deps').replaceChildren(...state.data.tasks.filter(t=>t.project_id===project).map(t=>{const option=node('option','',t.title);option.value=t.id;return option;}));
  $('worker-hint').textContent = $('task-agent').value===state.data.local_agent_id ? 'The local text worker computes fingerprints and word counts. It does not interpret instructions with a model.' : 'The enrolled worker must connect and claim this assignment. No session is launched automatically.';
}
function newTask() {
  if (!state.data.projects.length) {notice('Create a project first.');openDialog('project-dialog');return;}
  if (!state.data.agents.some(a=>a.enabled)) {notice('Enroll a worker first.');openDialog('agent-dialog');return;}
  openDialog('task-dialog');
  $('task-project').replaceChildren(...state.data.projects.map(p=>{const o=node('option','',p.name);o.value=p.id;return o;}));
  $('task-agent').replaceChildren(...state.data.agents.filter(a=>a.enabled).map(a=>{const o=node('option','',a.name);o.value=a.id;return o;}));
  if(state.project)$('task-project').value=state.project;taskOptions();
}
function act(task, action) {
  state.pendingAction={task_id:task.id,action};
  if(['accept','reject'].includes(action))state.pendingAction.artifact_id=task.artifacts.at(-1)?.id;
  openDialog('action-dialog');
  const titles={approve:'Approve execution',accept:'Accept result',reject:'Request changes',retry:'Retry assignment',cancel:'Cancel assignment'};
  const descriptions={approve:'Authorize this exact assignment and its recorded instruction. This does not approve deployment or expand the worker’s existing permissions.',
    accept:'Accept the latest submitted artifact. Dependent assignments may then become eligible to run.',reject:'Record one clear correction. The artifact remains in history; retry explicitly when ready.',
    retry:task.state==='interrupted'?'An interrupted worker may still be acting outside this service. Verify it has stopped before retrying, and record why another attempt is safe.':'Start a new attempt with the same instruction and the recorded feedback.',
    cancel:'Withdraw this assignment’s authorization. Cooperative workers must stop at their next heartbeat. This service cannot forcibly stop an external process.'};
  $('action-title').textContent=titles[action];$('action-explanation').textContent=descriptions[action];
  $('action-note').required=action==='reject'||(action==='retry'&&task.state==='interrupted');$('confirm-action').textContent=titles[action];
}
function download(filename,content,type='application/json') {
  const url=URL.createObjectURL(new Blob([content],{type}));const anchor=node('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function runRehearsal() {
  try {const result=await api('/api/rehearsal',{});state.project=result.project_id;state.task=result.task_ids[0];await refresh();notice('Rehearsal created. Review the first artifact, then approve the dependent assignment.');}
  catch(error){notice(error.message,'error');}
}
function handleForm(id, handler) {
  $(id).addEventListener('submit',async event=>{event.preventDefault();const submit=event.target.querySelector('[type=submit]');submit.disabled=true;
    try{await handler();}catch(error){(event.target.querySelector('.form-error')||$('login-error')).textContent=error.message;}finally{submit.disabled=false;}});
}
handleForm('login-form',async()=>{await api('/api/session',{token:$('operator-key').value});$('operator-key').value='';$('login-error').textContent='';await refresh();});
handleForm('project-form',async()=>{const result=await api('/api/projects',{name:$('project-name').value,description:$('project-description').value});state.project=result.id;state.view='work';$('project-dialog').close();await refresh();});
handleForm('task-form',async()=>{const result=await api('/api/tasks',{project_id:$('task-project').value,title:$('task-title').value,instruction:$('task-instruction').value,agent_id:$('task-agent').value,dependencies:[...$('task-deps').selectedOptions].map(o=>o.value),requires_approval:$('task-approval').checked});state.task=result.id;state.project=$('task-project').value;state.view='work';$('task-dialog').close();await refresh();});
handleForm('agent-form',async()=>{const result=await api('/api/agents',{name:$('agent-name').value,provider:$('agent-provider').value});state.workerKey=result;$('agent-form').hidden=true;$('agent-created').hidden=false;await refresh();});
handleForm('action-form',async()=>{await api('/api/tasks/action',{...state.pendingAction,note:$('action-note').value});$('action-dialog').close();await refresh();});
$('download-key').addEventListener('click',()=>{if(state.workerKey)download(state.workerKey.id+'.key',state.workerKey.token,'text/plain');});
$('agent-dialog').addEventListener('close',()=>{state.workerKey=null;$('agent-form').hidden=false;$('agent-created').hidden=true;});
document.querySelectorAll('.close-dialog').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{state.view=b.dataset.view;render();}));
$('add-project').addEventListener('click',()=>openDialog('project-dialog'));$('new-task').addEventListener('click',newTask);
$('add-agent').addEventListener('click',()=>openDialog('agent-dialog'));$('status-filter').addEventListener('change',renderWork);
$('task-project').addEventListener('change',taskOptions);$('task-agent').addEventListener('change',taskOptions);
$('pause').addEventListener('click',async()=>{try{await api('/api/pause',{paused:!state.data.paused});await refresh();}catch(error){notice(error.message,'error');}});
$('export').addEventListener('click',async()=>{try{download('medulla-records.json',JSON.stringify(await api('/api/export'),null,2));}catch(error){notice(error.message,'error');}});
$('sign-out').addEventListener('click',async()=>{await api('/api/logout',{});lock();});
const launchTicket = new URLSearchParams(location.hash.slice(1)).get('ticket');
if(launchTicket){
  history.replaceState(null,'','/');
  api('/api/session',{ticket:launchTicket}).then(refresh).catch(error=>{$('login-error').textContent=error.message;});
}else{refresh();}
setInterval(()=>{if(state.signedIn&&!document.hidden)refresh();},2000);
