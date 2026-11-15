import {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Alert, Badge, Button, Card, ConfigProvider, Drawer, Empty, Form, Input, Modal, Progress, Result, Select, Space, Spin, Table, Tag, Upload} from 'antd';
import {ArrowLeftOutlined, ArrowRightOutlined, InboxOutlined, PlusOutlined, ProfileOutlined, SearchOutlined, SnippetsOutlined} from '@ant-design/icons';
import type {UploadFile} from 'antd';
import zhCN from 'antd/locale/zh_CN';
import 'antd/dist/reset.css';
import './style.css';

import {api, labels, link, taskTime, usePolling} from './tasks';
import type {Report, Status, Task, TaskDetail, TaskList} from './tasks';
import {ReportPage} from './ReportPage';

type Fields = {title:string};
const badge = {queued:'default', running:'processing', done:'success', failed:'error'} as const;

function StatusBadge({value}:{value:Status}) {
  return <Badge status={badge[value]} text={labels[value]} />;
}

function CreateTask({open, close, created}:{open:boolean;close:()=>void;created:(id:number)=>void}) {
  const [form] = Form.useForm<Fields>();
  const [files,setFiles] = useState<UploadFile[]>([]);
  const [docs,setDocs] = useState<UploadFile[]>([]);
  const [docError,setDocError] = useState('');
  const [error,setError] = useState('');
  const [fileError,setFileError] = useState('');
  const [busy,setBusy] = useState(false);

  async function submit(values:Fields) {
    if (!files.length) {setFileError('请上传至少一张作业图片。');return;}
    if (!docs[0]?.originFileObj) {setDocError('请上传包含原题和答案的 Word 文档。');return;}
    setBusy(true);
    setError('');
    try {
      const body = new FormData();
      body.set('title',values.title.trim());
      body.set('document',docs[0].originFileObj!,docs[0].name);
      for (const file of files) if (file.originFileObj) body.append('images',file.originFileObj,file.name);
      const task = await api<{id:number}>('',{method:'POST',body});
      form.resetFields();
      setFiles([]);
      setDocs([]);
      setDocError('');
      setFileError('');
      created(task.id);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <Drawer title="新建批改任务" open={open} onClose={close} width="min(100vw, 510px)"
    maskClosable={!busy} keyboard={!busy} closable={!busy}
    footer={<Space style={{display:'flex',justifyContent:'flex-end'}}><Button disabled={busy} onClick={close}>取消</Button><Button type="primary" loading={busy} onClick={()=>form.submit()}>提交批改</Button></Space>}>
    <Form form={form} layout="vertical" onFinish={submit} disabled={busy}>
      {error && <Alert className="notification" type="error" showIcon message={error}/>}
      <Form.Item name="title" label="任务名称" rules={[{required:true,whitespace:true,message:'请输入任务名称'}]}>
        <Input maxLength={100} placeholder="例如：周三分数练习"/>
      </Form.Item>
      <Form.Item label="试卷图片" required validateStatus={fileError ? 'error' : undefined} help={fileError || undefined}>
        <Upload.Dragger multiple maxCount={10} accept="image/jpeg,image/png,image/webp" fileList={files}
          beforeUpload={file => {
            if (!/\.(jpe?g|png|webp)$/i.test(file.name) || file.size > 8*1024*1024) {
              setFileError('请选择 JPG、PNG 或 WebP 图片，每张不超过 8 MiB。');
              return Upload.LIST_IGNORE;
            }
            setFileError('');
            return false;
          }} onChange={({fileList})=>setFiles(fileList)}>
          <p className="ant-upload-drag-icon"><InboxOutlined/></p>
          <p className="ant-upload-text">点击选择或拖入试卷图片</p>
          <p className="ant-upload-hint">同一位学生的答卷，顺序不限。最多 10 张，每张 8 MiB</p>
        </Upload.Dragger>
      </Form.Item>
      <Form.Item label="原题与答案文档" required validateStatus={docError ? 'error' : undefined} help={docError || '一份包含试题原文和参考答案的 Word 文档，最多 25 MiB。'}>
        <Upload accept=".docx" maxCount={1} fileList={docs} beforeUpload={file=>{
          if(!/\.docx$/i.test(file.name) || file.size>25*1024*1024){setDocError('请选择不超过 25 MiB 的 .docx 文档。');return Upload.LIST_IGNORE}
          setDocError('');return false;
        }} onChange={({fileList})=>setDocs(fileList)}>
          <Button icon={<ProfileOutlined/>}>选择 Word 文档</Button>
        </Upload>
      </Form.Item>
    </Form>
  </Drawer>;
}

function TaskIndex({state,onCreate,onDeleted}:{state:ReturnType<typeof usePolling<TaskList>>;onCreate:()=>void;onDeleted:()=>void}) {
  const [query,setQuery] = useState('');
  const [filter,setFilter] = useState<Status>();
  const [selected,setSelected] = useState<Task|null>(null);
  const [deleting,setDeleting] = useState(false);
  const [deleteError,setDeleteError] = useState('');
  const tasks = state.data?.tasks ?? [];
  const visible = tasks.filter(task => (!filter || task.status === filter) && task.title.toLowerCase().includes(query.trim().toLowerCase()));
  const create = <Button type="primary" icon={<PlusOutlined/>} onClick={onCreate}>新建任务</Button>;

  async function removeTask() {
    if (!selected || deleting) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api('/'+selected.id,{method:'DELETE'});
      setSelected(null);
      onDeleted();
    } catch (error) {
      setDeleteError((error as Error).message);
    } finally {
      setDeleting(false);
    }
  }

  return <>
    <div className="page-title"><h1>批改任务</h1><p>管理作业批改进度，查看逐题反馈与错题延伸练习。</p></div>
    {state.error && <Alert className="notification" showIcon type="error" message={state.error}/>}
    {!state.data ? (!state.error && <div className="loading"><Spin/></div>) :
      <Card className="surface" styles={{body:{padding:0}}}>
        {tasks.length === 0 ? <div className="empty-state">
          <div className="empty-icon"><SnippetsOutlined/></div>
          <h2>还没有批改任务</h2>
          <p>上传学生试卷与答案文档，即可开始批改。</p>
          {create}
        </div> : <>
          <div className="toolbar">
            <Space wrap>
              <Input allowClear aria-label="搜索任务" prefix={<SearchOutlined className="muted"/>} placeholder="搜索任务名称" value={query} onChange={e=>setQuery(e.target.value)}/>
              <Select aria-label="筛选状态" allowClear placeholder="全部状态" style={{width:126}} value={filter} onChange={setFilter}
                options={Object.entries(labels).map(([value,label])=>({value,label}))}/>
            </Space>
            {create}
          </div>
          <Table<Task> rowKey="id" dataSource={visible} scroll={{x:900}}
            pagination={visible.length>10 ? {pageSize:10,showSizeChanger:false} : false}
            locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的任务"/>}}
            columns={[
              {title:'任务名称',dataIndex:'title',render:(title)=><span className="task-name"><ProfileOutlined aria-hidden="true"/> {title}</span>},
              {title:'状态',dataIndex:'status',width:145,render:(value:Status)=><StatusBadge value={value}/>},
              {title:'开始时间',width:177,render:(_,task)=>taskTime(task.started_at)},
              {title:'当前阶段与进度',width:240,render:(_,task)=><div className="list-progress">
                <span>{task.stage_label || (task.status==='queued'?'等待处理':labels[task.status])}</span>
                <Progress percent={task.progress || 0} size="small" format={percent=>percent+'%'} status={task.status==='failed'?'exception':task.status==='running'?'active':undefined}/>
              </div>},
              {title:'操作',width:170,render:(_,task)=><Space size="small">
                <Button type={task.status==='done'?'primary':'text'} size="small" href={link(task.id)} aria-label={'查看 '+task.title}>
                  {task.status==='done'?'查看报告':'查看详情'} <ArrowRightOutlined/>
                </Button>
                <Button type="text" danger size="small" aria-label={'删除 '+task.title} onClick={()=>{
                  setSelected(task);
                  setDeleteError('');
                }}>删除</Button>
              </Space>},
            ]}/>
        </>}
      </Card>}
    <Modal title="删除任务" open={selected!==null}
      okText="删除任务" okButtonProps={{danger:true}} cancelText="取消" confirmLoading={deleting}
      keyboard={!deleting} maskClosable={!deleting} closable={!deleting}
      cancelButtonProps={{disabled:deleting}} onCancel={()=>{if (!deleting) setSelected(null);}}
      onOk={removeTask}>
      <p>将永久删除「{selected?.title}」及其试卷、报告和配图，删除后无法恢复。</p>
      {selected?.status==='running' && <p>已经发出的模型请求可能仍会完成。</p>}
      {deleteError && <Alert showIcon type="error" message={deleteError}/>}
    </Modal>
  </>;
}

function Detail({id}:{id:number}) {
  const [revision,setRevision] = useState(0);
  const [busy,setBusy] = useState(false);
  const [retryError,setRetryError] = useState('');
  const {data:task,error,missing} = usePolling<TaskDetail>('/'+id,revision);
  async function retry() {
    setBusy(true);
    setRetryError('');
    try {await api('/'+id+'/retry',{method:'POST'});setRevision(v=>v+1);}
    catch (error) {setRetryError((error as Error).message);}
    finally {setBusy(false);}
  }
  const report:Report|null = task?.result ? JSON.parse(task.result) : null;
  return <>
    <a className="back" href="#/"><ArrowLeftOutlined/> 返回任务列表</a>
    {missing ? <Result status="404" title="任务不存在" subTitle="请返回列表选择一个任务。"/> :
      <>
        {error && <Alert className="notification" showIcon type="error" message={error}/>}
        {!task ? (!error && <div className="loading"><Spin/></div>) : <>
          <div className="page-title detail-heading"><h1>{task.title}</h1><StatusBadge value={task.status}/></div>
          {task.status==='failed' && <Card><Alert showIcon type="error" message={retryError || task.error || '批改失败'} action={<Button loading={busy} onClick={retry}>重试</Button>}/></Card>}
          {(task.status==='queued' || task.status==='running') && <Card className="loading"><Spin/><h2>{task.stage_label || labels[task.status]}</h2><Progress className="detail-progress" percent={task.progress || 0} status="active"/><p>任务会在后台继续处理，进度自动更新。</p></Card>}
          {report && <ReportPage task={task} report={report}/>}
        </>}
      </>}
  </>;
}

function Workspace() {
  const [route,setRoute] = useState(location.hash);
  const [open,setOpen] = useState(false);
  const [revision,setRevision] = useState(0);
  const list = usePolling<TaskList>('',revision);
  useEffect(()=>{
    const update = () => setRoute(location.hash);
    window.addEventListener('hashchange',update);
    return ()=>window.removeEventListener('hashchange',update);
  },[]);
  const match = /^#\/tasks\/(\d+)$/.exec(route);
  const id = match ? Number(match[1]) : null;
  return <>
    <header className="top"><div className="frame masthead">
      <a className="brand" href="#/"><span className="brand-icon"><ProfileOutlined/></span>作业批改工作台</a>
      <a className="nav-link" href="#/" aria-current={id===null?'page':undefined}>任务列表</a>
      {list.data?.demo && <Tag className="demo">演示模式</Tag>}
    </div></header>
    <main className="frame main">
      {list.data && !list.data.demo && !list.data.configured && <Alert className="notification" type="warning" showIcon message="请配置 DeepSeek API Key 后启动真实批改。"/>}
      {list.data && !list.data.demo && list.data.configured && !list.data.seedream_configured && <Alert className="notification" type="warning" showIcon message="需要配图的练习会使用火山方舟 API Key。"/>}
      {id===null ? <TaskIndex state={list} onCreate={()=>setOpen(true)} onDeleted={()=>setRevision(v=>v+1)}/> : <Detail key={id} id={id}/>}
    </main>
    <CreateTask open={open} close={()=>setOpen(false)} created={id=>{setOpen(false);setRevision(v=>v+1);location.hash=link(id);}}/>
  </>;
}

createRoot(document.getElementById('root')!).render(<ConfigProvider locale={zhCN} theme={{token:{
  colorPrimary:'#416dab',colorText:'#172132',colorTextSecondary:'#526175',colorBorder:'#dce4ef',
  borderRadius:8,controlHeight:38,fontFamily:"Inter, 'Microsoft YaHei UI', system-ui, sans-serif",
},components:{Table:{headerBg:'#f7f9fc',headerColor:'#536178',rowHoverBg:'#f3f7fd'}}}}><Workspace/></ConfigProvider>);
