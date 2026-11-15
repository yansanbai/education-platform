import {useEffect, useRef, useState} from 'react';
import {Alert, Spin} from 'antd';

export function WordPreview({url, onError}:{url: string; onError: () => void}) {
  const container = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'loading'|'ready'|'error'>('loading');
  const failure = useRef(onError);
  failure.current = onError;

  useEffect(() => {
    const controller = new AbortController();
    const element = container.current!;
    const detached = document.createElement('div');
    setStatus('loading');
    async function show() {
      try {
        const [response, {renderAsync}] = await Promise.all([
          fetch(url, {signal:controller.signal}), import('docx-preview'),
        ]);
        if (!response.ok) throw new Error('Report download failed');
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        await renderAsync(blob, detached, undefined, {className:'report-docx', ignoreLastRenderedPageBreak:true, useBase64URL:true});
        if (controller.signal.aborted) return;
        element.replaceChildren(...detached.childNodes);
        setStatus('ready');
      } catch {
        if (!controller.signal.aborted) {
          setStatus('error');
          failure.current();
        }
      }
    }
    void show();
    return () => {controller.abort(); element.replaceChildren();};
  },[url]);

  return <>
    {status==='loading' && <div className="loading"><Spin/><p>正在加载 Word 预览</p></div>}
    {status==='error' && <Alert showIcon type="warning" className="notification" message="Word 排版预览暂不可用，下面可查看报告正文。"/>}
    <div className="word-preview" ref={container} hidden={status!=='ready'}/>
  </>;
}
