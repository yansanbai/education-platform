# 作业批改工作台

本机运行的 React、TypeScript、Vite 和 Ant Design 前端，FastAPI 提供 API，独立 worker 从 SQLite 持久队列取任务。新任务须同时上传同一位学生的答卷照片（上传顺序不限）和一份含原题、参考答案与解析的 .docx。文档可以先试题后答案，也可逐题排列。

## 启动

安装 Python 3.12 和 Node.js（支持当前 Vite 所需版本）。首次运行时在项目目录安装依赖：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd web
npm ci
npm run build
cd ..
~~~

复制 .env.example 为 .env，在本机填写 DEEPSEEK_API_KEY 和火山方舟 ARK_API_KEY。SEEDREAM_MODEL 可指定账号已开通的模型 ID 或推理接入点。

~~~powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
~~~

打开 http://127.0.0.1:8000 。加 -Demo 可以用内置示例测试上传和下载，演示数据单独保存，不调用模型。实际答卷照片会发送给 DeepSeek，建议事先遮盖学生姓名和学号。

## 前端开发

保持 FastAPI 运行，在 web 目录执行 npm run dev，访问 Vite 打印的地址。Vite 将 /api 转发到本机 8000。npm run typecheck 检查 TypeScript，npm run build 构建 web/dist。FastAPI 在生产模式提供该目录的入口和资源，浏览器无需 Node.js。

## 后台流程

1. DeepSeek 逐页读取学生作答和题号。
2. DeepSeek 按内容拆分 Word 的原题、答案与解析。
3. 后台读取卷面页码，结合原题、全部答卷图和初读结果复核页序、题号与作答。页序无法确定时，根据题号和题干匹配续题，存疑的作答标待复核。
4. DeepSeek 对照标准答案批改。初读与复核冲突时标待复核，报告以已复核的学生作答为准。
5. 每条明确错题出两道变式，实质改变情境、条件或设问。
6. DeepSeek 为每道练习规划零张、一张或多张图，Seedream 只生成计划中的图片。
7. DeepSeek 核对实图、题干、选项和参考答案。
8. 生成含错题分析和延伸练习的 Word 文档。任务详情提供网页预览和下载。

重试复用已落盘结果。首次复核不通过后自动重试最多三次。只重绘被退回的配图，然后再次复核。达到上限后可手动重试，沿用已有结果。旧版本已完成任务仍可查看原结果。旧任务缺少答案文档时，请用新版表单重新上传。数据保存在 data 下，队列执行时需要保持电脑与服务运行。

### 排查任务

日志存放在 data/live/tasks.db 的 task_logs 表。演示模式使用 data/demo/tasks.db。记录按 job（任务 ID）、attempt（执行批次）和 stage（阶段）区分，包含 API 状态、耗时、用量、复核退回原因及自动重试序号。密钥、上传原图和完整请求体不写入日志。

在 PowerShell 执行以下命令查看任务 2（把 2 换成所查任务的 ID）：

~~~powershell
(Invoke-RestMethod http://127.0.0.1:8000/api/tasks/2/logs).events | ConvertTo-Json -Depth 10
Invoke-WebRequest http://127.0.0.1:8000/api/tasks/2/logs/download -OutFile task-2-logs.jsonl
~~~

也可以用 SQLite 查看日志：

~~~sql
SELECT id, attempt, stage, event, message, details
FROM task_logs
WHERE job = 2
ORDER BY id;
~~~
