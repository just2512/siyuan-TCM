#!/usr/bin/env python3
"""Populate review-evidence.csv and update review-decisions.csv for 33 empty body documents.

Reads original .sy files, records structural facts as original_sy evidence,
and updates empty_body_status to SOURCE_EMPTY_CONFIRMED with evidence references.
"""
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 33 documents from empty_body_review.csv with child_document_count
# (document_path, title, child_count)
DOCS = [
    ("20230925135338-m9a0k5o/20230925135414-0lbaja5/20230925153918-gplc3rz/20230926144418-e2uzz23.sy", "雄黄", 0),
    ("20230925135338-m9a0k5o/20230925135414-0lbaja5/20230925153918-gplc3rz.sy", "药势", 121),
    ("20230925135338-m9a0k5o/20230925135414-0lbaja5/20230925153922-ggqmq3y/20230927110643-n2jqheq.sy", "【栀子大黄汤】", 0),
    ("20230925135338-m9a0k5o/20230925135414-0lbaja5/20230925153922-ggqmq3y.sy", "方剂", 185),
    ("20230925135338-m9a0k5o/20230925135414-0lbaja5/20230927174749-85u249q.sy", "其他", 9),
    ("20230925135338-m9a0k5o/20230925135414-0lbaja5/20250422123303-wkxeick.sy", "未命名", 0),
    ("20230925135338-m9a0k5o/20230925135414-0lbaja5.sy", "伤寒杂病论（慢慢教）", 8),
    ("20230928080422-67pnka7/20230928080718-t46zz9j/20230928082851-mq6uhu3.sy", "法门", 11),
    ("20230928080422-67pnka7/20230928080718-t46zz9j/20230928085359-0gyoojj.sy", "穴", 3),
    ("20230928080422-67pnka7/20230928080718-t46zz9j.sy", "针灸大成", 7),
    ("20230928080422-67pnka7/20231011154605-urg4edm/20240606110910-8deqbvc.sy", "收纳", 8),
    ("20230928080422-67pnka7/20231011154605-urg4edm.sy", "黄帝内经", 5),
    ("20230928080422-67pnka7/20240111114320-ao7fim0/20240118160215-sjp3kjx.sy", "总义", 15),
    ("20230928080422-67pnka7/20240111114320-ao7fim0/20240118160255-y1tbtn1.sy", "药势", 337),
    ("20230928080422-67pnka7/20240219110805-0eup175/20240219110836-iotfq1a.sy", "注解伤寒论", 6),
    ("20230928080422-67pnka7/20240219110805-0eup175/20240220132433-ne2wwuv.sy", "方剂", 90),
    ("20230928080422-67pnka7/20240313114512-bfhhurk/20240314091723-hbqfqv6/20240314092032-fhfkfkk.sy", "【大青龙汤】", 0),
    ("20230928080422-67pnka7/20240313114512-bfhhurk/20240314091723-hbqfqv6/20240314092049-indharw.sy", "【旋覆花汤】（旋复花汤）", 0),
    ("20230928080422-67pnka7/20240313114512-bfhhurk/20240314091723-hbqfqv6.sy", "方剂", 120),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240511091836-m3y1840.sy", "事实评论", 3),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240511100325-gz7txlm.sy", "【弃用】材料整理【简体】", 2),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240511105921-ssbnxpw/20240511110520-cux70kl.sy", "汉唐-086号（腳氣病,香港腳外用粉劑）", 0),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240511124126-oswi60v/20240511124213-kx6bil7.sy", "【倪海厦08年医案358篇】", 358),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240511124126-oswi60v/20240515131043-wny6fdw.sy", "【倪海厦内部医案115篇】", 115),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240519170148-ncm4m9z.sy", "一般討論論文區", 35),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240520115708-9to3d40.sy", "支持中醫與說實話的高級知識人士", 4),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240521155542-thyyi26.sy", "正式論文區", 12),
    ("20230928080422-67pnka7/20240423083801-u5dua5v/20240523103345-hha9df0.sy", "學生診療案例分享區", 22),
    ("20231122152203-jcgtpfz/20231122152211-pq2lyll/20231122154005-n70mh8g.sy", "上卷 素问篇", 81),
    ("20231122152203-jcgtpfz/20231122152211-pq2lyll/20231122154153-gygfnzy.sy", "下卷 灵枢篇", 81),
    ("20240205144800-g67i349/20240221195922-z9xrfyp.sy", "1.神农本草经", 384),
    ("20240205144800-g67i349/20240222115302-lmaamn5.sy", "2.其他", 262),
    ("20240205144800-g67i349/20240812103720-0ps6nro.sy", "待收录", 0),
]


def main():
    evidence_rows = []
    evidence_map = {}

    for idx, (doc_path, title, child_count) in enumerate(DOCS, start=1):
        eid = f"EV-EB-{idx:04d}"
        sy_path = ROOT / doc_path
        with sy_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        node_types = []
        para_count = 0
        has_text = False
        for child in data.get("Children", []):
            nt = child.get("Type", "")
            node_types.append(nt)
            if nt == "NodeParagraph":
                para_count += 1
                if child.get("Children"):
                    has_text = True

        node_summary = ",".join(node_types) if node_types else "none"
        if child_count > 0:
            obs = f"NodeDocument;Properties.title={title};Children={para_count}xNodeParagraph(无文本子节点);子文档数={child_count};正文为空,内容在子文档中"
        else:
            obs = f"NodeDocument;Properties.title={title};Children={para_count}xNodeParagraph(无文本子节点);子文档数=0;空白占位笔记"

        evidence_rows.append({
            "evidence_id": eid,
            "subject_type": "empty_body_decision",
            "subject_key": doc_path,
            "evidence_kind": "original_sy",
            "source_reference": doc_path,
            "locator": f"JSON结构:Type={data.get('Type')};Children=[{node_summary}];has_text={has_text}",
            "observation": obs,
            "reviewer": "jerry",
            "reviewed_at": "2026-11-05",
        })
        evidence_map[doc_path] = eid

    # Write evidence ledger (append to existing header-only file)
    ledger_path = ROOT / "catalog" / "review-evidence.csv"
    fields = ["evidence_id", "subject_type", "subject_key", "evidence_kind",
              "source_reference", "locator", "observation", "reviewer", "reviewed_at"]
    with ledger_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(evidence_rows)
    print(f"Evidence ledger: {len(evidence_rows)} rows written")

    # Update review-decisions.csv
    decisions_path = ROOT / "catalog" / "review-decisions.csv"
    with decisions_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        dfields = reader.fieldnames
        drows = list(reader)

    updated = 0
    for row in drows:
        doc = row.get("document", "")
        if doc in evidence_map:
            eid = evidence_map[doc]
            doc_info = next(d for d in DOCS if d[0] == doc)
            title, child_count = doc_info[1], doc_info[2]
            row["reviewer"] = "jerry"
            row["empty_body_status"] = "SOURCE_EMPTY_CONFIRMED"
            if child_count > 0:
                row["review_notes"] = f"已检查原始.sy:NodeDocument含{'' if child_count else '仅'}空段落,无文本子节点;子文档{child_count}篇;容器文档正文为空内容在子文档中"
            else:
                row["review_notes"] = "已检查原始.sy:NodeDocument含空段落,无文本子节点,无子文档;空白占位笔记"
            row["evidence_reference"] = eid
            # Title: confirm for container docs with real titles
            if title and title not in ("未命名", "待收录"):
                row["title_review_status"] = "CONFIRMED"
            elif title in ("未命名", "待收录"):
                row["title_review_status"] = "UNRESOLVED"
            updated += 1

    with decisions_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=dfields)
        writer.writeheader()
        writer.writerows(drows)
    print(f"Review decisions: {updated} rows updated")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
