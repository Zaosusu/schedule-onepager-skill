#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
schedule-onepager-skill · 统一数据层 CLI
=================================

一个 skill（schedule-onepager-skill）同时维护三种互不耦合的个人时间数据：
  - schedule  排期表：已确定的承诺 / 赛事（带倒计时）
  - todo      今日待办：当天可勾选动作项（不与排期表关联）
  - history   每日历史：每天做了什么的流水账

数据全部落在同一个 SQLite 库（personal.db）的三张表里，HTML 只是导出视图，
永不手工编辑。三张表之间互不读取、互不合并（硬边界）。

子命令：
  personal.py schedule add|list|export|done|delete
  personal.py todo      add|list|export|done|set
  personal.py history   add|list|stats|export

零第三方依赖（仅标准库 sqlite3 / argparse / datetime）。

DB 路径解析顺序：
  1. --db 参数
  2. 环境变量 PERSONAL_DB
  3. 脚本同级目录的 personal.db
  4. <skill 根>/my/personal.db
"""

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime


# --------------------------------------------------------------------------- #
# DB 路径解析
# --------------------------------------------------------------------------- #
def resolve_db(cli_db=None):
    if cli_db:
        return cli_db
    env = os.environ.get("PERSONAL_DB")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    sibling = os.path.join(here, "personal.db")
    if os.path.exists(sibling):
        return sibling
    skill_root = os.path.dirname(here)  # scripts/ -> skill 根
    my_db = os.path.join(skill_root, "my", "personal.db")
    return my_db  # 即便不存在也返回，get_conn 会建表


SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  date_label TEXT NOT NULL,
  iso_date   TEXT,
  weekday    TEXT,
  title      TEXT,
  role       TEXT,
  detail     TEXT,
  status     TEXT DEFAULT '',
  sort_key   TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS todo (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  todo_date  TEXT NOT NULL,
  status     TEXT DEFAULT '待办',
  task       TEXT NOT NULL,
  note       TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS history (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  log_date   TEXT NOT NULL,
  category   TEXT,
  content    TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def esc(s):
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def today_iso():
    return date.today().isoformat()


def html_lines(text):
    """多行文本转 <br> 序列。"""
    return "<br>".join(esc(line) for line in (text or "").split("\n"))


def countdown_label(iso_date, status, today):
    """返回 (标签文本, 是否高亮红)。

    状态模型极简：表里的行只有两种含义——
      - 已完成：过去发生的事（日期已过、未被删除）
      - （空）：未来的事
    取消的事根本不进表（被 delete 物理删掉），所以不存在「已取消」，
    也不存在「已过期」——只要日期已过且在表里，就视为已发生 = 已完成。
    """
    if status and status.strip() == "已完成":
        return "已完成", False
    if not iso_date:
        return "待定", False
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except ValueError:
        return "待定", False
    days = (d - today).days
    if days < 0:
        return "已完成", False   # 日期已过且仍在表内 = 已发生 = 已完成
    if days == 0:
        return "今天", True
    return f"{days} 天", days <= 12


# --------------------------------------------------------------------------- #
# schedule 子命令
# --------------------------------------------------------------------------- #
def schedule_add(args, conn):
    sort_key = args.iso if args.iso else "9999-12-31"
    conn.execute(
        "INSERT INTO schedule (date_label, iso_date, weekday, title, role, detail, status, sort_key) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (args.date_label, args.iso or None, args.weekday or "", args.title or "",
         args.role or "", args.detail or "", args.status or "", sort_key),
    )
    conn.commit()
    print("schedule 已添加")


def schedule_list(args, conn):
    today = date.today()
    if args.all:
        rows = conn.execute(
            "SELECT id, date_label, weekday, title, role, detail, status, iso_date "
            "FROM schedule ORDER BY sort_key"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, date_label, weekday, title, role, detail, status, iso_date "
            "FROM schedule WHERE iso_date >= ? ORDER BY sort_key",
            (today.isoformat(),),
        ).fetchall()
    for r in rows:
        label, _ = countdown_label(r[1], r[6], today)
        flag = "✓" if label == "已完成" else " "
        print(f"[{flag}] {r[1]} {r[2]} | {r[3]} | {r[4]} | {r[5]}")
        if args.verbose and r[5]:
            print(f"      └─ {r[5]}")


def schedule_done(args, conn):
    conn.execute("UPDATE schedule SET status='已完成' WHERE id=?", (args.id,))
    conn.commit()
    print(f"schedule #{args.id} → 已完成")


def schedule_delete(args, conn):
    conn.execute("DELETE FROM schedule WHERE id=?", (args.id,))
    conn.commit()
    print(f"schedule #{args.id} → 已删除（取消 / 不办的事项不保留，不留痕）")


def schedule_export(args, conn):
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    # 过去发生、status 仍为空的事项 = 已完成：批量转正，保持 DB 与视图一致
    conn.execute(
        "UPDATE schedule SET status='已完成' WHERE iso_date IS NOT NULL AND iso_date < ? AND (status IS NULL OR status='')",
        (today.isoformat(),),
    )
    conn.commit()
    if args.all:
        rows = conn.execute(
            "SELECT date_label, iso_date, weekday, title, role, detail, status "
            "FROM schedule ORDER BY sort_key"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT date_label, iso_date, weekday, title, role, detail, status "
            "FROM schedule WHERE iso_date >= ? ORDER BY sort_key",
            (today.isoformat(),),
        ).fetchall()
    body = []
    for r in rows:
        label, red = countdown_label(r[1], r[6], today)
        cd_color = "#c9302c" if red else ("#9aa0b4" if label in ("已完成", "待定") else "#333333")
        cd = f'<td style="padding:12px 9px;border:1px solid #d8dced;color:{cd_color};font-weight:bold;">{esc(label)}</td>'
        muted = ' color:#7d8399;' if r[6] == "已完成" else ''
        body.append(f"""      <tr>
        <td style="padding:12px 9px;border:1px solid #d8dced;color:#333333;font-weight:bold;font-size:15px;">{esc(r[0])}</td>
        <td style="padding:12px 9px;border:1px solid #d8dced;color:#333333;">{esc(r[2] or "")}</td>
        <td style="padding:12px 9px;border:1px solid #d8dced;color:{'#c9302c' if '【冲突】' in (r[3] or '') else '#0f6b7a'};font-weight:bold;">{esc(r[3] or "")}</td>
        <td style="padding:12px 9px;border:1px solid #d8dced;color:#77809e;">{esc(r[4] or "")}</td>
        <td style="padding:12px 9px;border:1px solid #d8dced;color:#333333;line-height:1.9;{muted}">{html_lines(r[5])}</td>
        {cd}
      </tr>""")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>我的排期表</title></head>
<body style="margin:0;padding:0;background-color:#f4f6fb;">
<table bgcolor="#f4f6fb" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f6fb;">
<tr><td align="center" style="padding:20px 10px;">
<table bgcolor="#ffffff" role="presentation" width="760" cellpadding="0" cellspacing="0" border="0" style="width:760px;max-width:760px;background-color:#ffffff;border:1px solid #d8dced;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;">
  <tr><td style="padding:22px 24px 16px 24px;border-bottom:3px solid #1f3fa8;">
    <div style="font-size:23px;font-weight:bold;color:#1f3fa8;letter-spacing:1px;">我的排期表</div>
    <div style="font-size:13px;color:#77809e;padding-top:6px;">更新：{today.strftime('%Y年%m月%d日')}（{['周一','周二','周三','周四','周五','周六','周日'][today.weekday()]}）· 由 personal.db 导出</div>
  </td></tr>
  <tr><td style="padding:18px 24px 0 24px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:14px;">
      <tr bgcolor="#1f3fa8" style="background-color:#1f3fa8;">
        <td style="padding:11px 9px;border:1px solid #1f3fa8;color:#ffffff;font-weight:bold;width:104px;">日期</td>
        <td style="padding:11px 9px;border:1px solid #1f3fa8;color:#ffffff;font-weight:bold;width:56px;">星期</td>
        <td style="padding:11px 9px;border:1px solid #1f3fa8;color:#ffffff;font-weight:bold;width:120px;">活动</td>
        <td style="padding:11px 9px;border:1px solid #1f3fa8;color:#ffffff;font-weight:bold;width:46px;">身份</td>
        <td style="padding:11px 9px;border:1px solid #1f3fa8;color:#ffffff;font-weight:bold;">事项</td>
        <td style="padding:11px 9px;border:1px solid #1f3fa8;color:#ffffff;font-weight:bold;width:54px;">倒计时</td>
      </tr>
{chr(10).join(body)}
    </table>
  </td></tr>
  <tr><td style="padding:22px 24px 22px 24px;">
    <div style="border-top:1px solid #e4e7f2;padding-top:12px;font-size:12px;color:#99a0bb;line-height:1.8;">
      数据源：personal.db（schedule 表）。本表只收录已确定日期的事项。倒计时按导出日动态计算。
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    out = args.out or "行程总表.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已导出排期表 → {out}（{len(rows)} 行）")


# --------------------------------------------------------------------------- #
# todo 子命令
# --------------------------------------------------------------------------- #
def todo_add(args, conn):
    d = args.date or today_iso()
    conn.execute(
        "INSERT INTO todo (todo_date, status, task, note) VALUES (?,?,?,?)",
        (d, args.status or "待办", args.task, args.note or ""),
    )
    conn.commit()
    print(f"todo 已添加（{d}）")


def todo_list(args, conn):
    # 默认只显示今天（skill 设计：todo 只装当天的事）
    if args.date:
        d = args.date
    elif args.status:
        d = None
    else:
        d = today_iso()
    if d:
        rows = conn.execute(
            "SELECT id, status, task, note FROM todo WHERE todo_date=? ORDER BY id",
            (d,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, status, task, note FROM todo WHERE status=? ORDER BY todo_date DESC, id",
            (args.status,),
        ).fetchall()
    for r in rows:
        print(f"[{r[1]}] #{r[0]} {r[2]}  — {r[3]}")


def todo_set(args, conn):
    conn.execute("UPDATE todo SET status=? WHERE id=?", (args.status, args.id))
    conn.commit()
    print(f"todo #{args.id} → {args.status}")


def todo_export(args, conn):
    color_map = {"待办": "#c9302c", "进行中": "#1f3fa8", "已完成": "#7d8399", "未完成": "#ff6600"}
    body = []

    if args.status:
        # 状态视图：跨日期筛选
        status = args.status
        rows = conn.execute(
            "SELECT todo_date, status, task, note FROM todo WHERE status=? ORDER BY todo_date DESC, id",
            (status,),
        ).fetchall()
        title = f"历史 TODO（{status}）"
        header_color = "#1f3fa8"
        subtitle = f"按状态「{status}」筛选 · 共 {len(rows)} 项 · 独立清单，不与排期表关联"
        empty_msg = f'暂无状态为「{status}」的 TODO。'
    else:
        # 日期视图：默认今天
        d = args.date or today_iso()
        rows = conn.execute(
            "SELECT status, task, note FROM todo WHERE todo_date=? ORDER BY id", (d,)
        ).fetchall()
        title = "今日 TODO"
        header_color = "#0f6b7a"
        weekday = ['周一','周二','周三','周四','周五','周六','周日'][datetime.strptime(d,'%Y-%m-%d').weekday()]
        subtitle = f"{d}（{weekday}）· 独立清单，不与排期表关联"
        empty_msg = f'{d} 暂无待办，发我今天的任务我记进来。'

    for r in rows:
        if args.status:
            d_cell, st, task, note = r
            date_badge = f'<span style="display:inline-block;background:#eef1f8;color:#5a6291;font-size:11px;padding:1px 6px;border-radius:3px;margin-right:6px;">{esc(d_cell)}</span>'
        else:
            st, task, note = r
            date_badge = ""
        c = color_map.get(st, "#333333")
        strike = ' text-decoration:line-through;color:#99a0bb;' if st == "已完成" else 'color:#333333;'
        body.append(f"""      <tr>
        <td style="padding:12px 9px;border:1px solid #d8dced;color:{c};font-weight:bold;">{esc(st)}</td>
        <td style="padding:12px 9px;border:1px solid #d8dced;line-height:1.7;{strike}">{date_badge}<b>{esc(task)}</b></td>
        <td style="padding:12px 9px;border:1px solid #d8dced;color:#77809e;font-size:12px;line-height:1.6;">{esc(note)}</td>
      </tr>""")
    if not body:
        body.append('      <tr><td colspan="3" style="padding:14px 9px;border:1px solid #d8dced;color:#99a0bb;font-size:13px;text-align:center;">'
                    f'{empty_msg}</td></tr>')
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head>
<body style="margin:0;padding:0;background-color:#f4f6fb;">
<table bgcolor="#f4f6fb" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f6fb;">
<tr><td align="center" style="padding:20px 10px;">
<table bgcolor="#ffffff" role="presentation" width="760" cellpadding="0" cellspacing="0" border="0" style="width:760px;max-width:760px;background-color:#ffffff;border:1px solid #d8dced;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;">
  <tr><td style="padding:22px 24px 16px 24px;border-bottom:3px solid {header_color};">
    <div style="font-size:23px;font-weight:bold;color:{header_color};letter-spacing:1px;">{title}</div>
    <div style="font-size:13px;color:#77809e;padding-top:6px;">{subtitle}</div>
  </td></tr>
  <tr><td style="padding:18px 24px 0 24px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:14px;">
      <tr bgcolor="{header_color}" style="background-color:{header_color};">
        <td style="padding:11px 9px;border:1px solid {header_color};color:#ffffff;font-weight:bold;width:64px;">状态</td>
        <td style="padding:11px 9px;border:1px solid {header_color};color:#ffffff;font-weight:bold;">任务</td>
        <td style="padding:11px 9px;border:1px solid {header_color};color:#ffffff;font-weight:bold;width:150px;">备注</td>
      </tr>
{chr(10).join(body)}
    </table>
  </td></tr>
  <tr><td style="padding:22px 24px 22px 24px;">
    <div style="border-top:1px solid #e4e7f2;padding-top:12px;font-size:12px;color:#99a0bb;line-height:1.8;">
      状态：<span style="color:#c9302c;font-weight:bold;">待办</span> / <span style="color:#1f3fa8;font-weight:bold;">进行中</span> / <span style="color:#7d8399;">已完成（划掉）</span>。<br>
      数据源：personal.db（todo 表）。{ '只装当天的事' if not args.status else '按状态筛选展示' }；与排期表互不干扰。
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    if args.out:
        out = args.out
    elif args.status == "已完成":
        out = "my/历史TODO.html"
    else:
        out = "my/今日TODO.html"
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已导出{title} → {out}（{len(rows)} 项）")


def todo_export_history(args, conn):
    """按日期分组导出全部 TODO 历史（类似 history export 的每日流水账）。"""
    rows = conn.execute(
        "SELECT todo_date, status, task, note FROM todo ORDER BY todo_date DESC, id"
    ).fetchall()
    if not rows:
        print("暂无 TODO 历史")
        return

    # 按日期分组
    groups = {}
    for r in rows:
        groups.setdefault(r[0], []).append(r[1:])

    today = date.today()
    sections = []
    color_map = {"待办": "#c9302c", "进行中": "#1f3fa8", "已完成": "#7d8399", "未完成": "#ff6600"}
    for d in sorted(groups.keys(), reverse=True):
        items = []
        for st, task, note in groups[d]:
            c = color_map.get(st, "#333333")
            strike = ' text-decoration:line-through;color:#99a0bb;' if st == "已完成" else 'color:#333333;'
            items.append(f'      <tr><td style="padding:11px 9px;border:1px solid #d8dced;color:{c};font-weight:bold;width:64px;vertical-align:top;">{esc(st)}</td>'
                         f'<td style="padding:11px 9px;border:1px solid #d8dced;line-height:1.7;{strike}"><b>{esc(task)}</b></td>'
                         f'<td style="padding:11px 9px;border:1px solid #d8dced;color:#77809e;font-size:12px;line-height:1.6;vertical-align:top;">{esc(note)}</td></tr>')
        weekday = ['周一','周二','周三','周四','周五','周六','周日'][datetime.strptime(d,'%Y-%m-%d').weekday()]
        sections.append(f"""  <tr><td style="padding:18px 24px 0 24px;">
    <div style="font-size:17px;font-weight:bold;color:#1f3fa8;border-left:4px solid #1f3fa8;padding-left:10px;">{esc(d)}（{weekday}）</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:14px;margin-top:10px;">
{chr(10).join(items)}
    </table>
  </td></tr>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日 TODO 历史</title></head>
<body style="margin:0;padding:0;background-color:#f4f6fb;">
<table bgcolor="#f4f6fb" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f6fb;">
<tr><td align="center" style="padding:20px 10px;">
<table bgcolor="#ffffff" role="presentation" width="760" cellpadding="0" cellspacing="0" border="0" style="width:760px;max-width:760px;background-color:#ffffff;border:1px solid #d8dced;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;">
  <tr><td style="padding:22px 24px 16px 24px;border-bottom:3px solid #1f3fa8;">
    <div style="font-size:23px;font-weight:bold;color:#1f3fa8;letter-spacing:1px;">每日 TODO 历史</div>
    <div style="font-size:13px;color:#77809e;padding-top:6px;">更新：{today.strftime('%Y年%m月%d日')}（{['周一','周二','周三','周四','周五','周六','周日'][today.weekday()]}）· 由 personal.db 导出 · 按日期倒序</div>
  </td></tr>
{chr(10).join(sections)}
  <tr><td style="padding:22px 24px 22px 24px;">
    <div style="border-top:1px solid #e4e7f2;padding-top:12px;font-size:12px;color:#99a0bb;line-height:1.8;">
      数据源：personal.db（todo 表）。按日期分组展示全部历史，与排期表互不干扰。
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    out = args.out or "每日TODO历史.html"
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已导出每日 TODO 历史 → {out}（{len(groups)} 天）")


# --------------------------------------------------------------------------- #
# history 子命令
# --------------------------------------------------------------------------- #
def history_add(args, conn):
    d = args.date or today_iso()
    conn.execute(
        "INSERT INTO history (log_date, category, content) VALUES (?,?,?)",
        (d, args.cat or "未分类", args.text),
    )
    conn.commit()
    print(f"history 已添加（{d} / {args.cat or '未分类'}）")


def history_list(args, conn):
    if args.date:
        rows = conn.execute(
            "SELECT id, category, content, created_at FROM history WHERE log_date=? ORDER BY id",
            (args.date,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, category, content, created_at FROM history ORDER BY log_date DESC, id DESC LIMIT ?",
            (args.limit,),
        ).fetchall()
    for r in rows:
        print(f"[{r[1]}] {r[2]}   (id={r[0]}, {r[3]})")


def history_stats(args, conn):
    by_date = conn.execute(
        "SELECT log_date, COUNT(*) FROM history GROUP BY log_date ORDER BY log_date DESC"
    ).fetchall()
    by_cat = conn.execute(
        "SELECT category, COUNT(*) FROM history GROUP BY category ORDER BY COUNT(*) DESC"
    ).fetchall()
    print("== 按日期 ==")
    for d, n in by_date:
        print(f"  {d}: {n} 条")
    print("== 按分类 ==")
    for c, n in by_cat:
        print(f"  {c}: {n} 条")
    total = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    print(f"总计：{total} 条")


def history_export(args, conn):
    rows = conn.execute(
        "SELECT log_date, category, content FROM history ORDER BY log_date DESC, id DESC"
    ).fetchall()
    # 按日期分组
    groups = {}
    for d, c, t in rows:
        groups.setdefault(d, []).append((c, t))
    today = date.today()
    sections = []
    for d in sorted(groups.keys(), reverse=True):
        items = []
        for c, t in groups[d]:
            items.append(f'      <tr><td style="padding:11px 9px;border:1px solid #d8dced;color:#0f6b7a;font-weight:bold;width:90px;vertical-align:top;">{esc(c)}</td>'
                         f'<td style="padding:11px 9px;border:1px solid #d8dced;color:#333333;line-height:1.7;">{esc(t)}</td></tr>')
        sections.append(f"""  <tr><td style="padding:18px 24px 0 24px;">
    <div style="font-size:17px;font-weight:bold;color:#1f3fa8;border-left:4px solid #1f3fa8;padding-left:10px;">{esc(d)}（{['周一','周二','周三','周四','周五','周六','周日'][datetime.strptime(d,'%Y-%m-%d').weekday()]}）</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:14px;margin-top:10px;">
{chr(10).join(items)}
    </table>
  </td></tr>""")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日历史记录</title></head>
<body style="margin:0;padding:0;background-color:#f4f6fb;">
<table bgcolor="#f4f6fb" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f6fb;">
<tr><td align="center" style="padding:20px 10px;">
<table bgcolor="#ffffff" role="presentation" width="760" cellpadding="0" cellspacing="0" border="0" style="width:760px;max-width:760px;background-color:#ffffff;border:1px solid #d8dced;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;">
  <tr><td style="padding:22px 24px 16px 24px;border-bottom:3px solid #1f3fa8;">
    <div style="font-size:23px;font-weight:bold;color:#1f3fa8;letter-spacing:1px;">每日历史记录</div>
    <div style="font-size:13px;color:#77809e;padding-top:6px;">更新：{today.strftime('%Y年%m月%d日')}（{['周一','周二','周三','周四','周五','周六','周日'][today.weekday()]}）· 由 personal.db 导出</div>
  </td></tr>
{chr(10).join(sections)}
  <tr><td style="padding:22px 24px 22px 24px;">
    <div style="border-top:1px solid #e4e7f2;padding-top:12px;font-size:12px;color:#99a0bb;line-height:1.8;">
      数据源：personal.db（history 表）。每天结束追加一条，HTML 仅作浏览视图。
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    out = args.out or "每日历史记录.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已导出每日历史记录 → {out}（{len(rows)} 条）")


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(description="schedule-onepager-skill 统一数据层 CLI")
    p.add_argument("--db", help="SQLite 库路径（默认：环境变量 PERSONAL_DB > 脚本同级 > <skill根>/my/personal.db）")
    sub = p.add_subparsers(dest="mode", required=True)

    # schedule
    sp = sub.add_parser("schedule", help="排期表")
    sps = sp.add_subparsers(dest="action", required=True)
    a = sps.add_parser("add", help="新增排期")
    a.add_argument("--date-label", required=True)
    a.add_argument("--iso", help="ISO 日期 YYYY-MM-DD（用于倒计时；区间取起始日）")
    a.add_argument("--weekday")
    a.add_argument("--title")
    a.add_argument("--role")
    a.add_argument("--detail", default="")
    a.add_argument("--status", default="")
    a.set_defaults(func=schedule_add)
    l = sps.add_parser("list", help="列出排期")
    l.add_argument("--verbose", action="store_true")
    l.add_argument("--all", action="store_true", help="显示全部（含历史/已过期）")
    l.set_defaults(func=schedule_list)
    e = sps.add_parser("export", help="导出排期表 HTML")
    e.add_argument("--out")
    e.add_argument("--today")
    e.add_argument("--all", action="store_true", help="导出全部（含历史/已过期）")
    e.set_defaults(func=schedule_export)
    dn = sps.add_parser("done", help="标记已完成")
    dn.add_argument("--id", type=int, required=True)
    dn.set_defaults(func=schedule_done)
    dl = sps.add_parser("delete", help="删除整行（用于取消/不办的事项，不留痕）")
    dl.add_argument("--id", type=int, required=True)
    dl.set_defaults(func=schedule_delete)

    # todo
    tp = sub.add_parser("todo", help="今日待办")
    tps = tp.add_subparsers(dest="action", required=True)
    a = tps.add_parser("add", help="新增待办")
    a.add_argument("--date", help="默认今天")
    a.add_argument("--status", default="待办")
    a.add_argument("--task", required=True)
    a.add_argument("--note", default="")
    a.set_defaults(func=todo_add)
    l = tps.add_parser("list", help="列出待办")
    l.add_argument("--date")
    l.add_argument("--status")
    l.set_defaults(func=todo_list)
    e = tps.add_parser("export", help="导出今日/历史 TODO HTML")
    e.add_argument("--out")
    e.add_argument("--date")
    e.add_argument("--status", help="按状态跨日期导出历史视图（例：已完成）")
    e.set_defaults(func=todo_export)
    eh = tps.add_parser("export-history", help="按日期分组导出全部 TODO 历史流水账")
    eh.add_argument("--out")
    eh.set_defaults(func=todo_export_history)
    st = tps.add_parser("set", help="设置状态")
    st.add_argument("--id", type=int, required=True)
    st.add_argument("--status", required=True)
    st.set_defaults(func=todo_set)
    dn = tps.add_parser("done", help="标记已完成")
    dn.add_argument("--id", type=int, required=True)
    dn.set_defaults(func=lambda a, c: todo_set(argparse.Namespace(id=a.id, status="已完成"), c))

    # history
    hp = sub.add_parser("history", help="每日历史")
    hps = hp.add_subparsers(dest="action", required=True)
    a = hps.add_parser("add", help="新增历史")
    a.add_argument("--date", help="默认今天")
    a.add_argument("--cat", help="分类")
    a.add_argument("--text", required=True)
    a.set_defaults(func=history_add)
    l = hps.add_parser("list", help="列出历史")
    l.add_argument("--date")
    l.add_argument("--limit", type=int, default=50)
    l.set_defaults(func=history_list)
    s = hps.add_parser("stats", help="统计")
    s.set_defaults(func=history_stats)
    e = hps.add_parser("export", help="导出历史 HTML")
    e.add_argument("--out")
    e.set_defaults(func=history_export)

    return p


def main():
    args = build_parser().parse_args()
    db_path = resolve_db(args.db)
    conn = get_conn(db_path)
    try:
        args.func(args, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
