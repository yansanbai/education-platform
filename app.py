import io
import json
import os
import sqlite3
import sys
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from pipeline import MAX_REVIEW_RETRIES, STAGES, PipelineError, doc_blocks, run_pipeline
from report_word import make_report
from task_log import save_event

root = Path(__file__).resolve().parent
load_dotenv(root / ".env")
demo = os.getenv("MOCK_GRADING") == "1"
data = Path(os.getenv("GRADER_DATA_DIR") or root / "data" / ("demo" if demo else "live"))
data.mkdir(parents=True, exist_ok=True)
Image.MAX_IMAGE_PIXELS = 20_000_000
MIB = 1024 * 1024
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@contextmanager
def database():
    db = sqlite3.connect(data / "tasks.db", timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


with database() as db:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("BEGIN IMMEDIATE")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY, title TEXT, status TEXT, result TEXT,
      error TEXT, token TEXT, lease REAL)""")
    existing = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
    for column, definition in (
        ("started_at", "REAL"), ("stage", "INTEGER DEFAULT 0"),
        ("progress", "INTEGER DEFAULT 0"), ("stage_label", "TEXT"),
        ("review_attempts", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in existing:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
    db.execute("""CREATE TABLE IF NOT EXISTS pages (
      job INTEGER, number INTEGER, image BLOB, PRIMARY KEY(job,number))""")
    db.execute("CREATE TABLE IF NOT EXISTS rubrics(job INTEGER PRIMARY KEY, document BLOB NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS reports(job INTEGER PRIMARY KEY, document BLOB NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS job_stages(
      job INTEGER, stage INTEGER, value TEXT NOT NULL, PRIMARY KEY(job,stage))""")
    db.execute("""CREATE TABLE IF NOT EXISTS figures(
      job INTEGER, number INTEGER, image BLOB NOT NULL, PRIMARY KEY(job,number))""")
    db.execute("""CREATE TABLE IF NOT EXISTS figure_revisions(
      job INTEGER, number INTEGER, prompt TEXT NOT NULL, PRIMARY KEY(job,number))""")

    db.execute("""CREATE TABLE IF NOT EXISTS task_logs(
        id INTEGER PRIMARY KEY, job INTEGER NOT NULL, attempt TEXT,
        stage INTEGER NOT NULL, event TEXT NOT NULL, message TEXT NOT NULL,
        details TEXT NOT NULL, created_at REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS task_logs_job_id ON task_logs(job,id)")
    db.execute("""CREATE TABLE IF NOT EXISTS job_id_sequence (
        id INTEGER PRIMARY KEY CHECK (id=1), last_id INTEGER NOT NULL)""")
    db.execute("""INSERT OR IGNORE INTO job_id_sequence
        SELECT 1, COALESCE(MAX(id),0) FROM jobs""")


app = FastAPI()
frontend = root / "web" / "dist"
app.mount("/assets", StaticFiles(directory=frontend / "assets", check_dir=False), name="frontend-assets")


@app.get("/")
def index():
    index_file = frontend / "index.html"
    if not index_file.is_file():
        raise HTTPException(503, "请先在 web 目录运行 npm install 和 npm run build。")
    return FileResponse(index_file, headers={"Cache-Control":"no-cache"})


TASK_FIELDS = """id,title,status,started_at,stage,
    CASE WHEN status='done' THEN 100 ELSE progress END AS progress,
    CASE WHEN status='done' THEN '已完成' ELSE stage_label END AS stage_label"""


@app.get("/api/tasks")
def tasks():
    with database() as db:
        rows = db.execute("SELECT " + TASK_FIELDS + " FROM jobs ORDER BY id DESC").fetchall()
    return {"demo":demo, "configured":bool(os.getenv("DEEPSEEK_API_KEY")),
            "seedream_configured":bool(os.getenv("ARK_API_KEY")), "tasks":[dict(row) for row in rows]}


@app.get("/api/tasks/{job}")
def detail(job: int):
    with database() as db:
        row = db.execute("SELECT " + TASK_FIELDS + """,result,error,
            EXISTS(SELECT 1 FROM reports WHERE reports.job=jobs.id) AS has_document
            FROM jobs WHERE id=?""", (job,)).fetchone()
    if row is None:
        raise HTTPException(404, "任务不存在")
    return dict(row)


def log_row(row):
    return {**dict(row), "details":json.loads(row["details"])}


def require_task(db, job):
    if db.execute("SELECT 1 FROM jobs WHERE id=?", (job,)).fetchone() is None:
        raise HTTPException(404, "任务不存在")


@app.get("/api/tasks/{job}/logs")
def task_logs(job: int, limit: int = Query(250, ge=1, le=500)):
    with database() as db:
        require_task(db,job)
        rows = db.execute("SELECT * FROM task_logs WHERE job=? ORDER BY id DESC LIMIT ?", (job,limit+1)).fetchall()
    return {"events":[log_row(row) for row in reversed(rows[:limit])], "truncated":len(rows)>limit}


@app.get("/api/tasks/{job}/logs/download")
def download_task_logs(job: int):
    with database() as db:
        require_task(db,job)

    def lines():
        last = 0
        while True:
            with database() as db:
                rows = db.execute("SELECT * FROM task_logs WHERE job=? AND id>? ORDER BY id LIMIT 200",(job,last)).fetchall()
            if not rows:
                break
            for row in rows:
                yield json.dumps(log_row(row),ensure_ascii=False)+"\n"
            last = rows[-1]["id"]

    return StreamingResponse(lines(),media_type="application/x-ndjson",
                             headers={"Content-Disposition":f'attachment; filename="task-{job}-logs.jsonl"'})


@app.get("/api/tasks/{job}/report")
def report_file(job: int):
    with database() as db:
        row = db.execute("""SELECT reports.document FROM reports
            JOIN jobs ON jobs.id=reports.job WHERE reports.job=? AND jobs.status='done'""", (job,)).fetchone()
    if row is None:
        raise HTTPException(404, "报告尚未生成")
    return Response(row["document"], media_type=DOCX_MIME,
                    headers={"Content-Disposition":f'attachment; filename="grading-report-{job}.docx"'})


@app.get("/api/tasks/{job}/figures/{number}")
def figure_file(job: int, number: int):
    with database() as db:
        row = db.execute("""SELECT figures.image FROM figures JOIN jobs ON jobs.id=figures.job
           WHERE figures.job=? AND figures.number=? AND jobs.status='done'""", (job, number)).fetchone()
    if row is None:
        raise HTTPException(404, "配图不存在")
    return Response(row["image"], media_type="image/jpeg")


@app.post("/api/tasks", status_code=201)
def upload(title: str = Form(), images: list[UploadFile] = File(), document: UploadFile = File()):
    if not title.strip() or len(title.strip()) > 100 or not 1 <= len(images) <= 10:
        raise HTTPException(400, "请填写任务名称并上传 1 至 10 张试卷图片。")
    if not (document.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "请上传包含原题和答案的 Word（.docx）文档。")
    doc = document.file.read(25 * MIB + 1)
    if len(doc) > 25 * MIB:
        raise HTTPException(413, "Word 文档最多 25 MiB。")
    try:
        doc_blocks(doc, decode_images=False)
    except PipelineError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (OSError, zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise HTTPException(400, "无法读取 Word 文档，请重新保存为 .docx 后上传。") from exc

    pages = []
    for image in images:
        raw = image.file.read(8 * MIB + 1)
        if len(raw) > 8 * MIB:
            raise HTTPException(413, "单张图片最多 8 MiB。")
        try:
            with Image.open(io.BytesIO(raw), formats=["JPEG","PNG","WEBP"]) as source:
                page = ImageOps.exif_transpose(source).convert("RGB")
                page.thumbnail((2500,2500))
                buffer = io.BytesIO()
                page.save(buffer, "JPEG", quality=93)
                pages.append(buffer.getvalue())
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(400, "图片无效或尺寸过大。") from exc
    with database() as db:
        job = db.execute("""UPDATE job_id_sequence
            SET last_id=MAX(last_id,(SELECT COALESCE(MAX(id),0) FROM jobs))+1
            WHERE id=1 RETURNING last_id""").fetchone()["last_id"]
        db.execute("INSERT INTO jobs(id,title,status,stage_label) VALUES(?,?,'queued','等待处理')",
                   (job,title.strip()))
        db.execute("INSERT INTO rubrics VALUES(?,?)", (job, doc))
        db.executemany("INSERT INTO pages VALUES(?,?,?)",
                       ((job,number,page) for number,page in enumerate(pages,1)))
        save_event(db,job,None,0,"queued","任务已提交",{"photos":len(pages),"document_name":document.filename})
    return {"id":job}


@app.delete("/api/tasks/{job}")
def delete_task(job: int):
    with database() as db:
        if not db.execute("DELETE FROM jobs WHERE id=?", (job,)).rowcount:
            raise HTTPException(404, "任务不存在")
        for table in ("pages", "rubrics", "reports", "job_stages",
                      "figures", "figure_revisions", "task_logs"):
            db.execute(f"DELETE FROM {table} WHERE job=?", (job,))
    return {"id":job}


@app.post("/api/tasks/{job}/retry")
def retry(job: int):
    with database() as db:
        changed = db.execute("""UPDATE jobs SET status='queued',error=NULL,stage_label='等待重试',review_attempts=0
            WHERE id=? AND status='failed' AND EXISTS(SELECT 1 FROM rubrics WHERE rubrics.job=jobs.id)""",
                              (job,)).rowcount
        if changed:
            stage = db.execute("SELECT stage FROM jobs WHERE id=?",(job,)).fetchone()["stage"]
            save_event(db,job,None,stage,"retry_requested","已请求重试，等待 worker 领取",{})
    if not changed:
        raise HTTPException(409, "任务无法重试。旧任务如缺少答案文档，请新建。")
    return {"id":job}


class JobRun:
    def __init__(self, job, token):
        self.job, self.token = job, token
        self.stage = 0

    def log(self, event, message, entry_id=None, **details):
        with database() as db:
            self.guard(db)
            return save_event(db,self.job,self.token,self.stage,event,message,details,entry_id)

    def guard(self, db):
        if not db.execute("UPDATE jobs SET lease=? WHERE id=? AND token=? AND status='running'",
                          (time.time()+900,self.job,self.token)).rowcount:
            raise PipelineError("任务已被其他进程领取。")

    def advance(self, stage, fraction=0, label=None):
        progress = round((stage-1+fraction)*100/len(STAGES))
        with database() as db:
            self.guard(db)
            db.execute("UPDATE jobs SET stage=?,progress=?,stage_label=? WHERE id=?",
                       (stage,progress,label or STAGES[stage-1],self.job))
            if self.stage != stage:
                save_event(db,self.job,self.token,stage,"stage_started",STAGES[stage-1],{"progress":progress})
        self.stage = stage

    def checkpoint(self, stage, action):
        with database() as db:
            row = db.execute("SELECT value FROM job_stages WHERE job=? AND stage=?",
                             (self.job,stage)).fetchone()
        if row:
            self.stage = stage
            self.log("checkpoint_reused","复用已完成阶段",name=STAGES[stage-1])
            return json.loads(row["value"])
        self.advance(stage)
        value = action()
        with database() as db:
            self.guard(db)
            db.execute("INSERT INTO job_stages VALUES(?,?,?)",
                       (self.job,stage,json.dumps(value,ensure_ascii=False)))
            save_event(db,self.job,self.token,stage,"checkpoint_saved","阶段结果已保存",{"name":STAGES[stage-1]})
        return value

    def figure(self, number):
        with database() as db:
            row = db.execute("SELECT image FROM figures WHERE job=? AND number=?",(self.job,number)).fetchone()
        return row["image"] if row else None

    def figure_prompt(self, number, default):
        with database() as db:
            row = db.execute("SELECT prompt FROM figure_revisions WHERE job=? AND number=?",
                             (self.job,number)).fetchone()
        return default + ("\n复核修正要求：" + row["prompt"] if row and row["prompt"] else "")

    def save_figure(self, number, image):
        with database() as db:
            self.guard(db)
            db.execute("INSERT OR REPLACE INTO figures VALUES(?,?,?)",(self.job,number,image))

    def reject_figures(self, rejected):
        with database() as db:
            self.guard(db)
            for item in rejected:
                db.execute("DELETE FROM figures WHERE job=? AND number=?",(self.job,item["id"]))
                db.execute("INSERT OR REPLACE INTO figure_revisions VALUES(?,?,?)",
                           (self.job,item["id"],item["replacement_prompt"] or item["reason"]))

    def reserve_review(self, reason):
        with database() as db:
            self.guard(db)
            row = db.execute("""UPDATE jobs SET review_attempts=review_attempts+1
                WHERE id=? AND review_attempts<? RETURNING review_attempts""",
                (self.job,MAX_REVIEW_RETRIES+1)).fetchone()
            if row is None:
                save_event(db,self.job,self.token,7,"review_retries_exhausted","复核自动重试已达上限",
                           {"maximum":MAX_REVIEW_RETRIES,"reason":reason})
                return None
            call_number = row["review_attempts"]
            if call_number > 1:
                retry = call_number - 1
                save_event(db,self.job,self.token,7,"review_auto_retry",f"自动重试复核 {retry}/{MAX_REVIEW_RETRIES}",
                           {"retry":retry,"maximum":MAX_REVIEW_RETRIES,"reason":reason or "恢复未完成的复核"})
            return call_number

    def execute(self):
        with database() as db:
            rows = db.execute("SELECT image FROM pages WHERE job=? ORDER BY number",(self.job,)).fetchall()
            doc = db.execute("SELECT document FROM rubrics WHERE job=?",(self.job,)).fetchone()
            title = db.execute("SELECT title FROM jobs WHERE id=?",(self.job,)).fetchone()["title"]
        if not doc or not rows:
            raise PipelineError("任务缺少试卷图片或答案文档，请新建任务。")
        report = run_pipeline([row["image"] for row in rows],doc["document"],self.checkpoint,
                              self.advance,self.figure,self.save_figure,self.reject_figures,
                              self.figure_prompt,demo,log=self.log,reserve_review=self.reserve_review)
        self.advance(8)
        word = make_report(title, report, self.figure)
        with database() as db:
            self.guard(db)
            db.execute("INSERT OR REPLACE INTO reports VALUES(?,?)",(self.job,word))
            db.execute("""UPDATE jobs SET status='done',result=?,error=NULL,token=NULL,lease=NULL,
                stage_label='已完成',progress=100 WHERE id=?""",(json.dumps(report,ensure_ascii=False),self.job))
            save_event(db,self.job,self.token,8,"completed","Word 报告已生成",{"exercises":len(report["exercises"]),"bytes":len(word)})


def worker():
    while True:
        now, token = time.time(), uuid.uuid4().hex
        with database() as db:
            job = db.execute("""UPDATE jobs SET status='running',token=?,lease=?,started_at=COALESCE(started_at,?)
                WHERE id=(SELECT id FROM jobs WHERE status='queued' OR
                (status='running' AND lease < ?) ORDER BY id LIMIT 1) RETURNING id,stage""",
                (token,now+900,now,now)).fetchone()
            if job is not None:
                db.execute("""UPDATE task_logs SET details=json_set(details,'$.status','interrupted')
                    WHERE job=? AND event='api' AND attempt<>? AND json_extract(details,'$.status')='running'""",
                    (job["id"],token))
                save_event(db,job["id"],token,job["stage"] or 0,"attempt_started","开始本次执行",{"resuming":bool(job["stage"])})
        if job is None:
            time.sleep(0.7)
            continue
        run = JobRun(job["id"],token)
        try:
            run.execute()
        except (PipelineError, httpx.RequestError) as exc:
            error = str(exc) if isinstance(exc, PipelineError) else "模型服务连接失败或超时，请重试。"
        except Exception as exc:
            print(type(exc).__name__,flush=True)
            error = "当前阶段未能生成有效结果，请重试。"
        else:
            continue
        with database() as db:
            changed = db.execute("""UPDATE jobs SET status='failed',error=?,token=NULL,lease=NULL
                          WHERE id=? AND token=?""",(error,job["id"],token)).rowcount
            if changed:
                save_event(db,job["id"],token,run.stage,"failed",error,{})


if __name__ == "__main__" and sys.argv[1:] == ["worker"]:
    worker()
