#!/usr/bin/env python3
"""无头 CLI 入口（Docker/服务器批量处理）。

用法示例：
  python cli.py init
  python cli.py import <图片或PDF> [--direction compra|venta] [--json out.json]
  python cli.py list [--direction compra|venta]
  python cli.py report balance|income [--from 2026-01-01] [--to 2026-12-31] [--out file.pdf]
  python cli.py opening-import <财务初始余额.xlsx> [--year 2026]
  python cli.py opening-list [--year 2026]
  python cli.py opening-total [--year 2026]
"""
import argparse
import datetime
import json
import os
import sys

from app import config
from app.db import database
from app.settings import load_settings


def cmd_init(_):
    database.init_db()
    print(f"✔ 数据库已初始化：{config.DB_PATH}")


def cmd_import(args):
    """OCR 识别一张或多张图片/PDF 并保存为单据。"""
    from app.ocr.engine import OCREngine, pdf_to_images
    from app.ocr.parser import parse_document

    files = []
    for f in args.files:
        if os.path.isdir(f):
            for root, _, names in os.walk(f):
                for n in sorted(names):
                    if n.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".pdf")):
                        files.append(os.path.join(root, n))
        else:
            files.append(f)
    if not files:
        print("✗ 未找到可识别的图片/PDF 文件。")
        return 1

    engine = OCREngine()
    if not engine.load():
        print(f"✗ OCR 引擎加载失败：{engine.error}")
        return 1

    ok, fail = 0, []
    for path in files:
        try:
            pages = []
            if path.lower().endswith(".pdf"):
                pages = pdf_to_images(path)
                if not pages:
                    raise RuntimeError("PDF 渲染失败（需要 PyMuPDF）")
            else:
                pages = [path]
            texts = []
            for pg in pages:
                texts.extend(engine.recognize(pg))
            doc = parse_document(texts)
            if not doc:
                raise RuntimeError("未解析出有效单据内容")
            if args.direction:
                doc["direction"] = args.direction
            doc["source_file"] = os.path.basename(path)
            doc_id = database.save_document(doc)
            ok += 1
            print(f"✔ {os.path.basename(path)} → 单据#{doc_id} "
                  f"[{doc.get('direction')}] {doc.get('doc_number','')} "
                  f"{doc.get('date') or ''} 合计 {doc.get('total') or 0}")
            if args.json:
                _dump_json(args.json, {"file": path, "document_id": doc_id, **doc})
        except Exception as e:  # noqa: BLE001
            fail.append((os.path.basename(path), str(e)))
            print(f"✗ {os.path.basename(path)}: {e}")

    print(f"完成：成功 {ok} 张，失败 {len(fail)} 张。")
    for name, err in fail:
        print(f"   ✗ {name}: {err}")
    return 0 if not fail else 1


def _dump_json(path, data):
    def _conv(v):
        if isinstance(v, (datetime.date, datetime.datetime)):
            return v.isoformat()
        return v

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_conv)
    print(f"   JSON 已写出：{path}")


def cmd_list(args):
    docs = database.list_documents(direction=args.direction)
    print(f"共 {len(docs)} 张单据：")
    for d in docs:
        print(f"  #{d['id']:>4} {d.get('date') or '无日期':<10} "
              f"{d['direction']:<6} {d.get('doc_number',''):<12} "
              f"{d.get('partner_name','')[:18]:<18} 合计 {d.get('total') or 0}")
    return 0


def cmd_report(args):
    """生成报表（默认 PDF，可 --out）。"""
    date_from = None
    date_to = None
    if args.frm:
        date_from = datetime.date.fromisoformat(args.frm)
    if args.to:
        date_to = datetime.date.fromisoformat(args.to)

    settings = load_settings()
    capital = settings.get("capital_inicial") or 0.0
    out_path = args.out
    if not out_path:
        out_path = os.path.join(
            config.DATA_DIR,
            f"informe_{args.doc_type}_{datetime.date.today().isoformat()}.pdf")
    from app.accounting.reports import export_pdf, get_report
    if out_path.lower().endswith(".pdf"):
        export_pdf(args.doc_type, date_from, date_to, capital, out_path)
        print(f"✔ 报表已生成：{out_path}")
    else:
        report, docs = get_report(args.doc_type, date_from, date_to, capital)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"report": report, "docs": docs}, f,
                      ensure_ascii=False, indent=2, default=str)
        print(f"✔ 报表数据已写出：{out_path}")
    return 0


def cmd_opening_import(args):
    database.init_db()
    res = database.import_opening_balances_from_xlsx(
        args.xlsx, year=args.year, replace=args.replace)
    mode = "清空重建" if res["replaced"] else "合并更新"
    print(f"✔ 已{mode}：科目 {res['accounts']} 个（明细科目 {res['leaf']} 个），"
          f"期初余额 {res['balances']} 条（年度 {res['year']}）。")
    return 0


def cmd_opening_list(args):
    rows = database.list_opening_balances(year=args.year)
    print(f"科目与期初余额（{args.year or '全部年度'}），共 {len(rows)} 条：")
    print(f"  {'编码':<10}{'名称':<24}{'明细':<6}{'方向':<4}"
          f"{'年初余额':>14}{'累计借方':>14}{'累计贷方':>14}{'期初余额':>14}")
    pmap = {r["code"]: (r.get("parent") or "") for r in rows}

    def depth(code):
        d, cur = 0, pmap.get(code, "")
        while cur and cur in pmap:
            d += 1
            cur = pmap.get(cur, "")
        return d

    for r in rows:
        mark = "是" if int(r.get("is_leaf", 1) or 0) else "否"
        print(f"  {'  ' * depth(r['code'])}{r['code']:<10}{r['name'][:20]:<24}"
              f"{mark:<6}{r['direction']:<4}"
              f"{r['opening_balance']:>14.2f}{r['cum_debit']:>14.2f}"
              f"{r['cum_credit']:>14.2f}{r['period_balance']:>14.2f}")
    return 0


def cmd_watch(args):
    """守护模式：轮询 inbox 目录，新放入的单据图片/PDF 自动 OCR 导入。

    适合作为 Docker 容器的主进程常驻运行：
      docker compose up -d
    之后把扫描件丢进 ./inbox/ 即可自动入库，处理日志追加到 ./inbox/watch.log。
    """
    import time
    from pathlib import Path

    from app.ocr.engine import OCREngine, pdf_to_images
    from app.ocr.parser import parse_document

    inbox = Path(args.inbox)
    out = Path(args.out)
    inbox.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    done_file = inbox / ".processed.txt"
    processed = set()
    if done_file.exists():
        processed = {ln.strip() for ln in done_file.read_text(encoding="utf-8").splitlines() if ln.strip()}

    log_file = inbox / "watch.log"
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".pdf"}

    def log(msg):
        line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
        print(line, flush=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    engine = OCREngine()
    if not engine.load():
        log(f"✗ OCR 引擎加载失败：{engine.error}")
        return 1

    database.init_db()
    log(f"👁 监听 {inbox}（每 {args.interval}s 扫描一次），新单据自动导入…")

    while True:
        try:
            files = sorted(p for p in inbox.iterdir()
                           if p.suffix.lower() in exts
                           and not p.name.startswith(".")
                           and p.name not in processed)
            for f in files:
                try:
                    pages = pdf_to_images(str(f)) if f.suffix.lower() == ".pdf" else [str(f)]
                    if not pages:
                        raise RuntimeError("PDF 渲染失败（需要 PyMuPDF）")
                    texts = []
                    for pg in pages:
                        texts.extend(engine.recognize(pg))
                    doc = parse_document(texts)
                    if not doc:
                        raise RuntimeError("未解析出有效单据内容")
                    doc["source_file"] = f.name
                    doc_id = database.save_document(doc)
                    log(f"✔ {f.name} → 单据#{doc_id} [{doc.get('direction')}] "
                        f"{doc.get('doc_number', '')} {doc.get('date') or ''} 合计 {doc.get('total') or 0}")
                except Exception as e:  # noqa: BLE001
                    log(f"✗ {f.name}: {e}")
                finally:
                    processed.add(f.name)
                    done_file.write_text("\n".join(sorted(processed)), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log(f"✗ 扫描异常：{e}")
        time.sleep(args.interval)


def cmd_opening_total(args):
    def line(label, t):
        ok = abs(t["diff"]) < 0.005
        print(f"{label}：借方合计 {t['debit']:.2f} / 贷方合计 {t['credit']:.2f} "
              f"/ 差额 {t['diff']:.2f} → {'✔ 平衡' if ok else '✗ 不平衡'}")

    line("明细科目口径", database.get_opening_balance_total(
        year=args.year, only_leaf=True))
    line("全部科目口径", database.get_opening_balance_total(year=args.year))
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="发票管理应用 - 无头命令行（Docker/服务器）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化数据库")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("watch", help="守护模式：监听 inbox 自动 OCR 导入单据（Docker 常驻）")
    p.add_argument("--inbox", default=config.INBOX_DIR, help="待识别单据目录（默认 $FACTURAS_INBOX）")
    p.add_argument("--out", default=config.OUT_DIR, help="输出目录（默认 $FACTURAS_OUT）")
    p.add_argument("--interval", type=float,
                   default=float(os.environ.get("FACTURAS_WATCH_INTERVAL", "10")),
                   help="扫描间隔秒数（默认 $FACTURAS_WATCH_INTERVAL=10）")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("import", help="OCR 识别并保存单据")
    p.add_argument("files", nargs="+", help="图片/PDF 文件或目录")
    p.add_argument("--direction", choices=["compra", "venta"], help="强制方向")
    p.add_argument("--json", help="将解析结果写出为 JSON")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("list", help="列出单据")
    p.add_argument("--direction", choices=["compra", "venta"])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("report", help="生成报表")
    p.add_argument("doc_type", choices=["balance", "income"])
    p.add_argument("--from", dest="frm")
    p.add_argument("--to", dest="to")
    p.add_argument("--out")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("opening-import", help="从《财务初始余额.xlsx》导入期初余额")
    p.add_argument("xlsx")
    p.add_argument("--year")
    p.add_argument("--replace", action="store_true",
                   help="清空现有科目与该年度期初余额后重建")
    p.set_defaults(func=cmd_opening_import)

    p = sub.add_parser("opening-list", help="列出科目与期初余额")
    p.add_argument("--year")
    p.set_defaults(func=cmd_opening_list)

    p = sub.add_parser("opening-total", help="期初余额借贷平衡校验")
    p.add_argument("--year")
    p.set_defaults(func=cmd_opening_total)

    args = parser.parse_args()
    try:
        rc = args.func(args)
    except Exception as e:  # noqa: BLE001
        print(f"✗ 执行失败：{e}")
        return 1
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
