import {useState} from 'react';
import {WordPreview} from './WordPreview';
import {Button, Card} from 'antd';
import {DownloadOutlined} from '@ant-design/icons';
import {questionNumber, taskTime} from './tasks';
import type {Report, TaskDetail} from './tasks';

export function ReportPage({task,report}:{task:TaskDetail;report:Report}) {
  const [fallback, setFallback] = useState(false);
  const wrong = report.questions.filter(item=>item.verdict==='错误' || item.verdict==='部分正确');
  const statuses = ['未作答','未拍到','待复核'];
  return <>
    <div className="report-toolbar">
      <span>{task.started_at ? '开始于 '+taskTime(task.started_at) : ''}</span>
      {task.has_document && <Button type="primary" icon={<DownloadOutlined/>} href={'/api/tasks/'+task.id+'/report'}>下载 Word 文档</Button>}
    </div>
    {task.has_document && <WordPreview url={'/api/tasks/'+task.id+'/report'} onError={()=>setFallback(true)}/>}
    {(!task.has_document || fallback) && <Card className="surface report-paper">
      <h2 className="report-title">{task.title}</h2>
      {report.demo && <p>演示报告</p>}
      {!task.has_document && report.summary && <p>{report.summary}</p>}
      <h3>一、错题批改</h3>
      {!wrong.length && <p>本次未发现可确认的错题。</p>}
      {wrong.map((item,index)=><section className="report-question" key={index}>
        <h4>第 {questionNumber(item)} 题</h4>
        {item.student_answer!==undefined && <p><strong>学生作答</strong> {item.student_answer}</p>}
        {item.correct_answer && <p><strong>正确答案</strong> {item.correct_answer}</p>}
        {item.feedback && <p className="preserve"><strong>错误分析</strong> {item.feedback}</p>}
      </section>)}
      {statuses.map(status=>{const numbers=report.questions.filter(item=>item.verdict===status).map(questionNumber);return numbers.length?<p key={status}><strong>{status}</strong> {numbers.join('、')}</p>:null})}
      {report.coverage_warnings?.map(item=><p key={questionNumber(item)}>
        <strong>第 {questionNumber(item)} 题部分作答待复核</strong> {item.evidence}
      </p>)}
      {!!report.unlinked?.length && <>
        <h4>未关联的初读作答（待复核）</h4>
        {report.unlinked.map(item=><section key={item.record_id}>
          <p>照片 {item.photo}　{item.evidence}</p>
          <p className="preserve">{[...item.steps, item.final].filter(Boolean).join('\n')}</p>
        </section>)}
      </>}
      <h3>二、延伸练习</h3>
      {!report.exercises.length && <p>暂无延伸练习。</p>}
      {report.exercises.map((item,index)=><section className="report-question" key={index}>
        <h4>{index+1}. {task.has_document ? '对应原卷第 '+item.source+' 题' : item.source}</h4>
        <p className="preserve">{item.question}</p>
        {(item.images ?? (item.image ? [item.image] : [])).map((id,label,images)=><figure className="report-figure-group" key={id}>
          <img className="report-figure" src={'/api/tasks/'+task.id+'/figures/'+id} alt={'练习 '+(index+1)+' 图 '+(label+1)} />
          {images.length>1 && <figcaption>图 {label+1}</figcaption>}
        </figure>)}
        {item.options?.map((option,index)=><p className="report-option" key={index}>{option}</p>)}
      </section>)}
      {!!report.exercises.length && <details className="answer-key">
        <summary>延伸练习参考答案</summary>
        {report.exercises.map((item,index)=><p className="preserve" key={index}><strong>{index+1}. {item.answer}</strong>{item.solution && <><br/>{item.solution}</>}</p>)}
      </details>}
    </Card>}
  </>;
}

